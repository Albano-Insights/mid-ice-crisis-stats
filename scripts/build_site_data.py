"""Builds data/derived/** (everything the dashboard fetches) from data/raw/** + data/corrections/**.

Run after scripts/scrape.py. Safe to re-run any time -- it only reads raw/corrections and rewrites
derived output, never touching raw scraped data.

Usage: python scripts/build_site_data.py
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import sys
sys.path.insert(0, str(Path(__file__).parent))
from lib import analytics, corrections as corr, spotlight as sp

TREND_WINDOW = 10  # trailing games used for sparklines + the half-split momentum score
MIN_GAMES_FOR_TREND = 3

ROOT = Path(__file__).parent.parent
DATA_RAW = ROOT / "data" / "raw"
CORRECTIONS_DIR = ROOT / "data" / "corrections"
DERIVED = ROOT / "data" / "derived"
FRANCHISES_PATH = ROOT / "data" / "franchises.json"
SEASON_LABELS_PATH = ROOT / "data" / "raw" / "season_labels.json"
YOUTUBE_VIDEOS_PATH = ROOT / "data" / "raw" / "youtube_videos.json"
RINK_EVENTS_RAW_PATH = ROOT / "data" / "raw" / "rink_events.json"
PLAYERS_RAW_DIR = ROOT / "data" / "raw" / "players"
POSITIONS_PATH = ROOT / "data" / "positions.json"
ON_ICE_DIR = ROOT / "data" / "on_ice"
LEAGUES_RAW_DIR = ROOT / "data" / "raw" / "leagues"

_DAY_ABBR = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday",
             "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}


def _load_json(path: Path, default=None):
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
    'rink_calendars', that aren't shaped like a franchise."""
    data = _load_json(FRANCHISES_PATH, {})
    return {k: v for k, v in data.items() if k != "rink_calendars"}


def load_game_videos() -> dict[int, dict]:
    """game_id -> {video_id, title, url} for every scraped YouTube video whose description names a
    game_id. Multiple videos could in principle name the same game_id (a re-upload); last one wins,
    which is fine at this scale."""
    videos = _load_json(YOUTUBE_VIDEOS_PATH, [])
    return {v["game_id"]: {"video_id": v["video_id"], "title": v["title"], "url": v["url"]}
            for v in videos if v.get("game_id") is not None}


def season_label(season_id: int) -> str:
    labels = _load_json(SEASON_LABELS_PATH, {})
    return labels.get(str(season_id), f"Season {season_id}")


def discover_seasons() -> list[int]:
    if not (DATA_RAW / "seasons").exists():
        return []
    return sorted(int(p.name) for p in (DATA_RAW / "seasons").iterdir() if p.name.isdigit())


_MONTH_NUM = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
              "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _season_base_year(season_id: int) -> int:
    """The site's season labels ('WM Fall 2025', 'WSpring 2026', ...) carry a real year -- when a
    season has no label yet (brand new, still just 'Season N'), fall back to the current real year,
    since a season with no label is by definition the one starting now."""
    m = re.search(r"(\d{4})", season_label(season_id))
    return int(m.group(1)) if m else datetime.now().year


def assign_iso_dates(games: list[dict], season_id: int) -> None:
    """Mutates each game dict in place, adding 'iso_date'. Does NOT trust the games to already be in
    chronological order -- game_id on this site is assigned at scheduling time, not game time, so it
    is very much NOT reliably chronological within a season (a game created later can easily have a
    lower id than one created earlier but played first). The site's dates never carry a year either
    ("Thu Sep 17"), so both problems are solved together here from the (month, day) values alone:
      1. Detect whether this season crosses a calendar-year boundary at all (spread between its
         earliest and latest month > 6 -- a real season never spans more than ~7 months, so a spread
         that large only happens when Jan/Feb/etc. dates actually belong to the *following* year).
      2. If it does, shift the "early" months (< July) into a 13-24 range purely for sorting/year-
         assignment purposes, so Sep..Dec sorts before Jan..Jun as it should.
      3. The season's label year is the base; shifted (i.e. actually-next-year) months get base+1.
    """
    if not games:
        return
    parsed = []
    for g in games:
        parts = g["date"].split()
        month, day = _MONTH_NUM[parts[1][:3]], int(parts[2])
        parsed.append((g, month, day))

    months_present = {m for _, m, _ in parsed}
    crosses_new_year = (max(months_present) - min(months_present)) > 6
    base_year = _season_base_year(season_id)

    def sort_key(item):
        _, month, day = item
        adj_month = month if (not crosses_new_year or month >= 7) else month + 12
        return (adj_month, day)

    for g, month, day in sorted(parsed, key=sort_key):
        year = base_year if (not crosses_new_year or month >= 7) else base_year + 1
        g["iso_date"] = f"{year:04d}-{month:02d}-{day:02d}"


class SeasonData:
    """Everything scraped for one season: every division team's schedule/stats + standings.

    `division_team_pages` covers every team in our division that season (the scraper pulls all of
    them, not just ours) -- `our_team_pages` is just the subset that belongs to one of our own
    franchises, kept around because several views (team summary, head-to-head, schedule heatmap) are
    intentionally scoped to "us", not the whole division.
    """

    def __init__(self, season_id: int, franchises: dict):
        self.season_id = season_id
        self.dir = DATA_RAW / "seasons" / str(season_id)
        self.standings = _load_json(self.dir / "standings.json", [])
        self.team_name_by_id: dict[int, str] = {r["team_id"]: r["name"] for r in self.standings}

        our_ids = {int(tid) for f in franchises.values() for tid in f["team_ids"]}

        self.division_team_pages: dict[int, dict] = {}
        self.name_to_player_id: dict[int, dict[str, int]] = {}
        self.pid_to_name: dict[int, dict[int, str]] = {}
        for row in self.standings:
            team_id = row["team_id"]
            page = _load_json(self.dir / f"schedule_{team_id}.json")
            if page is None:
                continue
            assign_iso_dates(page["games"], season_id)
            self.division_team_pages[team_id] = page
            name_map = {}
            for prow in page["player_stats"] + page["goalie_stats"]:
                if prow.get("player_id") is not None:
                    name_map[prow["name"]] = prow["player_id"]
            self.name_to_player_id[team_id] = name_map
            self.pid_to_name[team_id] = {pid: name for name, pid in name_map.items()}

        self.our_team_pages = {tid: p for tid, p in self.division_team_pages.items() if tid in our_ids}
        self.our_team_name = {tid: self.team_name_by_id.get(tid) for tid in self.our_team_pages}

    def load_corrected_boxscore(self, game_id: int) -> dict | None:
        box = _load_json(self.dir / f"boxscore_{game_id}.json")
        if box is None:
            return None
        return corr.apply_corrections(box, corr.load_corrections(CORRECTIONS_DIR, game_id))


def _team_side(box: dict, team_name: str, name_map: dict[str, int]) -> str:
    if box["home_name"] == team_name:
        return "home"
    if box["away_name"] == team_name:
        return "away"
    # fall back to whichever side's roster contains this team's known player names
    home_roster_names = {p["name"] for p in box["rosters"].get(box["home_name"], [])}
    return "home" if set(name_map) & home_roster_names else "away"


def _bump(per_player: dict, pid: int | None, field: str, amt: int = 1) -> None:
    if pid is None:
        return
    per_player.setdefault(pid, {"goals": 0, "primary_assists": 0, "secondary_assists": 0, "pims": 0})
    per_player[pid][field] += amt


def build_team_game_log(season: SeasonData, team_id: int) -> tuple[dict[int, list[dict]], list[dict]]:
    """Returns (player_id -> chronological per-game stat dicts, team-level chronological results)
    for one team's games in one season, corrections already applied. Every player on a game's roster
    gets an entry for that game (zeros if they didn't record anything), so a trend series doesn't
    silently skip a quiet night."""
    page = season.division_team_pages.get(team_id)
    if page is None:
        return {}, []
    name_map = season.name_to_player_id.get(team_id, {})
    team_name = season.team_name_by_id.get(team_id)

    player_logs: dict[int, list[dict]] = defaultdict(list)
    team_log: list[dict] = []
    cume_diff = 0
    cume_wl = 0

    final_games = sorted([g for g in page["games"] if g["is_final"]], key=lambda g: (g["iso_date"], g["game_id"]))
    for game in final_games:
        is_home = game["home_name"] == team_name
        gf, ga = (game["home_goals"], game["away_goals"]) if is_home else (game["away_goals"], game["home_goals"])
        result = "W" if gf > ga else ("L" if gf < ga else "T")
        cume_diff += gf - ga
        cume_wl += 1 if result == "W" else (-1 if result == "L" else 0)
        team_log.append({
            "game_id": game["game_id"], "date": game["date"], "iso_date": game["iso_date"],
            "gf": gf, "ga": ga, "result": result, "cume_diff": cume_diff, "cume_wl": cume_wl,
        })

        if not game["has_boxscore"]:
            continue
        box = season.load_corrected_boxscore(game["game_id"])
        if box is None:
            continue
        side = _team_side(box, team_name, name_map)
        side_name = box["home_name"] if side == "home" else box["away_name"]
        # Some roster entries (often a backup goalie) have no jersey number recorded at all, i.e.
        # number is None -- excluding them here is essential, not just tidy: goals/assists with no
        # scorer or no secondary assist are ALSO encoded as None in the source data, and
        # dict.get(None) would otherwise silently match that same None key and credit a phantom
        # goal/assist to whichever player happens to be missing a number.
        roster_by_number = {p["number"]: p["name"] for p in box["rosters"].get(side_name, []) if p["number"] is not None}

        per_player: dict[int, dict] = {}
        for pname in roster_by_number.values():
            pid = name_map.get(pname)
            if pid is not None:
                per_player.setdefault(pid, {"goals": 0, "primary_assists": 0, "secondary_assists": 0, "pims": 0})

        for goal in box["goals"]:
            if goal["team"] != side:
                continue
            if goal["scorer_number"] is not None:
                _bump(per_player, name_map.get(roster_by_number.get(goal["scorer_number"])), "goals")
            if goal["assist1_number"] is not None:
                _bump(per_player, name_map.get(roster_by_number.get(goal["assist1_number"])), "primary_assists")
            if goal["assist2_number"] is not None:
                _bump(per_player, name_map.get(roster_by_number.get(goal["assist2_number"])), "secondary_assists")

        for pen in box["penalties"].get(side, []):
            if pen.get("minutes") and pen.get("number") is not None:
                _bump(per_player, name_map.get(roster_by_number.get(pen["number"])), "pims", pen["minutes"])

        for pid, stats in per_player.items():
            points = stats["goals"] + stats["primary_assists"] + stats["secondary_assists"]
            player_logs[pid].append({
                "game_id": game["game_id"], "date": game["date"], "iso_date": game["iso_date"],
                "goals": stats["goals"], "primary_assists": stats["primary_assists"],
                "secondary_assists": stats["secondary_assists"], "points": points, "pims": stats["pims"],
            })

    return dict(player_logs), team_log


