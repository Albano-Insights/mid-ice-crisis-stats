"""Pure helpers behind the Overview's two League Lowdown cards: which games count as "this week",
what the division table looked like at the start of that week, how tight a division's race is, and
what changed in another division since the last stored snapshot.

Split out of build_site_data.py so each piece can be tested on hand-written inputs -- the build
itself needs a full scrape on disk, which is no way to test a window boundary.

Two different kinds of question live here, because the league site gives us two different grains:

- Our own division is game grain (every box score is scraped), so "this week" is a real window over
  real games and the table can be replayed at any date.
- Every other division is season totals only (standings plus a top-100 scorer table, no game dates).
  Week-over-week there is only possible by storing a snapshot each night and diffing it, which is
  what `diff_snapshot` is for.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

WINDOW_DAYS = 7          # "this week"
WINDOW_MIN_GAMES = 3     # below this the window widens -- see `window`
WINDOW_CAP_DAYS = 21     # never widen past three weeks, and past this a season counts as archived

TIGHTNESS_MIN_GP = 3     # a team with fewer games has too noisy a points-per-game to rank
TIGHTNESS_MIN_TEAMS = 4  # a 2-3 team sample's spread says nothing


def _d(iso: str) -> date:
    return date.fromisoformat(iso)


def window(game_dates: list[str], today: str, *, days: int = WINDOW_DAYS,
           min_games: int = WINDOW_MIN_GAMES, cap_days: int = WINDOW_CAP_DAYS) -> dict | None:
    """The span of dates the week card should cover, from one date per completed game (duplicates
    expected -- two games on a Sunday are two entries).

    Returns {"from", "to", "games", "is_final_week", "widened"}, or None when nothing has been
    played. `from` and `to` are both inclusive.

    This division plays about once a team per week, so a plain trailing 7 days renders an empty card
    on any quiet stretch -- the same problem `divisionUpcoming` in docs/app.js documents for the
    upcoming strip, and the reason it carries a floor too. So when the last `days` hold fewer than
    `min_games`, the window walks back over earlier game dates until it has `min_games`, stopping at
    `cap_days`. Widening reaches back over whole dates, never half a slate, so a card never shows
    one game from a night and hides the other.

    A season whose most recent game is older than `cap_days` is over. Rather than render an empty
    card for an archived season, the window becomes that season's own final `days`, flagged
    `is_final_week` so the card can say so instead of claiming it is current.
    """
    played = sorted(d for d in game_dates if d <= today)
    if not played:
        return None
    last = played[-1]

    if _d(last) < _d(today) - timedelta(days=cap_days):
        frm = (_d(last) - timedelta(days=days)).isoformat()
        return {"from": frm, "to": last, "games": sum(1 for d in played if d >= frm),
                "is_final_week": True, "widened": False}

    frm = (_d(today) - timedelta(days=days)).isoformat()
    selected = [d for d in played if d >= frm]
    widened = False
    if len(selected) < min_games:
        floor = (_d(today) - timedelta(days=cap_days)).isoformat()
        for candidate in sorted({d for d in played if d >= floor}, reverse=True):
            if candidate >= frm:
                continue
            frm, widened = candidate, True
            selected = [d for d in played if d >= frm]
            if len(selected) >= min_games:
                break
    return {"from": frm, "to": today, "games": len(selected),
            "is_final_week": False, "widened": widened}


def _points(game: dict) -> int:
    """League scoring: a win is 2 whether or not it needed overtime, a tie or an overtime/shootout
    loss is 1, a regulation loss is 0. Matches the note on the Overview's standings table."""
    result = game.get("result")
    if result == "W":
        return 2
    if result == "T":
        return 1
    if result == "L" and game.get("decided_in") in ("OT", "SO"):
        return 1
    return 0


