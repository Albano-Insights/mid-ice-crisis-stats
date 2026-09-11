"""Builds data/derived/** (everything the dashboard fetches) from data/raw/** + data/corrections/**.

Run after scripts/scrape.py. Safe to re-run any time -- it only reads raw/corrections and rewrites
derived output, never touching raw scraped data.

Usage: python scripts/build_site_data.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from lib import corrections as corr

ROOT = Path(__file__).parent.parent
DATA_RAW = ROOT / "data" / "raw"
CORRECTIONS_DIR = ROOT / "data" / "corrections"
DERIVED = ROOT / "data" / "derived"
FRANCHISES_PATH = ROOT / "data" / "franchises.json"
SEASON_LABELS_PATH = ROOT / "data" / "raw" / "season_labels.json"

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
    return _load_json(FRANCHISES_PATH, {})


def season_label(season_id: int) -> str:
    labels = _load_json(SEASON_LABELS_PATH, {})
    return labels.get(str(season_id), f"Season {season_id}")


def discover_seasons() -> list[int]:
    if not (DATA_RAW / "seasons").exists():
        return []
    return sorted(int(p.name) for p in (DATA_RAW / "seasons").iterdir() if p.name.isdigit())


class SeasonData:
    """Everything scraped for one season: our team(s)' schedule/stats + standings + league stats."""

    def __init__(self, season_id: int, franchises: dict):
        self.season_id = season_id
        self.dir = DATA_RAW / "seasons" / str(season_id)
        self.standings = _load_json(self.dir / "standings.json", [])
        self.our_team_pages: dict[int, dict] = {}  # team_id -> parsed schedule page
        self.our_team_name: dict[int, str] = {}
        self.name_to_player_id: dict[int, dict[str, int]] = {}  # team_id -> {name: player_id}

        for franchise in franchises.values():
            for team_id_str in franchise["team_ids"]:
                team_id = int(team_id_str)
                page = _load_json(self.dir / f"schedule_{team_id}.json")
                if page is None:
                    continue
                self.our_team_pages[team_id] = page
                name_map = {}
                for row in page["player_stats"] + page["goalie_stats"]:
                    if row.get("player_id") is not None:
                        name_map[row["name"]] = row["player_id"]
                self.name_to_player_id[team_id] = name_map
                standing = next((r for r in self.standings if r["team_id"] == team_id), None)
                self.our_team_name[team_id] = standing["name"] if standing else None

    def all_games(self) -> list[dict]:
        out = []
        for team_id, page in self.our_team_pages.items():
            for g in page["games"]:
                out.append({**g, "our_team_id": team_id})
        return out

    def load_corrected_boxscore(self, game_id: int) -> dict | None:
        box = _load_json(self.dir / f"boxscore_{game_id}.json")
        if box is None:
            return None
        return corr.apply_corrections(box, corr.load_corrections(CORRECTIONS_DIR, game_id))


def _our_side(box: dict, our_team_id: int, season: SeasonData) -> str:
    our_name = season.our_team_name.get(our_team_id)
    if box["home_name"] == our_name:
        return "home"
    if box["away_name"] == our_name:
        return "away"
    # fall back to whichever side's roster contains our known player names
    our_players = set(season.name_to_player_id.get(our_team_id, {}))
    home_roster_names = {p["name"] for p in box["rosters"].get(box["home_name"], [])}
    return "home" if our_players & home_roster_names else "away"


