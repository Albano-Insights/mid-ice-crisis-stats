"""Scrapes stats.panthers.timetoscore.com into data/raw/**.

For every team_id listed in data/franchises.json, probes every season id from 0 up to a bit past the
newest season any franchise has played (so a brand-new season is picked up automatically before anyone
edits the config), records that team's games + season stat tables, the league standings for any season
touched, and the full box score for every completed game. Already-cached raw files are reused so repeat
runs (e.g. the nightly GitHub Action) only do network work for new/updated games.

Usage: python scripts/scrape.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import ttscore_client as tt

ROOT = Path(__file__).parent.parent
DATA_RAW = ROOT / "data" / "raw"
FRANCHISES_PATH = ROOT / "data" / "franchises.json"
SEASON_LABELS_PATH = ROOT / "data" / "raw" / "season_labels.json"

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
    return _load_json(FRANCHISES_PATH, {})


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
                team_page = fetch_team_season(team_id, season_id)
                if not team_page["games"]:
                    continue  # this team_id didn't exist / didn't play in this season

                seasons_touched.add(season_id)
                schedule_path = _season_dir(season_id) / f"schedule_{team_id}.json"
                _save_json(schedule_path, team_page)
                print(f"  season {season_id}: {len(team_page['games'])} games, "
                      f"{len(team_page['player_stats'])} skaters")

                for game in team_page["games"]:
                    if game["is_final"] and game["has_boxscore"]:
                        fetch_boxscore_cached(season_id, game["game_id"])

    for season_id in sorted(seasons_touched):
        print(f"fetching standings for season {season_id}")
        standings = fetch_standings_cached(season_id)

        our_level_ids = {row["level_id"] for row in standings if row["team_id"] in our_team_ids}
        for level_id in our_level_ids:
            if level_id is None:
                continue
            print(f"  fetching league-wide player stats: season {season_id} level {level_id}")
            fetch_league_stats_cached(season_id, level_id)

    print(f"done. seasons touched: {sorted(seasons_touched)}")


if __name__ == "__main__":
    scrape()