def rank_key(row: dict):
    """The dashboard's division ordering: points, then regulation wins, then goal differential,
    then name.

    This is deliberately one function used by both `build_standings` (the table on the Overview)
    and `table_as_of` (the replay behind the movers strip). The league site's own tie order is not
    reproducible from the columns it publishes -- in Adult A it currently lists a team on 3
    regulation wins and +7 ahead of one on 4 and +34, which neither wins, differential nor points
    percentage explains, so it is likely head-to-head or just insertion order. Rather than guess,
    the dashboard ranks ties its own way and says so in the glossary. What matters is that the two
    places agree: the movers strip must never claim a team climbed past someone the standings table
    directly above it still shows ahead.
    """
    return (-(row.get("pts") or 0), -(row.get("w") or 0), -(row.get("diff") or 0),
            row.get("name") or "")


def table_as_of(teams: list[dict], iso_date: str) -> list[dict]:
    """Replay the division table from each team's own game list, counting only completed regular
    in-division games on or before `iso_date`.

    Used for the *start* of the week, so the movers strip can say a team climbed. Ordered by
    `rank_key`, the same ordering the Overview's standings table uses.
    """
    rows = []
    for team in teams:
        pts = gf = ga = gp = reg_wins = 0
        for game in team.get("games", []):
            if not (game.get("final") and game.get("regular") and game.get("in_division")):
                continue
            if game.get("iso_date", "") > iso_date:
                continue
            gp += 1
            gf += game.get("gf") or 0
            ga += game.get("ga") or 0
            pts += _points(game)
            if game.get("result") == "W" and game.get("decided_in") not in ("OT", "SO"):
                reg_wins += 1
        rows.append({"team_id": team.get("team_id"), "name": team.get("name"),
                     "is_us": bool(team.get("is_us")), "gp": gp, "pts": pts, "w": reg_wins,
                     "gf": gf, "ga": ga, "diff": gf - ga})
    rows.sort(key=rank_key)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def tightness(teams: list[dict], *, min_gp: int = TIGHTNESS_MIN_GP,
              min_teams: int = TIGHTNESS_MIN_TEAMS) -> dict | None:
    """How close a division's race is, and how much it scores, from standings rows alone.

    Returns {"teams", "ppg_spread", "goals_per_game", "mean_abs_diff"} or None when the division is
    too small or too early to say anything.

    Everything is per game because games played inside one division currently range from 2 to 6, so
    raw points would just rank whoever has played most. `ppg_spread` is the population standard
    deviation of points per game: low means nobody is running away with it. `goals_per_game` is per
    team per game. `mean_abs_diff` is the average team's goal differential per game ignoring sign,
    a second read on the same thing -- a division of blowouts has a high one even if the points
    happen to be level.
    """
    eligible = [t for t in teams if (t.get("gp") or 0) >= min_gp]
    if len(eligible) < min_teams:
        return None
    ppg = [(t.get("pts") or 0) / t["gp"] for t in eligible]
    total_gp = sum(t["gp"] for t in eligible)
    diffs = [abs((t.get("gf") or 0) - (t.get("ga") or 0)) / t["gp"] for t in eligible]
    return {
        "teams": len(eligible),
        "ppg_spread": round(statistics.pstdev(ppg), 2),
        "goals_per_game": round(sum(t.get("gf") or 0 for t in eligible) / total_gp, 2),
        "mean_abs_diff": round(statistics.mean(diffs), 2),
    }


def diff_snapshot(now: dict, prior: dict | None) -> dict:
    """Counter deltas between two nightly snapshots, for teams and players alike.

    Every entry carries `was_absent`: True when the entity is in `now` but not in `prior`. That
    matters because a snapshot stores only each division's top scorers, so a player missing from
    last week's file may simply have been below the cap rather than new -- their delta would then
    read as their whole season. Callers building "gained the most this week" notes should use only
    entries with `was_absent` False, where the delta is exact.

    With no prior snapshot at all (the first week this runs), both maps come back empty rather than
    claiming every season total as this week's work.
    """
    if not prior:
        return {"teams": {}, "players": {}, "from": None}
    out = {"teams": {}, "players": {}, "from": prior.get("date")}
    for kind in ("teams", "players"):
        old = prior.get(kind) or {}
        for key, cur in (now.get(kind) or {}).items():
            was = old.get(key)
            base = was or {}
            entry = {"was_absent": was is None}
            for field, value in cur.items():
                if isinstance(value, (int, float)) and field != "lvl":
                    entry[field] = value - (base.get(field) or 0)
            out[kind][key] = entry
    return out