def trend_block(values: list[float], secondary: list[float] | None = None) -> dict:
    """Builds the {sparkline, spark_svg, momentum} block used everywhere in the dashboard, from a
    chronological numeric series (design template section 4: half-split trend + momentum score +
    Python-rendered sparkline, all precomputed here so the client does zero aggregation).
    `secondary` (e.g. goals, when `values` is points) feeds the momentum score's lower-weight term;
    defaults to `values` itself when not given.
    """
    window = values[-TREND_WINDOW:]
    if len(window) < MIN_GAMES_FOR_TREND:
        momentum = {"direction": "steady", "value": 0.0, "label": "not enough games yet"}
    else:
        secondary_window = (secondary or values)[-TREND_WINDOW:]
        momentum = analytics.trend_label(analytics.momentum_score(window, secondary_window))
    return {"sparkline": window, "spark_svg": analytics.line_spark_svg(window), "momentum": momentum}


def trend_from_log(games: list[dict], key: str = "points", secondary_key: str | None = "goals") -> dict:
    """Same as trend_block, but pulled from a chronological per-game log of dicts."""
    secondary = [g[secondary_key] for g in games] if secondary_key else None
    return trend_block([g[key] for g in games], secondary)


def collect_division_logs(season: SeasonData) -> dict:
    """One season's per-player game logs across every division team (not just ours), plus each
    team's own chronological results. Shared by our-team leaderboards, division-wide leaderboards,
    league outliers, and insights, so the (cheap, disk-only) box-score walk only happens once."""
    player_logs: dict[int, list[dict]] = defaultdict(list)
    names: dict[int, str] = {}
    teams_by_pid: dict[int, str] = {}
    team_logs: dict[int, list[dict]] = {}
    reported_extra: dict[int, dict] = {}  # player_id -> {shots, plus_minus} as last reported by the site

    for team_id, page in season.division_team_pages.items():
        player_log, team_log = build_team_game_log(season, team_id)
        pid_to_name = season.pid_to_name.get(team_id, {})
        team_name = season.team_name_by_id.get(team_id)
        team_logs[team_id] = team_log
        for pid, entries in player_log.items():
            player_logs[pid].extend(entries)
            names[pid] = pid_to_name.get(pid, names.get(pid))
            teams_by_pid[pid] = team_name
        for row in page["player_stats"]:
            if row.get("player_id") is not None:
                reported_extra[row["player_id"]] = {"shots": row.get("shots"), "plus_minus": row.get("plus_minus")}

    return {
        "player_logs": dict(player_logs), "names": names, "teams_by_pid": teams_by_pid,
        "team_logs": team_logs, "reported_extra": reported_extra,
    }


def _finalize_leaderboard(logs: dict[int, list[dict]], names: dict[int, str],
                           reported_extra: dict[int, dict], plus_minus: dict[int, dict] | None = None) -> list[dict]:
    out = []
    for pid, entries in logs.items():
        entries = sorted(entries, key=lambda e: (e["iso_date"], e["game_id"]))
        games = len(entries)
        goals = sum(e["goals"] for e in entries)
        pa = sum(e["primary_assists"] for e in entries)
        sa = sum(e["secondary_assists"] for e in entries)
        pims = sum(e["pims"] for e in entries)
        hat_tricks = sum(1 for e in entries if e["goals"] >= 3)
        points = goals + pa + sa
        extra = reported_extra.get(pid, {})
        out.append({
            "player_id": pid, "name": names.get(pid), "games_played": games,
            "goals": goals, "primary_assists": pa, "secondary_assists": sa,
            "assists": pa + sa, "points": points,
            "points_per_game": round(points / games, 2) if games else 0,
            "pims": pims, "hat_tricks": hat_tricks,
            "shots_as_reported": extra.get("shots"), "plus_minus_as_reported": extra.get("plus_minus"),
            "plus_minus_tagged": (plus_minus or {}).get(pid),
            **trend_from_log(entries, "points", "goals"),
        })
    # Momentum (not raw points) is the default sort everywhere, per the design template -- it surfaces
    # "who's heating up that you weren't watching" instead of just restating the standings.
    out.sort(key=lambda r: r["momentum"]["value"], reverse=True)
    return out


def build_leaderboards(seasons: list[SeasonData], division_logs: dict[int, dict]) -> tuple[dict, dict]:
    """Returns (our_team_leaderboards, division_wide_leaderboards_by_season)."""
    our_career_logs: dict[int, list[dict]] = defaultdict(list)
    our_career_names: dict[int, str] = {}
    our_career_extra: dict[int, dict] = {}
    our_by_season: dict[int, list[dict]] = {}
    division_by_season: dict[int, list[dict]] = {}
    pm = build_plus_minus(seasons)["players"]

    for season in seasons:
        dl = division_logs[season.season_id]
        our_team_names = {season.team_name_by_id.get(tid) for tid in season.our_team_pages}
        our_pids = {pid for pid, team in dl["teams_by_pid"].items() if team in our_team_names}

        our_logs_this_season = {pid: dl["player_logs"][pid] for pid in our_pids}
        our_by_season[season.season_id] = _finalize_leaderboard(our_logs_this_season, dl["names"], dl["reported_extra"], pm)

        for pid in our_pids:
            our_career_logs[pid].extend(dl["player_logs"][pid])
            our_career_names[pid] = dl["names"][pid]
        our_career_extra.update(dl["reported_extra"])

        division_rows = _finalize_leaderboard(dl["player_logs"], dl["names"], dl["reported_extra"], pm)
        for row in division_rows:
            row["team"] = dl["teams_by_pid"].get(row["player_id"])
        division_by_season[season.season_id] = division_rows

    our_leaderboards = {
        "career": _finalize_leaderboard(our_career_logs, our_career_names, our_career_extra, pm),
        "by_season": our_by_season,
    }
    return our_leaderboards, division_by_season


def build_team_pace(seasons: list[SeasonData], division_logs: dict[int, dict]) -> dict:
    """Per season, every division team's chronological cumulative goal-diff / win-loss pace --
    powers an 'our pace vs. the division' comparison chart."""
    out = {}
    for season in seasons:
        dl = division_logs[season.season_id]
        teams = []
        for team_id, team_log in dl["team_logs"].items():
            teams.append({
                "team_id": team_id, "name": season.team_name_by_id.get(team_id),
                "is_us": team_id in season.our_team_pages, "games": team_log,
            })
        out[season.season_id] = teams
    return out


def build_standings(seasons: list[SeasonData], team_pace: dict, ctx: "LeagueContext", franchises: dict) -> dict:
    """Our division's table for every season we played, straight from the league's standings
    (the official ledger), plus each team's last five results from the box-score walk. The
    players scrape keeps a fuller copy of the standings under data/raw/leagues/<league>/<season>/
    than the team-page scrape does (which can be a pre-season stub), so prefer that one."""
    our_league = next((int(f["league"]) for f in franchises.values() if f.get("league")), 4)
    out = {}
    for season in seasons:
        our_ids = set(season.our_team_pages)
        rows = ctx.standings.get((our_league, season.season_id)) or season.standings
        our_row = next((r for r in rows if r["team_id"] in our_ids), None)
        if not our_row or our_row.get("level_id") is None:
            continue
        pace = {t["name"]: t["games"] for t in team_pace.get(season.season_id, [])}
        table = []
        for r in rows:
            if r["level_id"] != our_row["level_id"]:
                continue
            last5 = [g["result"] for g in (pace.get(r["name"]) or [])[-5:]]
            table.append({**r, "is_us": r["team_id"] in our_ids, "last5": last5,
                          "diff": (r["gf"] or 0) - (r["ga"] or 0) if r.get("gf") is not None else None})
        # League order: points, then wins, then goal diff -- the site's own tie-break, as far as we can tell.
        table.sort(key=lambda r: (-(r["pts"] or 0), -(r["w"] or 0), -(r["diff"] or 0), r["name"]))
        out[season.season_id] = {"season_label": season_label(season.season_id),
                                 "level_label": our_row["level_label"], "rows": table}
    return out


