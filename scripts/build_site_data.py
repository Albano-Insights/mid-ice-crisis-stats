"""Builds data/derived/** (everything the dashboard fetches) from data/raw/** + data/corrections/**.

Run after scripts/scrape.py. Safe to re-run any time -- it only reads raw/corrections and rewrites
derived output, never touching raw scraped data.

Usage: python scripts/build_site_data.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from lib import analytics, corrections as corr

TREND_WINDOW = 10  # trailing games used for sparklines + the half-split momentum score
MIN_GAMES_FOR_TREND = 3

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

    final_games = sorted([g for g in page["games"] if g["is_final"]], key=lambda g: g["game_id"])
    for game in final_games:
        is_home = game["home_name"] == team_name
        gf, ga = (game["home_goals"], game["away_goals"]) if is_home else (game["away_goals"], game["home_goals"])
        result = "W" if gf > ga else ("L" if gf < ga else "T")
        cume_diff += gf - ga
        cume_wl += 1 if result == "W" else (-1 if result == "L" else 0)
        team_log.append({
            "game_id": game["game_id"], "date": game["date"], "gf": gf, "ga": ga, "result": result,
            "cume_diff": cume_diff, "cume_wl": cume_wl,
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
                "game_id": game["game_id"], "date": game["date"],
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
                           reported_extra: dict[int, dict]) -> list[dict]:
    out = []
    for pid, entries in logs.items():
        entries = sorted(entries, key=lambda e: e["game_id"])
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

    for season in seasons:
        dl = division_logs[season.season_id]
        our_team_names = {season.team_name_by_id.get(tid) for tid in season.our_team_pages}
        our_pids = {pid for pid, team in dl["teams_by_pid"].items() if team in our_team_names}

        our_logs_this_season = {pid: dl["player_logs"][pid] for pid in our_pids}
        our_by_season[season.season_id] = _finalize_leaderboard(our_logs_this_season, dl["names"], dl["reported_extra"])

        for pid in our_pids:
            our_career_logs[pid].extend(dl["player_logs"][pid])
            our_career_names[pid] = dl["names"][pid]
        our_career_extra.update(dl["reported_extra"])

        division_rows = _finalize_leaderboard(dl["player_logs"], dl["names"], dl["reported_extra"])
        for row in division_rows:
            row["team"] = dl["teams_by_pid"].get(row["player_id"])
        division_by_season[season.season_id] = division_rows

    our_leaderboards = {
        "career": _finalize_leaderboard(our_career_logs, our_career_names, our_career_extra),
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

    game = min(upcoming, key=lambda g: g["game_id"])
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
    }


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
    _save_json(DERIVED / "league_insights.json",
               build_league_insights(seasons, division_logs, division_leaderboards, team_pace))
    _save_json(DERIVED / "scouting_report.json",
               build_scouting_report(seasons, division_leaderboards, team_pace, head_to_head))
    _save_json(DERIVED / "meta.json", {"generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes")})

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
