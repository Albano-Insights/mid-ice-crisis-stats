"""Scrapes stats.panthers.timetoscore.com into data/raw/**.

For every team_id listed in data/franchises.json, probes every season id from 0 up to a bit past the
newest season any franchise has played (so a brand-new season is picked up automatically before anyone
edits the config), records that team's games + season stat tables, and the full box score for every
completed game. Then, for each season touched, finds every OTHER team in our own division that season
(from the standings page) and scrapes their schedules + box scores too -- this is what makes division-wide
trends/leaderboards possible instead of just our own roster. Already-cached raw files are reused so repeat
runs (e.g. the nightly GitHub Action) only do network work for new/updated games; a box score is shared
between both teams in a game, so it's only ever fetched once regardless of how many division teams'
schedules reference it.

Finally, for the Player Spotlight, the career page of every skater who has appeared in our division
(ours and every opponent's) is fetched -- it spans every league on the site, not just ours -- along
with the standings + division player tables of each configured adult league for every season those
careers touch (cached, except each league's current season), so the build step can place each stint
in a division and rank it. Career pages are re-fetched only for players active somewhere this season.

Usage: python scripts/scrape.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import ttscore_client as tt
from lib import youtube_client as yt
from lib import daysmart_client as ds

ROOT = Path(__file__).parent.parent
DATA_RAW = ROOT / "data" / "raw"
FRANCHISES_PATH = ROOT / "data" / "franchises.json"
SEASON_LABELS_PATH = ROOT / "data" / "raw" / "season_labels.json"
YOUTUBE_DIR = DATA_RAW / "youtube"
YOUTUBE_VIDEOS_PATH = DATA_RAW / "youtube_videos.json"
RINK_EVENTS_PATH = DATA_RAW / "rink_events.json"
PLAYERS_DIR = DATA_RAW / "players"
LEAGUES_DIR = DATA_RAW / "leagues"
RINK_EVENTS_WINDOW_DAYS = 45  # how far ahead to pull public rink events for the calendar overlay

LEAGUE = 4
STAT_CLASS = 1
SEASON_PROBE_BUFFER = 5  # look this many season-ids past the newest one we know about


def _season_dir(season_id: int) -> Path:
    d = DATA_RAW / "seasons" / str(season_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)


def load_franchises() -> dict:
    """Only the actual franchise entries -- excludes sibling config keys in the same file, like
    'rink_calendars', that aren't shaped like a franchise (see load_rink_calendars)."""
    data = _load_json(FRANCHISES_PATH, {})
    return {k: v for k, v in data.items() if k != "rink_calendars"}


def load_rink_calendars() -> list[dict]:
    return _load_json(FRANCHISES_PATH, {}).get("rink_calendars", [])


def max_known_season(franchises: dict) -> int:
    seasons = [0]
    for f in franchises.values():
        for team in f["team_ids"].values():
            seasons.extend(team.get("seasons", []))
    return max(seasons)


def fetch_standings_cached(season_id: int) -> list[dict]:
    path = _season_dir(season_id) / "standings.json"
    cached = _load_json(path, None)
    if cached is not None:
        return cached
    html = tt.fetch("display-stats", season=season_id, league=LEAGUE, stat_class=STAT_CLASS)
    rows = tt.parse_standings(html)
    _save_json(path, rows)

    labels = _load_json(SEASON_LABELS_PATH, {})
    labels.update(tt.parse_season_options(html))
    _save_json(SEASON_LABELS_PATH, labels)

    return rows


def fetch_team_season(team_id: int, season_id: int) -> dict:
    html = tt.fetch("display-schedule", team=team_id, season=season_id, league=LEAGUE, stat_class=STAT_CLASS)
    return tt.parse_team_page(html)


def fetch_boxscore_cached(season_id: int, game_id: int) -> dict:
    path = _season_dir(season_id) / f"boxscore_{game_id}.json"
    cached = _load_json(path, None)
    if cached is not None:
        return cached
    html = tt.fetch("oss-scoresheet", game_id=game_id, mode="display")
    box = tt.parse_boxscore(html, game_id)
    _save_json(path, box)
    return box


def fetch_league_stats_cached(season_id: int, level_id: int) -> list[dict]:
    path = _season_dir(season_id) / f"league_stats_level_{level_id}.json"
    cached = _load_json(path, None)
    if cached is not None:
        return cached
    html = tt.fetch("display-league-stats", stat_class=STAT_CLASS, league=LEAGUE,
                     season=season_id, level=level_id, conf=0)
    rows = tt.parse_league_player_stats(html)
    _save_json(path, rows)
    return rows