def build_team_summary(seasons: list[SeasonData], franchises: dict) -> dict:
    by_season = {}
    all_games_chrono = []

    for season in seasons:
        for team_id, page in season.our_team_pages.items():
            standing = next((r for r in season.standings if r["team_id"] == team_id), None)
            by_season[season.season_id] = {
                "team_id": team_id,
                "name": season.our_team_name.get(team_id),
                "season_label": season_label(season.season_id),
                "level_label": standing["level_label"] if standing else None,
                "gp": standing["gp"] if standing else None,
                "w": standing["w"] if standing else None,
                "l": standing["l"] if standing else None,
                "t": standing["t"] if standing else None,
                "otw": standing["otw"] if standing else None,
                "otl": standing["otl"] if standing else None,
                "gf": standing["gf"] if standing else None,
                "ga": standing["ga"] if standing else None,
                "pts": standing["pts"] if standing else None,
                "pims": standing["pims"] if standing else None,
            }
            for g in page["games"]:
                if g["is_final"]:
                    all_games_chrono.append({**g, "season_id": season.season_id, "our_team_id": team_id})

    all_games_chrono.sort(key=lambda g: (g["iso_date"], g["game_id"]))

    season_by_id = {s.season_id: s for s in seasons}
    results = []
    diff_series = []
    form_series = []  # 2/1/0 per game (win/tie/loss), for a simple "points pace" trend
    for g in all_games_chrono:
        season = season_by_id[g["season_id"]]
        our_name = season.our_team_name.get(g["our_team_id"])
        if g["home_name"] == our_name:
            us, them = g["home_goals"], g["away_goals"]
        else:
            us, them = g["away_goals"], g["home_goals"]
        if us > them:
            results.append("W")
            form_series.append(2)
        elif us < them:
            results.append("L")
            form_series.append(0)
        else:
            results.append("T")
            form_series.append(1)
        diff_series.append(us - them)

    current_streak = {"result": None, "length": 0}
    if results:
        last = results[-1]
        n = 0
        for r in reversed(results):
            if r != last:
                break
            n += 1
        current_streak = {"result": last, "length": n}

    recent_form = {"goal_diff": trend_block(diff_series), "points_pace": trend_block(form_series)}

    overall = {
        "gp": sum(v["gp"] or 0 for v in by_season.values()),
        "w": sum(v["w"] or 0 for v in by_season.values()),
        "l": sum(v["l"] or 0 for v in by_season.values()),
        "t": sum(v["t"] or 0 for v in by_season.values()),
        "otw": sum(v["otw"] or 0 for v in by_season.values()),
        "otl": sum(v["otl"] or 0 for v in by_season.values()),
        "gf": sum(v["gf"] or 0 for v in by_season.values()),
        "ga": sum(v["ga"] or 0 for v in by_season.values()),
        "pts": sum(v["pts"] or 0 for v in by_season.values()),
        "pims": sum(v["pims"] or 0 for v in by_season.values()),
    }

    return {"overall": overall, "current_streak": current_streak, "recent_form": recent_form, "by_season": by_season}


def build_head_to_head(seasons: list[SeasonData]) -> dict:
    opponents = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "gf": 0, "ga": 0, "meetings": []})

    for season in seasons:
        for team_id, page in season.our_team_pages.items():
            our_name = season.our_team_name.get(team_id)
            for g in page["games"]:
                if not g["is_final"]:
                    continue
                is_home = g["home_name"] == our_name
                opp_name = g["away_name"] if is_home else g["home_name"]
                us, them = (g["home_goals"], g["away_goals"]) if is_home else (g["away_goals"], g["home_goals"])
                row = opponents[opp_name]
                if us > them:
                    row["w"] += 1
                elif us < them:
                    row["l"] += 1
                else:
                    row["t"] += 1
                row["gf"] += us
                row["ga"] += them
                row["meetings"].append({
                    "game_id": g["game_id"], "season_id": season.season_id,
                    "season_label": season_label(season.season_id), "date": g["date"], "iso_date": g["iso_date"],
                    "us": us, "them": them, "game_type": g["game_type"],
                })

    for row in opponents.values():
        row["meetings"].sort(key=lambda m: (m["iso_date"], m["game_id"]))

    return dict(opponents)


def build_schedule_heatmap(seasons: list[SeasonData]) -> dict:
    by_day = defaultdict(int)
    by_hour = defaultdict(int)
    by_rink = defaultdict(int)

    for season in seasons:
        for team_id, page in season.our_team_pages.items():
            for g in page["games"]:
                day_abbr = g["date"].split(" ")[0] if g["date"] else None
                by_day[_DAY_ABBR.get(day_abbr, day_abbr)] += 1
                time = g["time"]
                if time:
                    hour_str, meridiem = time.split(" ")[0], time.split(" ")[-1]
                    hour = int(hour_str.split(":")[0]) % 12
                    if meridiem == "PM":
                        hour += 12
                    by_hour[f"{hour:02d}:00"] += 1
                by_rink[g["rink"]] += 1

    return {"by_day_of_week": dict(by_day), "by_hour": dict(sorted(by_hour.items())), "by_rink": dict(by_rink)}


def build_league_outliers(seasons: list[SeasonData], division_leaderboards: dict) -> dict:
    """Division-wide leader boards, built from the same corrected, trend-aware rows as everything
    else (richer than the site's own coarse `display-league-stats` table, which we still scrape as a
    raw cross-check but no longer use directly here)."""
    out = {}
    for season in seasons:
        rows = division_leaderboards.get(season.season_id, [])
        if not rows:
            continue
        our_ids = set(season.our_team_pages)
        our_row = next((r for r in season.standings if r["team_id"] in our_ids), None)

        def top(key, n=5):
            return sorted([r for r in rows if r.get(key) is not None], key=lambda r: r[key], reverse=True)[:n]

        out[season.season_id] = {
            "level_id": our_row["level_id"] if our_row else None,
            "level_label": our_row["level_label"] if our_row else None,
            "season_label": season_label(season.season_id),
            "leaders": {
                "goals": top("goals"),
                "assists": top("assists"),
                "points": top("points"),
                "pims": top("pims"),
            },
        }
    return out


_MIN_GAMES_FOR_INSIGHT = 5


def build_league_insights(seasons: list[SeasonData], division_logs: dict[int, dict],
                           division_leaderboards: dict, team_pace: dict) -> dict:
    """Generated 'quick insight' callouts per season: hottest/coldest player, scoring-leader margin,
    best goal differential, longest active win streak, and PIM leader across the whole division."""
    out = {}
    for season in seasons:
        rows = division_leaderboards.get(season.season_id, [])
        teams = team_pace.get(season.season_id, [])
        insights = []
        eligible = [r for r in rows if r["games_played"] >= _MIN_GAMES_FOR_INSIGHT]

        hot = [r for r in eligible if r["momentum"]["direction"] == "hot"]
        if hot:
            top_hot = max(hot, key=lambda r: r["momentum"]["value"])
            insights.append({
                "kind": "hot_streak",
                "headline": f"{top_hot['name']} ({top_hot['team']}) is heating up",
                "detail": f"Momentum {top_hot['momentum']['label']} over their last "
                          f"{len(top_hot['sparkline'])} games.",
            })

        cold = [r for r in eligible if r["momentum"]["direction"] == "cold" and r["points"] > 0]
        if cold:
            top_cold = min(cold, key=lambda r: r["momentum"]["value"])
            insights.append({
                "kind": "cold_streak",
                "headline": f"{top_cold['name']} ({top_cold['team']}) has cooled off",
                "detail": f"Momentum {top_cold['momentum']['label']} over their last "
                          f"{len(top_cold['sparkline'])} games.",
            })

        by_points = sorted(rows, key=lambda r: r["points"], reverse=True)
        if len(by_points) >= 2:
            lead, second = by_points[0], by_points[1]
            insights.append({
                "kind": "scoring_leader",
                "headline": f"{lead['name']} ({lead['team']}) leads the division in scoring",
                "detail": f"{lead['points']} points, {lead['points'] - second['points']} ahead of "
                          f"{second['name']} ({second['team']}).",
            })

        if teams:
            best_diff = max(teams, key=lambda t: t["games"][-1]["cume_diff"] if t["games"] else -999)
            if best_diff["games"]:
                insights.append({
                    "kind": "goal_diff",
                    "headline": f"{best_diff['name']} has the division's best goal differential",
                    "detail": f"{best_diff['games'][-1]['cume_diff']:+d} across "
                              f"{len(best_diff['games'])} games this season.",
                })

            def active_streak(games: list[dict]) -> tuple[str, int]:
                if not games:
                    return None, 0
                last = games[-1]["result"]
                n = 0
                for g in reversed(games):
                    if g["result"] != last:
                        break
                    n += 1
                return last, n

            streak_teams = [(t, *active_streak(t["games"])) for t in teams if t["games"]]
            win_streaks = [(t, n) for t, result, n in streak_teams if result == "W" and n >= 2]
            if win_streaks:
                team, n = max(win_streaks, key=lambda pair: pair[1])
                insights.append({
                    "kind": "win_streak",
                    "headline": f"{team['name']} is on a {n}-game win streak",
                    "detail": "Longest active winning streak in the division right now.",
                })

        pim_leaders = sorted([r for r in rows if r["pims"] > 0], key=lambda r: r["pims"], reverse=True)
        if pim_leaders:
            top_pim = pim_leaders[0]
            insights.append({
                "kind": "pim_leader",
                "headline": f"{top_pim['name']} ({top_pim['team']}) leads the division in PIM",
                "detail": f"{top_pim['pims']} penalty minutes so far -- frequent flyer of the box.",
            })

        our_names = {season.team_name_by_id.get(tid) for tid in season.our_team_pages}
        our_rows = [r for r in by_points if r["team"] in our_names]
        if our_rows:
            our_top = our_rows[0]
            rank = by_points.index(our_top) + 1
            if rank > 1:
                insights.append({
                    "kind": "our_rank",
                    "headline": f"Our leading scorer ranks #{rank} in the division",
                    "detail": f"{our_top['name']} has {our_top['points']} points "
                              f"({by_points[0]['points'] - our_top['points']} behind the division lead).",
                })

        out[season.season_id] = {"season_label": season_label(season.season_id), "insights": insights}
    return out