def build_player_leaderboards(seasons: list[SeasonData], franchises: dict) -> dict:
    career = defaultdict(lambda: {"name": None, "goals": 0, "primary_assists": 0, "secondary_assists": 0,
                                   "pims": 0, "hat_tricks": 0, "games": set()})
    by_season = defaultdict(lambda: defaultdict(
        lambda: {"name": None, "goals": 0, "primary_assists": 0, "secondary_assists": 0,
                 "pims": 0, "hat_tricks": 0, "games": set()}))
    reported_extra: dict[int, dict] = {}  # player_id -> {shots, plus_minus} as last reported by the site

    for season in seasons:
        for team_id, page in season.our_team_pages.items():
            name_map = season.name_to_player_id[team_id]
            for row in page["player_stats"]:
                if row.get("player_id") is not None:
                    reported_extra[row["player_id"]] = {"shots": row.get("shots"),
                                                          "plus_minus": row.get("plus_minus")}

            for game in page["games"]:
                if not (game["is_final"] and game["has_boxscore"]):
                    continue
                box = season.load_corrected_boxscore(game["game_id"])
                if box is None:
                    continue
                side = _our_side(box, team_id, season)
                our_name = box["home_name"] if side == "home" else box["away_name"]
                roster_by_number = {p["number"]: p["name"] for p in box["rosters"].get(our_name, [])}

                for roster_name in roster_by_number.values():
                    roster_id = name_map.get(roster_name)
                    if roster_id is not None:
                        for bucket in (career[roster_id], by_season[season.season_id][roster_id]):
                            bucket["name"] = roster_name
                            bucket["games"].add(game["game_id"])

                per_game_goals = defaultdict(int)
                for goal in box["goals"]:
                    if goal["team"] != side:
                        continue
                    scorer_name = roster_by_number.get(goal["scorer_number"])
                    scorer_id = name_map.get(scorer_name)
                    if scorer_id is not None:
                        per_game_goals[scorer_id] += 1
                        for bucket in (career[scorer_id], by_season[season.season_id][scorer_id]):
                            bucket["name"] = scorer_name
                            bucket["goals"] += 1
                            bucket["games"].add(game["game_id"])

                    for field, key in (("assist1_number", "primary_assists"), ("assist2_number", "secondary_assists")):
                        assist_name = roster_by_number.get(goal[field])
                        assist_id = name_map.get(assist_name)
                        if assist_id is not None:
                            for bucket in (career[assist_id], by_season[season.season_id][assist_id]):
                                bucket["name"] = assist_name
                                bucket[key] += 1
                                bucket["games"].add(game["game_id"])

                for pid, g in per_game_goals.items():
                    if g >= 3:
                        career[pid]["hat_tricks"] += 1
                        by_season[season.season_id][pid]["hat_tricks"] += 1

                for pen in box["penalties"].get(side, []):
                    pen_name = roster_by_number.get(pen["number"])
                    pen_id = name_map.get(pen_name)
                    if pen_id is not None and pen.get("minutes"):
                        career[pen_id]["pims"] += pen["minutes"]
                        by_season[season.season_id][pen_id]["pims"] += pen["minutes"]

    def _finalize(d: dict) -> list[dict]:
        out = []
        for pid, row in d.items():
            games = len(row["games"])
            goals, pa, sa = row["goals"], row["primary_assists"], row["secondary_assists"]
            points = goals + pa + sa
            extra = reported_extra.get(pid, {})
            out.append({
                "player_id": pid, "name": row["name"], "games_played": games,
                "goals": goals, "primary_assists": pa, "secondary_assists": sa,
                "assists": pa + sa, "points": points,
                "points_per_game": round(points / games, 2) if games else 0,
                "pims": row["pims"], "hat_tricks": row["hat_tricks"],
                "shots_as_reported": extra.get("shots"), "plus_minus_as_reported": extra.get("plus_minus"),
            })
        out.sort(key=lambda r: r["points"], reverse=True)
        return out

    return {
        "career": _finalize(career),
        "by_season": {season_id: _finalize(rows) for season_id, rows in by_season.items()},
    }


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

    all_games_chrono.sort(key=lambda g: g["game_id"])  # game_id increases monotonically with time site-wide

    season_by_id = {s.season_id: s for s in seasons}
    results = []
    for g in all_games_chrono:
        season = season_by_id[g["season_id"]]
        our_name = season.our_team_name.get(g["our_team_id"])
        if g["home_name"] == our_name:
            us, them = g["home_goals"], g["away_goals"]
        else:
            us, them = g["away_goals"], g["home_goals"]
        if us > them:
            results.append("W")
        elif us < them:
            results.append("L")
        else:
            results.append("T")

    current_streak = {"result": None, "length": 0}
    if results:
        last = results[-1]
        n = 0
        for r in reversed(results):
            if r != last:
                break
            n += 1
        current_streak = {"result": last, "length": n}

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

    return {"overall": overall, "current_streak": current_streak, "by_season": by_season}


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
                    "season_label": season_label(season.season_id), "date": g["date"],
                    "us": us, "them": them, "game_type": g["game_type"],
                })

    for row in opponents.values():
        row["meetings"].sort(key=lambda m: m["game_id"])

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


def build_league_outliers(seasons: list[SeasonData]) -> dict:
    out = {}
    for season in seasons:
        level_files = list(season.dir.glob("league_stats_level_*.json"))
        if not level_files:
            continue
        level_id = level_files[0].stem.split("_")[-1]
        players = _load_json(level_files[0], [])
        level_label = next((r["level_label"] for r in season.standings if str(r.get("level_id")) == level_id), None)

        def top(key, n=5):
            return sorted([p for p in players if p.get(key) is not None], key=lambda p: p[key], reverse=True)[:n]

        out[season.season_id] = {
            "level_id": level_id,
            "level_label": level_label,
            "season_label": season_label(season.season_id),
            "leaders": {
                "goals": top("goals"),
                "assists": top("assists"),
                "points": top("pts"),
                "pims": top("pims"),
            },
        }
    return out


def build_games(seasons: list[SeasonData]) -> dict:
    games_out = {}
    for season in seasons:
        for team_id, page in season.our_team_pages.items():
            for g in page["games"]:
                if not (g["is_final"] and g["has_boxscore"]):
                    continue
                box = season.load_corrected_boxscore(g["game_id"])
                if box is None:
                    continue
                games_out[str(g["game_id"])] = {
                    "game_id": g["game_id"], "season_id": season.season_id,
                    "season_label": season_label(season.season_id),
                    "date": g["date"], "time": g["time"], "rink": g["rink"], "game_type": g["game_type"],
                    **box,
                }
    return games_out


def main() -> None:
    franchises = load_franchises()
    season_ids = discover_seasons()
    seasons = [SeasonData(sid, franchises) for sid in season_ids]
    seasons = [s for s in seasons if s.our_team_pages]  # drop seasons with nothing of ours

    _save_json(DERIVED / "team_summary.json", build_team_summary(seasons, franchises))
    _save_json(DERIVED / "player_leaderboards.json", build_player_leaderboards(seasons, franchises))
    _save_json(DERIVED / "head_to_head.json", build_head_to_head(seasons))
    _save_json(DERIVED / "schedule_heatmap.json", build_schedule_heatmap(seasons))
    _save_json(DERIVED / "league_outliers.json", build_league_outliers(seasons))

    games = build_games(seasons)
    for game_id, game in games.items():
        _save_json(DERIVED / "games" / f"{game_id}.json", game)
    _save_json(DERIVED / "games_index.json", sorted(
        [{"game_id": g["game_id"], "season_id": g["season_id"], "season_label": g["season_label"],
          "date": g["date"], "home_name": g["home_name"], "away_name": g["away_name"],
          "home_final": g["home_final"], "away_final": g["away_final"]} for g in games.values()],
        key=lambda g: g["game_id"]))

    print(f"built derived data for {len(seasons)} seasons, {len(games)} games")


if __name__ == "__main__":
    main()