def scrape_team_season(team_id: int, season_id: int) -> dict | None:
    """Fetches one team's schedule/stats page for one season and, for every completed game on it,
    the shared box score. Returns None (and writes nothing) if that team_id didn't play that season."""
    team_page = fetch_team_season(team_id, season_id)
    if not team_page["games"]:
        return None
    _save_json(_season_dir(season_id) / f"schedule_{team_id}.json", team_page)
    for game in team_page["games"]:
        if game["is_final"] and game["has_boxscore"]:
            fetch_boxscore_cached(season_id, game["game_id"])
    return team_page


# ---------------------------------------------------------------------------
# Player spotlight: every roster player's career page + the cross-league context to grade it
# ---------------------------------------------------------------------------

def _league_dir(league_id: int, season_id: int) -> Path:
    d = LEAGUES_DIR / str(league_id) / str(season_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_current_season_id(league_id: int) -> tuple[int | None, str | None]:
    """(current season id, league label) for a league -- the site's 'Current' standings page never
    names its season id directly, but its team links do."""
    html = tt.fetch("display-stats", season=0, league=league_id, stat_class=STAT_CLASS)
    return tt.parse_current_season_id(html), tt.parse_league_label(html)


def fetch_league_standings_cached(league_id: int, season_id: int, refresh: bool = False) -> dict:
    """Standings for any (league, season): {league_label, rows}. Cached forever except for a league's
    current season (`refresh=True`), which changes as games are played and teams get added."""
    path = _league_dir(league_id, season_id) / "standings.json"
    cached = None if refresh else _load_json(path, None)
    if cached is not None:
        return cached
    html = tt.fetch("display-stats", season=season_id, league=league_id, stat_class=STAT_CLASS)
    data = {"league_label": tt.parse_league_label(html), "rows": tt.parse_standings(html)}
    _save_json(path, data)

    labels = _load_json(SEASON_LABELS_PATH, {})
    labels.update(tt.parse_season_options(html))  # season ids are global across leagues on this site
    _save_json(SEASON_LABELS_PATH, labels)
    return data


def fetch_league_level_players_cached(league_id: int, season_id: int, level_id: int, refresh: bool = False) -> list[dict]:
    """Every player in one division of one league-season -- the population a roster player's
    production is percentile-ranked against for the caliber grade."""
    path = _league_dir(league_id, season_id) / f"level_{level_id}_players.json"
    cached = None if refresh else _load_json(path, None)
    if cached is not None:
        return cached
    html = tt.fetch("display-league-stats", stat_class=STAT_CLASS, league=league_id,
                     season=season_id, level=level_id, conf=0)
    rows = tt.parse_league_player_stats(html)
    _save_json(path, rows)
    return rows


def spotlight_player_ids(our_team_ids: set[int], seasons_touched: set[int]) -> dict[int, str]:
    """Skater player_id -> name for everyone who has appeared in our division in any season we
    played: our own roster, every opponent's roster, and anyone who made a one-off appearance.
    Goalies are left out on purpose: the career page only carries skater columns, so there's
    nothing to grade them on."""
    out: dict[int, str] = {}
    for season_id in sorted(seasons_touched):
        standings = _load_json(_season_dir(season_id) / "standings.json", [])
        our_levels = {r["level_id"] for r in standings if r["team_id"] in our_team_ids}
        team_ids = {r["team_id"] for r in standings if r["level_id"] in our_levels} | our_team_ids
        for team_id in sorted(team_ids):
            page = _load_json(_season_dir(season_id) / f"schedule_{team_id}.json", None)
            if page is None:
                continue
            goalie_ids = {g["player_id"] for g in page["goalie_stats"]}
            for row in page["player_stats"]:
                pid = row.get("player_id")
                if pid is not None and pid not in goalie_ids:
                    out[pid] = row["name"]
    return out


def scrape_players(franchises: dict, our_team_ids: set[int], seasons_touched: set[int]) -> None:
    """Fetches the career page of every skater who has appeared in our division (fresh for anyone
    playing somewhere this season, cached otherwise), then makes sure the standings + division
    player tables exist for every (league, season) those careers touch, so the build step can pin
    each stint to a division and rank it.

    Which leagues count is configured per franchise (`player_lookup_leagues`); a stint in a league
    that isn't listed (tournaments, youth) still shows up on the spotlight, just without a grade.
    """
    leagues = sorted({int(l) for f in franchises.values() for l in f.get("player_lookup_leagues", {})})
    if not leagues:
        leagues = [LEAGUE]
    roster = spotlight_player_ids(our_team_ids, seasons_touched)

    # Resolve the current season of each lookup league first: its label never appears in any
    # dropdown (the site just says "Current"), so it has to be learned from the id the team links
    # carry, and its standings/player tables must be re-fetched every run rather than cached.
    current: dict[int, int | None] = {}
    active_now: set[int] = set()  # player ids rostered somewhere in a lookup league's current season
    for league_id in leagues:
        season_id, league_label = fetch_current_season_id(league_id)
        current[league_id] = season_id
        print(f"[players] league {league_id} ({league_label}) current season id = {season_id}")
        if season_id is None:
            continue
        standings = fetch_league_standings_cached(league_id, season_id, refresh=True)
        for level_id in sorted({r["level_id"] for r in standings["rows"] if r["level_id"] is not None}):
            for row in fetch_league_level_players_cached(league_id, season_id, level_id, refresh=True):
                if row.get("player_id") is not None:
                    active_now.add(row["player_id"])

    # Career pages: a few hundred players once you include every opponent, so only re-fetch the
    # ones whose career can actually have changed -- anyone rostered this season in a league we
    # grade. Everyone else's page is cached from the first time we saw them.
    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    to_fetch = [pid for pid in sorted(roster) if pid in active_now or not (PLAYERS_DIR / f"{pid}.json").exists()]
    print(f"[players] {len(roster)} spotlight players; fetching {len(to_fetch)} career pages "
          f"({len(active_now & set(roster))} active this season, rest uncached)")
    labels_seen: set[str] = set()
    for pid, name in sorted(roster.items()):
        path = PLAYERS_DIR / f"{pid}.json"
        if pid in to_fetch:
            html = tt.fetch("display-player-stats.php", player=pid)  # unlike the other pages, the bare path 404s here
            page = tt.parse_player_page(html)
            page["player_id"] = pid
            page["roster_name"] = name
            _save_json(path, page)
        else:
            page = _load_json(path, {})
        labels_seen.update(row["season_label"] for row in page.get("summary", []))

    label_to_id = {label: int(sid) for sid, label in _load_json(SEASON_LABELS_PATH, {}).items()}
    # Known season ids: everything any dropdown ever listed, plus the current ones. A career label we
    # can't place (a tournament, a season older than every dropdown) is simply left ungraded.
    season_ids = sorted({*label_to_id.values(), *(s for s in current.values() if s is not None)})
    unresolved = sorted(l for l in labels_seen if l not in label_to_id)
    print(f"[players] {len(unresolved)} career season labels not in the dropdown map: {unresolved}")

    for league_id in leagues:
        for season_id in season_ids:
            is_current = season_id == current[league_id]
            standings = fetch_league_standings_cached(league_id, season_id, refresh=is_current)
            level_ids = sorted({r["level_id"] for r in standings["rows"] if r["level_id"] is not None})
            for level_id in level_ids:
                fetch_league_level_players_cached(league_id, season_id, level_id, refresh=is_current)

    # Learn the label for each league's current season from the roster's career pages: the career
    # page names the season, the standings page names the teams, and a team appearing in both pins
    # the label to the id for good (persisted, so the build step can resolve it like any other).
    labels = _load_json(SEASON_LABELS_PATH, {})
    for league_id in leagues:
        season_id = current[league_id]
        if season_id is None or str(season_id) in labels:
            continue
        team_names = {r["name"] for r in fetch_league_standings_cached(league_id, season_id)["rows"]}
        learned = None
        for pid in roster:
            page = _load_json(PLAYERS_DIR / f"{pid}.json", {})
            for row in page.get("summary", []):
                if row["team"] in team_names and row["season_label"] not in label_to_id:
                    learned = row["season_label"]
                    break
            if learned:
                break
        if learned:
            labels[str(season_id)] = learned
            print(f"[players] learned season {season_id} = {learned!r} (league {league_id})")
    _save_json(SEASON_LABELS_PATH, labels)


def scrape_youtube(franchises: dict) -> None:
    """Fetches every video in the team's game-film playlist, caching each video's description by id
    (descriptions don't change once posted) and re-fetching the playlist listing itself every run so
    newly-added videos are picked up."""
    playlist_id = next((f.get("youtube_playlist_id") for f in franchises.values() if f.get("youtube_playlist_id")), None)
    if not playlist_id:
        return

    YOUTUBE_DIR.mkdir(parents=True, exist_ok=True)
    videos = yt.fetch_playlist_videos(playlist_id)
    print(f"[youtube] playlist has {len(videos)} videos")

    out = []
    for v in videos:
        cache_path = YOUTUBE_DIR / f"{v['video_id']}.json"
        cached = _load_json(cache_path, None)
        # A fresh upload can serve an empty description while YouTube is still processing it;
        # caching that would pin the video to game_id null forever, so only cache once we got text.
        if cached is None or (not cached.get("description") and cached.get("game_id") is None):
            description = yt.fetch_video_description(v["video_id"])
            cached = {**v, "description": description, "game_id": yt.extract_game_id(description)}
            if description:
                _save_json(cache_path, cached)
        out.append({
            "video_id": cached["video_id"], "title": cached["title"], "game_id": cached.get("game_id"),
            "url": f"https://www.youtube.com/watch?v={cached['video_id']}",
        })

    _save_json(YOUTUBE_VIDEOS_PATH, out)
    matched = sum(1 for v in out if v["game_id"] is not None)
    print(f"[youtube] {matched}/{len(out)} videos matched to a game_id")


def scrape_rink_events() -> None:
    """Public adult-hockey rink events (stick & puck, drop-ins, ...) for the calendar overlay -- a
    fresh rolling window every run since these are schedule-like data that changes day to day, not
    something worth caching per-item like a completed box score."""
    calendars = load_rink_calendars()
    if not calendars:
        return

    today = date.today()
    start = today.isoformat()
    end = (today + timedelta(days=RINK_EVENTS_WINDOW_DAYS)).isoformat()

    all_events = []
    for cal in calendars:
        print(f"[rink] fetching {cal['label']} events {start}..{end}")
        events = ds.fetch_events(cal["company"], cal["sport_id"], start, end, cal.get("facility_id"))
        for e in events:
            e["_calendar_label"] = cal["label"]
            e["_company"] = cal["company"]
            e["_sport_id"] = cal["sport_id"]
            e["_facility_id"] = cal.get("facility_id")
        print(f"  {len(events)} events")
        all_events.extend(events)

    _save_json(RINK_EVENTS_PATH, all_events)


def scrape() -> None:
    franchises = load_franchises()
    if not franchises:
        raise SystemExit(f"No franchises configured in {FRANCHISES_PATH}")

    upper = max_known_season(franchises) + SEASON_PROBE_BUFFER
    seasons_touched: set[int] = set()
    our_team_ids: set[int] = set()

    for franchise_id, franchise in franchises.items():
        for team_id_str in franchise["team_ids"]:
            team_id = int(team_id_str)
            our_team_ids.add(team_id)
            print(f"[{franchise_id}] probing team {team_id} across seasons 1..{upper}")
            for season_id in range(1, upper + 1):  # season=0 is the site's own alias for "current", not a real id
                team_page = scrape_team_season(team_id, season_id)
                if team_page is None:
                    continue  # this team_id didn't exist / didn't play in this season
                seasons_touched.add(season_id)
                print(f"  season {season_id}: {len(team_page['games'])} games, "
                      f"{len(team_page['player_stats'])} skaters")

    for season_id in sorted(seasons_touched):
        print(f"fetching standings for season {season_id}")
        standings = fetch_standings_cached(season_id)

        our_level_ids = {row["level_id"] for row in standings if row["team_id"] in our_team_ids}
        for level_id in our_level_ids:
            if level_id is None:
                continue
            print(f"  fetching league-wide player stats: season {season_id} level {level_id}")
            fetch_league_stats_cached(season_id, level_id)

            division_team_ids = sorted({row["team_id"] for row in standings if row["level_id"] == level_id})
            print(f"  scraping {len(division_team_ids)} division teams for season {season_id}: {division_team_ids}")
            for team_id in division_team_ids:
                scrape_team_season(team_id, season_id)

    scrape_players(franchises, our_team_ids, seasons_touched)
    scrape_youtube(franchises)
    scrape_rink_events()

    print(f"done. seasons touched: {sorted(seasons_touched)}")


if __name__ == "__main__":
    scrape()