def build_scouting_report(seasons: list[SeasonData], division_leaderboards: dict,
                           team_pace: dict, head_to_head: dict) -> dict:
    """Opponent scouting report for our next unplayed game, generated entirely from already-scraped
    data with plain Python string templating -- no LLM call, so this costs nothing extra to refresh
    on every GitHub Actions run.
    """
    game_videos = load_game_videos()

    # Restrict to the latest season only, and require has_boxscore == False. A handful of already-played
    # games are missing a final score on the league site itself (a scoresheet exists, is_final is just
    # False/unset) -- has_boxscore reliably distinguishes those stray past games from real future ones,
    # which never have a scoresheet link yet.
    latest_season = max(seasons, key=lambda s: s.season_id)
    upcoming = []
    for team_id, page in latest_season.our_team_pages.items():
        our_name = latest_season.our_team_name.get(team_id)
        for g in page["games"]:
            if not g["is_final"] and not g["has_boxscore"]:
                upcoming.append({**g, "season": latest_season, "our_name": our_name})
    if not upcoming:
        return {"has_upcoming_game": False}

    game = min(upcoming, key=lambda g: (g["iso_date"], g["game_id"]))
    season = game["season"]
    is_home = game["home_name"] == game["our_name"]
    opp_name = game["away_name"] if is_home else game["home_name"]

    # Early in a new season there's often no current-season data for the opponent yet (or for us).
    # Fall back to the most recent earlier season where they have division-wide stats, so a week-1
    # scouting report isn't just a page of nulls -- and say which season it's actually reflecting.
    stats_season, opp_roster = None, []
    for candidate in sorted(seasons, key=lambda s: s.season_id, reverse=True):
        if candidate.season_id > season.season_id:
            continue
        rows = [r for r in division_leaderboards.get(candidate.season_id, []) if r["team"] == opp_name]
        if rows:
            stats_season, opp_roster = candidate, rows
            break

    opp_row = next((r for r in (stats_season.standings if stats_season else []) if r["name"] == opp_name), None)
    opp_team_id = opp_row["team_id"] if opp_row else None

    top_threats = sorted(opp_roster, key=lambda r: r["points"], reverse=True)[:5]
    pim_sorted = sorted([r for r in opp_roster if r["pims"] > 0], key=lambda r: r["pims"], reverse=True)
    pim_leader = pim_sorted[0] if pim_sorted else None

    opp_team_log = []
    if stats_season:
        opp_team_log = next((t["games"] for t in team_pace.get(stats_season.season_id, []) if t["name"] == opp_name), [])
    recent_form = [g["result"] for g in opp_team_log[-5:]]

    opp_goalies = []
    opp_page = stats_season.division_team_pages.get(opp_team_id) if stats_season and opp_team_id else None
    if opp_page:
        opp_goalies = [
            {"name": g["name"], "gp": g["gp"], "gaa": g.get("gaa"), "save_pct": g.get("save_pct"),
             "w": g.get("w"), "l": g.get("l")}
            for g in opp_page["goalie_stats"] if g.get("gp")
        ]
        opp_goalies.sort(key=lambda g: g["gp"] or 0, reverse=True)

    h2h = head_to_head.get(opp_name)
    past_films = []
    if h2h:
        for m in h2h["meetings"]:
            video = game_videos.get(m["game_id"])
            if video:
                past_films.append({**video, "date": m["date"], "season_label": m["season_label"],
                                    "us": m["us"], "them": m["them"]})

    stats_note = None
    if stats_season and stats_season.season_id != season.season_id:
        stats_note = f"No games played yet this season -- stats below are from {season_label(stats_season.season_id)}."

    keys_to_game = []
    if h2h:
        record = f"{h2h['w']}-{h2h['l']}" + (f"-{h2h['t']}" if h2h["t"] else "")
        keys_to_game.append(f"All-time we're {record} against {opp_name} "
                             f"({h2h['gf']}-{h2h['ga']} goals).")
    if len(recent_form) >= 2 and recent_form[-1] == recent_form[-2] and recent_form[-1] in ("W", "L"):
        streak_len = 0
        for r in reversed(recent_form):
            if r != recent_form[-1]:
                break
            streak_len += 1
        word = "won" if recent_form[-1] == "W" else "lost"
        keys_to_game.append(f"{opp_name} have {word} their last {streak_len} straight.")
    if top_threats and top_threats[0]["momentum"]["direction"] == "hot":
        t = top_threats[0]
        keys_to_game.append(f"Watch {t['name']} -- momentum {t['momentum']['label']}, "
                             f"their most dangerous player right now.")
    if pim_leader and pim_leader["pims"] >= 20:
        keys_to_game.append(f"{pim_leader['name']} leads them with {pim_leader['pims']} PIM -- "
                             f"expect some physical play.")
    if opp_goalies and opp_goalies[0].get("save_pct"):
        try:
            sv = float(opp_goalies[0]["save_pct"])
            if sv >= 0.910:
                keys_to_game.append(f"Their goalie {opp_goalies[0]['name']} is stopping "
                                     f"{sv*100:.1f}% of shots -- traffic and second chances matter more than usual.")
        except (TypeError, ValueError):
            pass
    if not keys_to_game:
        keys_to_game.append("Not enough recent data on this opponent yet -- check back closer to game day.")

    return {
        "has_upcoming_game": True,
        "generated_for_season": season.season_id,
        "season_label": season_label(season.season_id),
        "game": {
            "game_id": game["game_id"], "date": game["date"], "time": game["time"],
            "rink": game["rink"], "game_type": game["game_type"], "is_home": is_home,
        },
        "opponent": {"name": opp_name, "team_id": opp_team_id, "level_label": opp_row["level_label"] if opp_row else None},
        "stats_note": stats_note,
        "opponent_record": opp_row,
        "recent_form": recent_form,
        "head_to_head": h2h,
        "top_threats": top_threats,
        "pim_leader": pim_leader,
        "goalies": opp_goalies,
        "keys_to_game": keys_to_game,
        "past_films": past_films,
    }


# ---------------------------------------------------------------------------
# Player Spotlight (cross-league career + caliber grade) -- see lib/spotlight.py for the method
# ---------------------------------------------------------------------------

class LeagueContext:
    """Every configured lookup league's standings + division player tables, as scraped, indexed for
    the two questions the spotlight asks: 'what division was this team in that season?' and 'how did
    this P/GP rank among everyone in that division?'"""

    def __init__(self, franchises: dict):
        self.league_labels: dict[int, str] = {}
        for f in franchises.values():
            for lid, label in f.get("player_lookup_leagues", {}).items():
                self.league_labels[int(lid)] = label
        self.label_to_season = {label: int(sid) for sid, label in _load_json(SEASON_LABELS_PATH, {}).items()}
        # (league, season) -> [standings rows]; (league, season, level) -> [player rows]
        self.standings: dict[tuple[int, int], list[dict]] = {}
        self.populations: dict[tuple[int, int, int], list[dict]] = {}
        if not LEAGUES_RAW_DIR.exists():
            return
        for league_dir in LEAGUES_RAW_DIR.iterdir():
            if not league_dir.name.isdigit():
                continue
            league_id = int(league_dir.name)
            for season_dir in league_dir.iterdir():
                if not season_dir.name.isdigit():
                    continue
                season_id = int(season_dir.name)
                st = _load_json(season_dir / "standings.json", {})
                self.standings[(league_id, season_id)] = st.get("rows", [])
                self.league_labels.setdefault(league_id, st.get("league_label") or f"League {league_id}")
                for lp in season_dir.glob("level_*_players.json"):
                    level_id = int(lp.stem.split("_")[1])
                    self.populations[(league_id, season_id, level_id)] = _load_json(lp, [])

    def locate(self, team: str, season_label: str, opponents: set[str]) -> dict | None:
        """Pin a (team, season label) stint to {league_id, league_label, season_id, level_id,
        level_label}. When the same team name exists in more than one league that season, the one
        whose division actually contains the stint's opponents wins."""
        season_id = self.label_to_season.get(season_label)
        if season_id is None:
            return None
        candidates = []
        for (league_id, sid), rows in self.standings.items():
            if sid != season_id:
                continue
            for r in rows:
                if r["name"] == team and r["level_id"] is not None:
                    peers = {x["name"] for x in rows if x["level_id"] == r["level_id"]}
                    candidates.append((len(opponents & peers), league_id, r))
        if not candidates:
            return None
        _, league_id, row = max(candidates, key=lambda c: c[0])
        return {"league_id": league_id, "league_label": self.league_labels.get(league_id),
                "season_id": season_id, "level_id": row["level_id"], "level_label": row["level_label"]}

    def population(self, loc: dict) -> list[dict]:
        return self.populations.get((loc["league_id"], loc["season_id"], loc["level_id"]), [])


def build_plus_minus(seasons: list[SeasonData]) -> dict:
    """True +/- from hand-tagged on-ice lists (data/on_ice/<game_id>.json), NHL rules: even-strength
    and shorthanded goals count, power-play goals count for nobody. Returns
    {"players": {pid: {plus, minus, plus_minus, goals_tagged}}, "games": {game_id: {tagged, total}}}
    -- coverage matters as much as the number, so both are reported."""
    players: dict[int, dict] = {}
    games: dict[str, dict] = {}
    if not ON_ICE_DIR.exists():
        return {"players": players, "games": games}
    for path in ON_ICE_DIR.glob("*.json"):
        game_id = int(path.stem)
        tags = _load_json(path, {}).get("goals", [])
        season = next((s for s in seasons if any(g["game_id"] == game_id for p in s.division_team_pages.values() for g in p["games"])), None)
        if season is None:
            continue
        box = season.load_corrected_boxscore(game_id)
        if box is None:
            continue
        names = {"home": box["home_name"], "away": box["away_name"]}
        pid_by_side = {}
        for side, name in names.items():
            tid = next((t for t, n in season.team_name_by_id.items() if n == name), None)
            name_map = season.name_to_player_id.get(tid, {}) if tid else {}
            pid_by_side[side] = {p["number"]: name_map.get(p["name"]) for p in box["rosters"].get(name, []) if p["number"] is not None}
        by_key = {(t["team"], t["period"], t["time"]): t for t in tags}
        tagged = 0
        for goal in box["goals"]:
            tag = by_key.get((goal["team"], goal["period"], goal["time"]))
            if not tag:
                continue
            tagged += 1
            if "PP" in (goal.get("situation") or "").upper():
                continue  # power-play goals don't move +/-
            for side, numbers in tag.get("on_ice", {}).items():
                sign = 1 if side == goal["team"] else -1
                for num in numbers:
                    pid = pid_by_side.get(side, {}).get(num)
                    if pid is None:
                        continue
                    r = players.setdefault(pid, {"plus": 0, "minus": 0, "plus_minus": 0, "goals_tagged": 0})
                    r["plus" if sign > 0 else "minus"] += 1
                    r["plus_minus"] += sign
                    r["goals_tagged"] += 1
        games[str(game_id)] = {"tagged": tagged, "total": len(box["goals"])}
    return {"players": players, "games": games}


def build_wowy(seasons: list[SeasonData], division_logs: dict[int, dict]) -> dict[int, dict]:
    """player_id -> {with_diff, without_diff, with_gp, without_gp, swing} across every division
    season we have: the team's goal differential per game in games the player dressed vs. games the
    same team played without them. Game-grain only (no shift data), pooled across seasons so a
    regular gets a real 'without' sample eventually."""
    acc: dict[int, dict] = defaultdict(lambda: {"with": [], "without": []})
    for season in seasons:
        dl = division_logs[season.season_id]
        team_by_pid = dl["teams_by_pid"]
        team_id_by_name = {v: k for k, v in season.team_name_by_id.items()}
        dressed: dict[int, set[int]] = {pid: {e["game_id"] for e in entries} for pid, entries in dl["player_logs"].items()}
        for pid, games in dressed.items():
            team_id = team_id_by_name.get(team_by_pid.get(pid))
            team_log = dl["team_logs"].get(team_id, [])
            for g in team_log:
                (acc[pid]["with"] if g["game_id"] in games else acc[pid]["without"]).append(g["gf"] - g["ga"])
    out = {}
    for pid, a in acc.items():
        w, wo = a["with"], a["without"]
        with_diff = round(sum(w) / len(w), 2) if len(w) >= sp.WOWY_MIN_GAMES else None
        without_diff = round(sum(wo) / len(wo), 2) if len(wo) >= sp.WOWY_MIN_GAMES else None
        out[pid] = {"with_diff": with_diff, "without_diff": without_diff, "with_gp": len(w), "without_gp": len(wo),
                    "swing": round(with_diff - without_diff, 2) if with_diff is not None and without_diff is not None else None}
    return out


def build_vs_us(seasons: list[SeasonData], division_logs: dict[int, dict]) -> dict[int, dict]:
    """player_id -> how an OPPONENT has done against us specifically: their G/A/PTS/PIM in games
    vs. our team, and our record in those games. Ours are skipped (that'd be 'vs themselves')."""
    out: dict[int, dict] = {}
    for season in seasons:
        dl = division_logs[season.season_id]
        our_names = {season.team_name_by_id.get(tid) for tid in season.our_team_pages}
        our_results: dict[int, str] = {}
        for tid in season.our_team_pages:
            for g in dl["team_logs"].get(tid, []):
                our_results[g["game_id"]] = g["result"]
        for pid, entries in dl["player_logs"].items():
            if dl["teams_by_pid"].get(pid) in our_names:
                continue
            for e in entries:
                if e["game_id"] not in our_results:
                    continue
                r = out.setdefault(pid, {"gp": 0, "goals": 0, "assists": 0, "points": 0, "pims": 0,
                                         "our_w": 0, "our_l": 0, "our_t": 0, "last_date": None, "games": []})
                r["gp"] += 1
                r["goals"] += e["goals"]; r["assists"] += e["primary_assists"] + e["secondary_assists"]
                r["points"] += e["points"]; r["pims"] += e["pims"]
                res = our_results[e["game_id"]]
                r["our_w" if res == "W" else "our_l" if res == "L" else "our_t"] += 1
                r["games"].append({"game_id": e["game_id"], "date": e["iso_date"], "season_label": season_label(season.season_id),
                                   "goals": e["goals"], "assists": e["primary_assists"] + e["secondary_assists"],
                                   "points": e["points"], "our_result": res})
    for r in out.values():
        r["games"].sort(key=lambda g: (g["date"], g["game_id"]))
        r["last_date"] = r["games"][-1]["date"] if r["games"] else None
        r["points_per_game"] = round(r["points"] / r["gp"], 2) if r["gp"] else 0.0
    return out


_PERIOD_KEYS = ("1", "2", "3", "OT")


def _period_key(raw: str) -> str:
    raw = (raw or "").strip().upper()
    return raw if raw in ("1", "2", "3") else "OT"


def _clock_seconds(t: str) -> int | None:
    """'4:32' -> 272. The site's clock counts DOWN within a period."""
    try:
        m, s_ = t.strip().split(":")
        return int(m) * 60 + int(s_)
    except (ValueError, AttributeError):
        return None


def build_situational(seasons: list[SeasonData]) -> dict:
    """WHEN goals happen, for every division team and every skater, from the goal-by-goal box
    scores: GF/GA by period, PP/SH share, and 'late & close' -- third-period (or OT) goals while the
    game was within one. Returns {"teams": {season_id: {team: {...}}}, "players": {pid: {...}}}."""
    teams_out: dict[int, dict[str, dict]] = defaultdict(dict)
    players: dict[int, dict] = {}

    def team_bucket(sid: int, name: str) -> dict:
        return teams_out[sid].setdefault(name, {
            "games": 0, "gf_by_period": {k: 0 for k in _PERIOD_KEYS}, "ga_by_period": {k: 0 for k in _PERIOD_KEYS},
            "pp_gf": 0, "sh_gf": 0, "pp_ga": 0, "sh_ga": 0, "en_gf": 0,
            "late_close_gf": 0, "late_close_ga": 0, "late_close_games": 0, "late_close_w": 0, "late_close_l": 0,
            "first_goal_games": 0, "first_goal_w": 0,
        })

    def player_bucket(pid: int) -> dict:
        return players.setdefault(pid, {"points_by_period": {k: 0 for k in _PERIOD_KEYS}, "late_close_points": 0,
                                        "pp_points": 0, "game_winners": 0})

    for season in seasons:
        seen: set[int] = set()
        for team_id, page in season.division_team_pages.items():
            for g in page["games"]:
                if not (g["is_final"] and g["has_boxscore"]) or g["game_id"] in seen:
                    continue
                box = season.load_corrected_boxscore(g["game_id"])
                if box is None:
                    continue
                seen.add(g["game_id"])
                names = {"home": box["home_name"], "away": box["away_name"]}
                for side, name in names.items():
                    team_bucket(season.season_id, name)["games"] += 1
                # Roster lookups: number -> pid per side
                pid_by_side: dict[str, dict[int, int]] = {}
                for side, name in names.items():
                    tid = next((t for t, n in season.team_name_by_id.items() if n == name), None)
                    name_map = season.name_to_player_id.get(tid, {}) if tid else {}
                    pid_by_side[side] = {p["number"]: name_map.get(p["name"]) for p in box["rosters"].get(name, [])
                                         if p["number"] is not None}

                # Walk goals in order to know the score state at each one.
                goals = sorted(box["goals"], key=lambda x: (["1", "2", "3"].index(x["period"]) if x["period"] in ("1", "2", "3") else 3,
                                                            -(_clock_seconds(x["time"]) or 0)))
                score = {"home": 0, "away": 0}
                late_close_touched: set[str] = set()
                first_scorer = None
                for goal in goals:
                    side = goal["team"]
                    other = "away" if side == "home" else "home"
                    per = _period_key(goal["period"])
                    sit = (goal.get("situation") or "").upper()
                    close = abs(score[side] - score[other]) <= 1
                    late = per in ("3", "OT")
                    tf, ta = team_bucket(season.season_id, names[side]), team_bucket(season.season_id, names[other])
                    tf["gf_by_period"][per] += 1
                    ta["ga_by_period"][per] += 1
                    if "PP" in sit:
                        tf["pp_gf"] += 1; ta["pp_ga"] += 1
                    if "SH" in sit:
                        tf["sh_gf"] += 1; ta["sh_ga"] += 1
                    if "EN" in sit:
                        tf["en_gf"] += 1
                    if late and close:
                        tf["late_close_gf"] += 1; ta["late_close_ga"] += 1
                        late_close_touched.update([side, other])
                    if first_scorer is None:
                        first_scorer = side
                    score[side] += 1
                    for key, field in (("scorer_number", None), ("assist1_number", None), ("assist2_number", None)):
                        num = goal.get(key)
                        pid = pid_by_side[side].get(num) if num is not None else None
                        if pid is None:
                            continue
                        pb = player_bucket(pid)
                        pb["points_by_period"][per] += 1
                        if late and close:
                            pb["late_close_points"] += 1
                        if "PP" in sit:
                            pb["pp_points"] += 1

                # Game-winner: the goal that put the winner ahead for good.
                hf, af = box.get("home_final"), box.get("away_final")
                if hf is not None and af is not None and hf != af:
                    winner = "home" if hf > af else "away"
                    loser_final = min(hf, af)
                    running = {"home": 0, "away": 0}
                    for goal in goals:
                        running[goal["team"]] += 1
                        if goal["team"] == winner and running[winner] == loser_final + 1:
                            num = goal.get("scorer_number")
                            pid = pid_by_side[winner].get(num) if num is not None else None
                            if pid is not None:
                                player_bucket(pid)["game_winners"] += 1
                            break
                    for side in late_close_touched:
                        tb = team_bucket(season.season_id, names[side])
                        tb["late_close_games"] += 1
                        tb["late_close_w" if side == winner else "late_close_l"] += 1
                    if first_scorer:
                        fb = team_bucket(season.season_id, names[first_scorer])
                        fb["first_goal_games"] += 1
                        if first_scorer == winner:
                            fb["first_goal_w"] += 1
                elif first_scorer:
                    team_bucket(season.season_id, names[first_scorer])["first_goal_games"] += 1

    return {"teams": {sid: teams for sid, teams in teams_out.items()}, "players": players}


def _is_placeholder_player(raw: dict) -> bool:
    """A shared roster slot like 'ALT Goalie' shows up on dozens of teams in one season. Nothing
    about it is one person's career, so it gets no spotlight."""
    per_season = defaultdict(set)
    for row in raw.get("summary", []):
        per_season[row["season_label"]].add(row["team"])
    return any(len(teams) > 8 for teams in per_season.values())


def build_player_spotlight(raw: dict, ctx: LeagueContext, our_team_names: set[str], is_ours: bool,
                           position: str | None = None, positions: dict[int, str] | None = None,
                           wowy: dict | None = None) -> dict | None:
    """One skater's cross-league profile: every stint placed in its division and percentile-ranked,
    a caliber grade rolled up from those, trailing-window KPIs over the merged game log, and
    per-level / per-season aggregates for the charts."""
    if _is_placeholder_player(raw):
        return None
    name = raw.get("name") or raw.get("roster_name")
    games_by_stint: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for g in raw.get("games", []):
        games_by_stint[(g["team"], g["season_label"])].append(g)

    stints = []
    for row in raw.get("summary", []):
        key = (row["team"], row["season_label"])
        stint_games = games_by_stint.get(key, [])
        opponents = {g["opponent"] for g in stint_games}
        loc = ctx.locate(row["team"], row["season_label"], opponents)
        tier = sp.parse_tier(loc["level_label"]) if loc else None
        gp = row.get("gp") or 0
        ppg = round((row.get("pts") or 0) / gp, 2) if gp else 0.0
        rank = None
        if loc and tier and gp >= sp.MIN_STINT_GP:
            rank = sp.percentile_in_division(ppg, ctx.population(loc), position, positions)
        first_date = min((g["date"] for g in stint_games), default=None)
        last_date = max((g["date"] for g in stint_games), default=None)
        stints.append({
            "team": row["team"], "season_label": row["season_label"], "season_id": loc["season_id"] if loc else None,
            "league_label": loc["league_label"] if loc else None,
            "level_label": loc["level_label"] if loc else None,
            "tier": tier, "is_us": row["team"] in our_team_names,
            "gp": gp, "goals": row.get("goals") or 0, "assists": row.get("assists") or 0,
            "points": row.get("pts") or 0, "pims": row.get("pims") or 0, "points_per_game": ppg,
            "rank": rank, "first_date": first_date, "last_date": last_date,
            "graded": bool(rank and tier and gp >= sp.MIN_STINT_GP),
        })
    stints.sort(key=lambda s: (s["first_date"] or "0000-00-00"), reverse=True)

    # Caliber: GP x recency weighted mean of each graded stint's rung, then the two adjustments a
    # points-only read can't see (roster persistence at the top tier, with-vs-without-you).
    graded = [s for s in stints if s["graded"]]
    graded_gp = sum(s["gp"] for s in graded)
    latest_game = max((s["last_date"] for s in stints if s["last_date"]), default=None)
    caliber = None
    if graded_gp:
        def age_days(st):
            if not (latest_game and st["last_date"]):
                return None
            return (datetime.strptime(latest_game, "%Y-%m-%d") - datetime.strptime(st["last_date"], "%Y-%m-%d")).days
        for st in graded:
            st["rung"] = round(sp.stint_rung(st["tier"]["rung"], st["rank"]["pct"]), 2)
            st["weight"] = round(st["gp"] * sp.recency_weight(age_days(st)), 2)
        wsum = sum(st["weight"] for st in graded)
        base = sum(st["rung"] * st["weight"] for st in graded) / wsum
        top_tier = max(st["tier"]["rung"] for st in graded)
        seasons_at_top = len({st["season_label"] for st in graded if st["tier"]["rung"] == top_tier})
        persistence = sp.persistence_bonus(seasons_at_top)
        w = wowy.get(raw["player_id"]) if wowy else None
        wowy_adj = sp.wowy_adjustment(w["with_diff"], w["without_diff"]) if w else None
        score = base + persistence + (wowy_adj or 0.0)
        label = sp.caliber_label(score)
        # Trajectory: same math over recent stints vs. everything before them.
        recent = [st for st in graded if (age_days(st) or 10**6) <= sp.TRAJECTORY_WINDOW_DAYS]
        earlier = [st for st in graded if st not in recent]
        def mean_rung(sts):
            tot = sum(st["gp"] for st in sts)
            return sum(st["rung"] * st["gp"] for st in sts) / tot if tot else None
        traj = sp.trajectory(mean_rung(recent), mean_rung(earlier))
        caliber = {"score": round(score, 2), **label, "graded_gp": graded_gp,
                   "graded_stints": len(graded), "confidence": sp.confidence_for(graded_gp),
                   "base_score": round(base, 2), "persistence_bonus": round(persistence, 2),
                   "seasons_at_top_tier": seasons_at_top, "wowy_adjustment": wowy_adj, "wowy": w,
                   "trajectory": traj}

    # Current division(s): whatever they're rostered on in the most recent season they appear in.
    latest_label = None
    latest_sid = -1
    for s in stints:
        if s["season_id"] is not None and s["season_id"] > latest_sid:
            latest_sid, latest_label = s["season_id"], s["season_label"]
    current = [s for s in stints if s["season_label"] == latest_label] if latest_label else []
    current_teams = [{"team": s["team"], "level_label": s["level_label"], "league_label": s["league_label"],
                      "tier": s["tier"], "is_us": s["is_us"]} for s in current]
    current_rungs = [s["tier"]["rung"] for s in current if s["tier"]]
    fit = sp.fit_vs_current(caliber["score"], max(current_rungs)) if (caliber and current_rungs) else None

    # Merged chronological game log across every team/league, with the stint's division attached.
    loc_by_stint = {(s["team"], s["season_label"]): s for s in stints}
    log = []
    for g in raw.get("games", []):
        st = loc_by_stint.get((g["team"], g["season_label"]), {})
        log.append({
            "date": g["date"], "game_id": g["game_id"], "team": g["team"], "opponent": g["opponent"],
            "season_label": g["season_label"], "level_label": st.get("level_label"),
            "tier": st.get("tier", {}).get("name") if st.get("tier") else None,
            "league_label": st.get("league_label"), "is_us": st.get("is_us", False),
            "goals": g.get("goals") or 0, "assists": g.get("assists") or 0,
            "pts": g.get("pts") or 0, "pims": g.get("pims") or 0,
        })
    log.sort(key=lambda g: (g["date"], g["game_id"] or 0))

    windows = {f"L{n}": sp.window_stats(log, n) for n in sp.TREND_WINDOWS}
    windows["All"] = sp.window_stats(log, None)
    trend = trend_block([g["pts"] for g in log], [g["goals"] for g in log])

    # Per-level rollup (the "production by level" chart): the player's P/GP vs the GP-weighted
    # average of the divisions they did it in.
    by_level: dict[str, dict] = {}
    for s in stints:
        if not s["tier"]:
            continue
        b = by_level.setdefault(s["tier"]["name"], {"tier": s["tier"]["name"], "gp": 0, "points": 0,
                                                    "goals": 0, "assists": 0, "_avg_w": 0.0, "_pct_w": 0.0, "_w": 0})
        b["gp"] += s["gp"]; b["points"] += s["points"]; b["goals"] += s["goals"]; b["assists"] += s["assists"]
        if s["rank"]:
            b["_avg_w"] += s["rank"]["division_avg_ppg"] * s["gp"]
            b["_pct_w"] += s["rank"]["pct"] * s["gp"]
            b["_w"] += s["gp"]
    levels = []
    for b in sorted(by_level.values(), key=lambda b: sp.tier_sort_key(b["tier"])):
        levels.append({
            "tier": b["tier"], "gp": b["gp"], "goals": b["goals"], "assists": b["assists"], "points": b["points"],
            "points_per_game": round(b["points"] / b["gp"], 2) if b["gp"] else 0.0,
            "division_avg_ppg": round(b["_avg_w"] / b["_w"], 2) if b["_w"] else None,
            "pct": round(b["_pct_w"] / b["_w"], 1) if b["_w"] else None,
        })

    # Per-season rollup across all teams that season, in chronological order.
    by_season: dict[str, dict] = {}
    for s in stints:
        b = by_season.setdefault(s["season_label"], {"season_label": s["season_label"], "first_date": s["first_date"],
                                                     "gp": 0, "points": 0, "goals": 0, "assists": 0, "teams": []})
        b["gp"] += s["gp"]; b["points"] += s["points"]; b["goals"] += s["goals"]; b["assists"] += s["assists"]
        b["teams"].append(f"{s['team']} ({s['level_label'] or s['season_label']})")
        if s["first_date"] and (b["first_date"] is None or s["first_date"] < b["first_date"]):
            b["first_date"] = s["first_date"]
    seasons_out = []
    for b in sorted(by_season.values(), key=lambda b: b["first_date"] or "0000"):
        seasons_out.append({**b, "points_per_game": round(b["points"] / b["gp"], 2) if b["gp"] else 0.0})

    verdict = _caliber_verdict(name, caliber, levels, fit)

    return {
        "player_id": raw["player_id"], "name": name, "is_ours": is_ours,
        "caliber": caliber, "fit": fit, "verdict": verdict,
        "current_teams": current_teams, "latest_season_label": latest_label,
        "on_our_roster_now": any(s["is_us"] for s in current),
        "windows": windows, "trend": trend,
        "levels": levels, "seasons": seasons_out, "stints": stints, "log": log,
    }


def _tenure(log: list[dict], stints: list[dict]) -> dict | None:
    """Time in the league site's system: first and latest game anywhere, and how many distinct
    seasons (any league) they've been rostered in."""
    dates = [g["date"] for g in log if g.get("date")]
    if not dates:
        return None
    first, last = min(dates), max(dates)
    d0, d1 = datetime.strptime(first, "%Y-%m-%d"), datetime.strptime(last, "%Y-%m-%d")
    return {"first_date": first, "last_date": last, "days": (d1 - d0).days,
            "seasons": len({st["season_label"] for st in stints if st["gp"]})}


def _league_mix(log: list[dict], our_league_labels: set[str]) -> dict:
    """Where their games have been played: share in our league, share in D specifically, and the
    full split by league -- 'how much of this player's hockey is actually our league?'"""
    n = len(log)
    by_league: dict[str, int] = defaultdict(int)
    for g in log:
        by_league[g.get("league_label") or "Other / tournaments"] += 1
    ours = sum(1 for g in log if g.get("league_label") in our_league_labels)
    in_d = sum(1 for g in log if g.get("tier") == "D")
    return {"games": n, "our_league_pct": round(100 * ours / n) if n else 0,
            "d_pct": round(100 * in_d / n) if n else 0,
            "by_league": dict(sorted(by_league.items(), key=lambda kv: -kv[1]))}


def _caliber_verdict(name: str, caliber: dict | None, levels: list[dict], fit: dict | None) -> str:
    if not caliber:
        return (f"Not enough graded games to place {name} on the ladder yet -- a stint needs "
                f"{sp.MIN_STINT_GP}+ games in a division we can rank.")
    parts = []
    for lv in sorted(levels, key=lambda l: -sp.tier_sort_key(l["tier"])):
        if lv["pct"] is None:
            continue
        parts.append(f"{lv['points_per_game']:.2f} P/GP in {lv['tier']} ({sp.ordinal(lv['pct'])} pct over {lv['gp']} GP)")
    detail = "; ".join(parts) if parts else "no ranked stints"
    sentence = f"{caliber['label']} ({caliber['confidence']} confidence): {detail}."
    extras = []
    if caliber.get("persistence_bonus"):
        extras.append(f"+{caliber['persistence_bonus']:.2f} for {caliber['seasons_at_top_tier']} seasons kept at their top level")
    if caliber.get("wowy_adjustment") is not None:
        w = caliber["wowy"]
        extras.append(f"{caliber['wowy_adjustment']:+.2f} with-vs-without ({w['with_diff']:+.2f} goal diff/game dressed vs {w['without_diff']:+.2f} without)")
    if extras:
        sentence += " Adjustments: " + "; ".join(extras) + "."
    tr = caliber.get("trajectory")
    if tr and tr["direction"] != "flat":
        sentence += f" Trajectory: {tr['direction']} ({tr['earlier']:.2f} → {tr['recent']:.2f})."
    if fit:
        sentence += " " + fit["text"]
    return sentence


def build_player_spotlights(seasons: list[SeasonData], franchises: dict, division_logs: dict[int, dict]) -> tuple[dict[int, dict], list[dict]]:
    """Returns (player_id -> full spotlight, index rows for the Players grid). The population is
    every skater with a scraped career page: everyone who has appeared in our division in any season
    we played (ours, every opponent's, one-off appearances). `is_ours` marks who has ever been on
    one of our own rosters."""
    ctx = LeagueContext(franchises)
    our_pids = {row["player_id"] for season in seasons for page in season.our_team_pages.values()
                for row in page["player_stats"] if row.get("player_id") is not None}
    # Positions are hand-maintained (the site records none) -- see data/positions.json.
    positions = {int(k): (v.get("pos") or None) for k, v in _load_json(POSITIONS_PATH, {}).items() if k.isdigit()}
    our_league_labels = {ctx.league_labels.get(int(f["league"])) for f in franchises.values() if f.get("league")}
    # "This season" for scouting = the latest of our seasons that actually has stats yet.
    played = [s.season_id for s in seasons if any(p["player_stats"] for p in s.our_team_pages.values())]
    current_season_id = max(played) if played else None
    wowy = build_wowy(seasons, division_logs)
    vs_us = build_vs_us(seasons, division_logs)
    plus_minus = build_plus_minus(seasons)["players"]
    situational = build_situational(seasons)["players"]
    our_team_names = {name for f in franchises.values() for t in f["team_ids"].values() for name in [t["name"]]}
    our_team_names |= {name for f in franchises.values() for name in f.get("aka", [])} | {f["name"] for f in franchises.values()}
    profiles: dict[int, dict] = {}
    index: list[dict] = []
    if not PLAYERS_RAW_DIR.exists():
        return profiles, index
    for path in sorted(PLAYERS_RAW_DIR.glob("*.json")):
        raw = _load_json(path)
        if not raw or not raw.get("summary"):
            continue
        prof = build_player_spotlight(raw, ctx, our_team_names, raw["player_id"] in our_pids,
                                      positions.get(raw["player_id"]), positions, wowy)
        if prof is None:
            continue
        prof["position"] = positions.get(prof["player_id"])
        prof["teams"] = sorted({st["team"] for st in prof["stints"]})
        # Teams in OUR division (D, in our league) the player has skated for -- the Players tab's team
        # filter is scoped to these, not to every C3/other-league team on their career.
        div_stints = [st for st in prof["stints"] if st["tier"] and st["tier"]["name"] == "D" and st["league_label"] in our_league_labels]
        prof["division_teams"] = sorted({st["team"] for st in div_stints})
        prof["tenure"] = _tenure(prof["log"], prof["stints"])
        prof["league_mix"] = _league_mix(prof["log"], our_league_labels)
        prof["vs_us"] = vs_us.get(prof["player_id"])
        prof["situational"] = situational.get(prof["player_id"])
        prof["wowy"] = wowy.get(prof["player_id"])
        prof["plus_minus"] = plus_minus.get(prof["player_id"])
        prof["division_teams_now"] = sorted({st["team"] for st in div_stints if st["season_id"] == current_season_id})
        profiles[prof["player_id"]] = prof
        index.append({
            "player_id": prof["player_id"], "name": prof["name"], "is_ours": prof["is_ours"],
            "position": prof["position"], "teams": prof["teams"],
            "division_teams": prof["division_teams"], "division_teams_now": prof["division_teams_now"],
            "tenure": prof["tenure"], "league_mix": prof["league_mix"],
            "vs_us": ({k: v for k, v in prof["vs_us"].items() if k != "games"} if prof["vs_us"] else None),
            "situational": prof["situational"], "wowy": prof["wowy"], "plus_minus": prof["plus_minus"],
            "trajectory": prof["caliber"]["trajectory"] if prof["caliber"] else None,
            "caliber": prof["caliber"], "fit": prof["fit"],
            "current_teams": prof["current_teams"], "latest_season_label": prof["latest_season_label"],
            "on_our_roster_now": prof["on_our_roster_now"],
            "levels_played": [l["tier"] for l in prof["levels"]],
            "gp": prof["windows"]["All"]["gp"], "points": prof["windows"]["All"]["points"],
            "points_per_game": prof["windows"]["All"]["points_per_game"],
            "l10_points_per_game": prof["windows"]["L10"]["points_per_game"],
            "momentum": prof["trend"]["momentum"], "spark_svg": prof["trend"]["spark_svg"],
        })
    # Default order: caliber score, strongest first -- the grid's job is "who's our best hockey player".
    index.sort(key=lambda r: (r["caliber"]["score"] if r["caliber"] else -1, r["points_per_game"]), reverse=True)
    return profiles, index


def _week_bucket(iso_date: str) -> tuple[str, str]:
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat(), f"{monday.strftime('%b')} {monday.day}"


def _month_bucket(iso_date: str) -> tuple[str, str]:
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return f"{d.year:04d}-{d.month:02d}", d.strftime("%b %Y")


def _empty_bucket(label: str) -> dict:
    return {"label": label, "gf": 0, "ga": 0, "pims": 0, "w": 0, "l": 0, "t": 0, "gp": 0}


def _add_game_to_bucket(bucket: dict, g: dict) -> None:
    us = g["home_final"] if g["is_home"] else g["away_final"]
    them = g["away_final"] if g["is_home"] else g["home_final"]
    bucket["gf"] += us
    bucket["ga"] += them
    bucket["pims"] += g["pims"] or 0
    bucket["gp"] += 1
    if us > them:
        bucket["w"] += 1
    elif us < them:
        bucket["l"] += 1
    else:
        bucket["t"] += 1


def build_team_timeseries(all_games: list[dict]) -> dict:
    """Buckets our completed games into Week / Month / Season grains -- GF, GA, PIM, and W-L-T per
    bucket -- for the Overview tab's flexible multi-grain trend charts."""
    final = sorted(
        [g for g in all_games if g["is_final"] and g["home_final"] is not None],
        key=lambda g: (g["iso_date"], g["game_id"]),
    )

    def bucket_by(key_fn):
        buckets: dict[str, dict] = {}
        for g in final:
            key, label = key_fn(g["iso_date"])
            buckets.setdefault(key, _empty_bucket(label))
            _add_game_to_bucket(buckets[key], g)
        return [buckets[k] for k in sorted(buckets)]

    season_buckets: dict[int, dict] = {}
    for g in final:
        season_buckets.setdefault(g["season_id"], _empty_bucket(g["season_label"]))
        _add_game_to_bucket(season_buckets[g["season_id"]], g)
    season = [season_buckets[k] for k in sorted(season_buckets)]

    return {"week": bucket_by(_week_bucket), "month": bucket_by(_month_bucket), "season": season}


# Allowlist, not a blocklist: the facility's calendar is mostly stuff we don't want (other teams'
# league games with no desc at all, private lessons, skating classes) -- the small set of "come play"
# public drop-in sessions is much more stable to match on than trying to exclude every junk category,
# including ones that might show up later.
_HOCKEY_EVENT_KEYWORDS = ("stick & puck", "stick and puck", "pick-up hockey", "pickup hockey",
                          "pick-up goalie", "pickup goalie", "open hockey", "drop-in hockey", "drop in hockey")


def _is_public_hockey_event(desc: str) -> bool:
    d = (desc or "").lower()
    return any(kw in d for kw in _HOCKEY_EVENT_KEYWORDS)


def build_rink_events() -> list[dict]:
    """Public drop-in hockey events (Stick & Puck, Adult Pick-Up Hockey/Goalies -- not other teams'
    league games, private lessons, or skating classes, which the facility's API otherwise mixes in)
    for the calendar overlay. Uses the API's `start_gmt`/`end_gmt` (true UTC) rather than `start`/`end`
    (local time with no offset marker) -- the browser needs an unambiguous instant to convert to
    the viewer's own timezone, and a naive "2026-09-11T13:00:00" string would otherwise be
    misinterpreted as being in *the viewer's* timezone, not the rink's, for anyone not in US/Eastern.
    """
    raw = _load_json(RINK_EVENTS_RAW_PATH, [])
    out = []
    for e in raw:
        if not e.get("start_gmt") or not e.get("end_gmt"):
            continue
        if not _is_public_hockey_event(e.get("desc")):
            continue
        event_date = e["start_gmt"][:10]
        dashboard_url = None
        if e.get("_company"):
            params = f"date={event_date}&sport_ids={e.get('_sport_id')}"
            if e.get("_facility_id") is not None:
                params += f"&facility_ids={e['_facility_id']}"
            dashboard_url = f"https://apps.daysmartrecreation.com/dash/x/{e['_company']}/event-registration?{params}"
        out.append({
            "title": e.get("desc") or "Event",
            "start": e["start_gmt"] + "Z", "end": e["end_gmt"] + "Z",
            "label": e.get("_calendar_label"), "dashboard_url": dashboard_url,
        })
    return out


def _our_side_pims(box: dict, our_name: str) -> int | None:
    side = "home" if box["home_name"] == our_name else "away"
    return sum(p["minutes"] for p in box["penalties"].get(side, []) if p.get("minutes")) or 0


def build_games(seasons: list[SeasonData]) -> tuple[dict, list[dict]]:
    """Returns (games_out, all_games): `games_out` is game_id -> full corrected box score, only for
    completed games with a box score (used for the per-game detail view). `all_games` is every game
    for our team across every season -- completed or not, with an inferred iso_date -- used for the
    condensed season-bucketed Games table and the calendar view, both of which need to show upcoming
    games too."""
    games_out = {}
    all_games: list[dict] = []
    game_videos = load_game_videos()

    for season in seasons:
        for team_id, page in season.our_team_pages.items():
            our_name = season.our_team_name.get(team_id)
            # iso_date was already assigned in SeasonData.__init__; sort by it here for true
            # chronological order (game_id is not reliable for that -- see assign_iso_dates).
            season_games = sorted(page["games"], key=lambda g: (g["iso_date"], g["game_id"]))
            for g in season_games:
                g["season_id"] = season.season_id

            for g in season_games:
                is_home = g["home_name"] == our_name
                opponent = g["away_name"] if is_home else g["home_name"]
                row = {
                    "game_id": g["game_id"], "season_id": season.season_id,
                    "season_label": season_label(season.season_id), "iso_date": g["iso_date"],
                    "date": g["date"], "time": g["time"], "rink": g["rink"], "game_type": g["game_type"],
                    "is_home": is_home, "opponent": opponent, "is_final": g["is_final"],
                    "home_name": g["home_name"], "away_name": g["away_name"],
                    "home_final": g["home_goals"], "away_final": g["away_goals"], "pims": None,
                    "decided_in": g.get("decided_in"),  # "OT" / "SO" when it went past regulation
                    "video": game_videos.get(g["game_id"]),
                }
                if g["is_final"] and g["has_boxscore"]:
                    box = season.load_corrected_boxscore(g["game_id"])
                    if box is not None:
                        row["pims"] = _our_side_pims(box, our_name)
                        games_out[str(g["game_id"])] = {**row, **box}
                all_games.append(row)

    return games_out, all_games


RINK_TZ = ZoneInfo("America/New_York")  # every rink we play at (Baptist Health Iceplex) is in this tz
GAME_DURATION = timedelta(minutes=75)  # the league site never states an end time


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line: str) -> str:
    """RFC 5545 line folding: continuation lines start with a single space, max 75 octets/line."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    out, chunk = [], b""
    for piece in re.findall(r".", line):
        candidate = chunk + piece.encode("utf-8")
        if len(candidate) > (75 if not out else 74):
            out.append(chunk)
            chunk = piece.encode("utf-8")
        else:
            chunk = candidate
    if chunk:
        out.append(chunk)
    return "\r\n ".join(c.decode("utf-8") for c in out)


def _game_start(iso_date: str, time_str: str) -> datetime | None:
    if not time_str:
        return None
    try:
        naive = datetime.strptime(f"{iso_date} {time_str}", "%Y-%m-%d %I:%M %p")
    except ValueError:
        return None
    return naive.replace(tzinfo=RINK_TZ)


def build_schedule_ics(all_games: list[dict], team_name: str) -> str:
    """Renders every game we have (past + upcoming, every season) as an .ics feed at
    data/derived/schedule.ics -> docs/data/schedule.ics. Point a bench-management app's calendar sync
    (e.g. BenchApp's Schedule > Add > Sync Schedule) at that published URL and it stays current on its
    own -- the daily refresh-data workflow rebuilds this file straight from the league site, so there's
    nothing to re-upload by hand when a game gets added, rescheduled, or its rink changes."""
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//mid-ice-crisis-stats//schedule//EN",
        "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_ics_escape(team_name)} Schedule",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for g in sorted(all_games, key=lambda g: (g["iso_date"], g["game_id"])):
        start = _game_start(g["iso_date"], g["time"])
        if start is None:
            continue
        start_utc, end_utc = start.astimezone(timezone.utc), (start + GAME_DURATION).astimezone(timezone.utc)
        summary = f"{team_name} {'vs' if g['is_home'] else '@'} {g['opponent']}"
        desc = [g["game_type"], g["season_label"]]
        if g["is_final"] and g["home_final"] is not None:
            desc.append(f"Final: {g['home_name']} {g['home_final']}-{g['away_final']} {g['away_name']}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:game-{g['game_id']}@mid-ice-crisis-stats",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"LOCATION:{_ics_escape(g['rink'] or '')}",
            f"DESCRIPTION:{_ics_escape(' | '.join(desc))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(l) for l in lines) + "\r\n"


def _save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def main() -> None:
    franchises = load_franchises()
    season_ids = discover_seasons()
    seasons = [SeasonData(sid, franchises) for sid in season_ids]
    seasons = [s for s in seasons if s.our_team_pages]  # drop seasons with nothing of ours

    division_logs = {s.season_id: collect_division_logs(s) for s in seasons}
    our_leaderboards, division_leaderboards = build_leaderboards(seasons, division_logs)
    team_pace = build_team_pace(seasons, division_logs)
    head_to_head = build_head_to_head(seasons)

    _save_json(DERIVED / "team_summary.json", build_team_summary(seasons, franchises))
    _save_json(DERIVED / "player_leaderboards.json", our_leaderboards)
    _save_json(DERIVED / "division_leaderboards.json", division_leaderboards)
    _save_json(DERIVED / "head_to_head.json", head_to_head)
    _save_json(DERIVED / "schedule_heatmap.json", build_schedule_heatmap(seasons))
    _save_json(DERIVED / "league_outliers.json", build_league_outliers(seasons, division_leaderboards))
    _save_json(DERIVED / "team_pace.json", team_pace)
    _save_json(DERIVED / "standings.json", build_standings(seasons, team_pace, LeagueContext(franchises), franchises))
    _save_json(DERIVED / "league_insights.json",
               build_league_insights(seasons, division_logs, division_leaderboards, team_pace))
    _save_json(DERIVED / "scouting_report.json",
               build_scouting_report(seasons, division_leaderboards, team_pace, head_to_head))
    _save_json(DERIVED / "meta.json", {"generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes")})

    games, all_games = build_games(seasons)
    pm_games = build_plus_minus(seasons)["games"]
    for game_id, game in games.items():
        game["on_ice_tags"] = _load_json(ON_ICE_DIR / f"{game_id}.json", {}).get("goals", [])
        game["tag_coverage"] = pm_games.get(game_id)
    for game_id, game in games.items():
        _save_json(DERIVED / "games" / f"{game_id}.json", game)
    _save_json(DERIVED / "games_index.json", sorted(all_games, key=lambda g: (g["iso_date"], g["game_id"])))
    _save_json(DERIVED / "team_timeseries.json", build_team_timeseries(all_games))
    _save_json(DERIVED / "rink_events.json", build_rink_events())

    team_name = next(iter(franchises.values()))["name"] if franchises else "Team"
    _save_text(DERIVED / "schedule.ics", build_schedule_ics(all_games, team_name))

    profiles, players_index = build_player_spotlights(seasons, franchises, division_logs)
    # Prune profiles for players no longer in the index (a placeholder id, a scrape config change)
    # so docs/ doesn't accumulate orphaned files that nothing links to.
    players_dir = DERIVED / "players"
    if players_dir.exists():
        for stale in players_dir.glob("*.json"):
            if not stale.stem.isdigit() or int(stale.stem) not in profiles:
                stale.unlink()
    situational = build_situational(seasons)
    _save_json(DERIVED / "situational.json", {str(k): v for k, v in situational["teams"].items()})
    for pid, prof in profiles.items():
        _save_json(DERIVED / "players" / f"{pid}.json", prof)
    _save_json(DERIVED / "players_index.json", players_index)
    print(f"built {len(profiles)} player spotlights")

    print(f"built derived data for {len(seasons)} seasons, {len(games)} completed games, {len(all_games)} total")


if __name__ == "__main__":
    main()
