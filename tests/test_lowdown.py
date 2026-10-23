"""The four pure pieces behind the League Lowdown cards.

What has to hold or a card is worse than nothing: the week window must never render empty on a
quiet stretch (this division plays about once a team per week), an archived season must say so
rather than claim to be current, the replayed table must agree with the official one so the movers
strip can't contradict the standings sitting directly above it, the division tightness numbers must
refuse to rank a sample too small to mean anything, and a snapshot diff must not claim a player's
whole season as this week's work just because they were below last week's top-scorer cap.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lib import lowdown  # noqa: E402

TODAY = "2026-10-22"


# --- window -----------------------------------------------------------------------------------

def test_a_normal_week_is_a_trailing_seven_days():
    # The real D1 slate as of Oct 22: Oct 18, two on Oct 20, Oct 21.
    w = lowdown.window(["2026-10-04", "2026-10-11", "2026-10-18", "2026-10-20", "2026-10-20",
                        "2026-10-21"], TODAY)
    assert (w["from"], w["to"]) == ("2026-10-15", TODAY)
    assert w["games"] == 4
    assert not w["widened"] and not w["is_final_week"]


def test_a_quiet_stretch_widens_rather_than_rendering_empty():
    # One game in the last 7 days; the window must reach back for more.
    w = lowdown.window(["2026-10-03", "2026-10-04", "2026-10-11", "2026-10-20"], TODAY)
    assert w["widened"]
    assert w["games"] >= lowdown.WINDOW_MIN_GAMES
    assert w["from"] <= "2026-10-11"


def test_widening_takes_whole_dates_so_a_slate_is_never_split():
    # Two games on Oct 11. Reaching back for a third must bring in both, not one.
    w = lowdown.window(["2026-10-11", "2026-10-11", "2026-10-20"], TODAY)
    assert w["from"] == "2026-10-11"
    assert w["games"] == 3


def test_widening_stops_at_the_cap_even_if_still_short():
    w = lowdown.window(["2026-09-01", "2026-09-02", "2026-10-21"], TODAY)
    assert w["from"] >= "2026-10-01"  # cap_days=21 back from Oct 22
    assert w["games"] == 1            # the September games stay out


def test_an_archived_season_windows_its_own_final_week():
    w = lowdown.window(["2026-01-18", "2026-01-25", "2026-02-01"], TODAY)
    assert w["is_final_week"]
    assert (w["from"], w["to"]) == ("2026-01-25", "2026-02-01")
    assert w["games"] == 2


def test_future_games_are_never_counted():
    w = lowdown.window(["2026-10-21", "2026-11-08", "2026-11-12"], TODAY)
    assert w["to"] == TODAY
    assert w["games"] == 1


def test_no_games_at_all_is_none_not_an_empty_window():
    assert lowdown.window([], TODAY) is None
    assert lowdown.window(["2026-11-08"], TODAY) is None


# --- table_as_of ------------------------------------------------------------------------------

def _game(iso, result, gf, ga, *, decided_in=None, final=True, regular=True, in_division=True):
    return {"iso_date": iso, "result": result, "gf": gf, "ga": ga, "decided_in": decided_in,
            "final": final, "regular": regular, "in_division": in_division}


def test_a_shootout_loss_is_worth_a_point():
    rows = lowdown.table_as_of([
        {"team_id": 1, "name": "Mid Ice Crisis", "is_us": True,
         "games": [_game("2026-10-18", "L", 2, 3, decided_in="SO")]},
    ], TODAY)
    assert rows[0]["pts"] == 1


def test_an_overtime_win_is_worth_two_like_any_win():
    rows = lowdown.table_as_of([
        {"team_id": 1, "name": "A", "games": [_game("2026-10-18", "W", 4, 3, decided_in="OT")]},
        {"team_id": 2, "name": "B", "games": [_game("2026-10-18", "W", 4, 3)]},
    ], TODAY)
    assert [r["pts"] for r in rows] == [2, 2]


def test_the_cutoff_excludes_later_games_so_the_week_start_is_the_week_start():
    team = {"team_id": 1, "name": "A", "games": [
        _game("2026-10-14", "W", 5, 1),
        _game("2026-10-21", "W", 8, 1),
    ]}
    assert lowdown.table_as_of([team], "2026-10-15")[0]["pts"] == 2
    assert lowdown.table_as_of([team], TODAY)[0]["pts"] == 4


def test_playoff_unfinished_and_cross_division_games_are_left_out():
    team = {"team_id": 1, "name": "A", "games": [
        _game("2026-10-01", "W", 5, 1, regular=False),
        _game("2026-10-02", "W", 5, 1, final=False),
        _game("2026-10-03", "W", 5, 1, in_division=False),
    ]}
    assert lowdown.table_as_of([team], TODAY)[0]["gp"] == 0


def test_regulation_wins_break_a_tie_ahead_of_differential():
    """The dashboard's ordering: a team on more regulation wins is placed ahead even with the worse
    goal differential. Shared with build_standings via rank_key, so the standings table and the
    movers strip cannot disagree."""
    rows = lowdown.table_as_of([
        {"team_id": 1, "name": "TwoRegWins", "games": [
            _game("2026-10-01", "W", 3, 2), _game("2026-10-08", "W", 3, 2),
            _game("2026-10-15", "L", 0, 1)]},
        {"team_id": 2, "name": "OneRegWinBigDiff", "games": [
            _game("2026-10-01", "W", 9, 1), _game("2026-10-08", "W", 3, 2, decided_in="OT"),
            _game("2026-10-15", "L", 0, 1)]},
    ], TODAY)
    assert [r["pts"] for r in rows] == [4, 4]
    assert [r["name"] for r in rows] == ["TwoRegWins", "OneRegWinBigDiff"]
    assert rows[1]["diff"] > rows[0]["diff"]


def test_differential_then_goals_for_break_a_tie_on_regulation_wins():
    rows = lowdown.table_as_of([
        {"team_id": 1, "name": "SmallDiff", "games": [_game("2026-10-01", "W", 3, 2)]},
        {"team_id": 2, "name": "BigDiff", "games": [_game("2026-10-01", "W", 9, 1)]},
        {"team_id": 3, "name": "SameDiffMoreGoals", "games": [_game("2026-10-01", "W", 4, 3)]},
    ], TODAY)
    assert [r["name"] for r in rows] == ["BigDiff", "SameDiffMoreGoals", "SmallDiff"]
    assert [r["rank"] for r in rows] == [1, 2, 3]


def test_the_replay_reproduces_the_live_division_table():
    """The contract the movers strip depends on, pinned against the real files: today's replay must
    reproduce the table the Overview shows -- every team's counters and the whole running order,
    ties included. Both sides order through `rank_key`, so this is what catches the two drifting
    apart and the strip claiming a climb past a team still shown ahead."""
    import json
    derived = ROOT / "data" / "derived"
    outlook = json.loads((derived / "outlook.json").read_text(encoding="utf-8"))
    standings = json.loads((derived / "standings.json").read_text(encoding="utf-8"))
    for season_id, block in outlook.items():
        rows = standings[season_id]["rows"]
        replayed = lowdown.table_as_of(block["teams"], "2099-01-01")
        by_name = {r["name"]: r for r in replayed}
        for official in rows:
            got = by_name.get(official["name"])
            assert got, f"season {season_id}: {official['name']} missing from the replay"
            for field in ("gp", "pts", "gf", "ga", "w"):
                assert got[field] == (official.get(field) or 0), \
                    f"season {season_id}: {official['name']} {field}"
        played = [r["name"] for r in rows if r.get("gp")]
        if len(played) < 2:
            continue
        assert [r["name"] for r in replayed if r["gp"]] == played, \
            f"season {season_id} replay disagrees with the official table"


# --- tightness --------------------------------------------------------------------------------

def _team(pts, gp, gf, ga):
    return {"pts": pts, "gp": gp, "gf": gf, "ga": ga}


def test_a_level_division_has_a_smaller_spread_than_a_lopsided_one():
    level = lowdown.tightness([_team(4, 4, 12, 12) for _ in range(5)])
    lopsided = lowdown.tightness([_team(8, 4, 30, 4), _team(6, 4, 20, 10), _team(4, 4, 12, 12),
                                  _team(2, 4, 8, 20), _team(0, 4, 4, 30)])
    assert level["ppg_spread"] == 0.0
    assert lopsided["ppg_spread"] > level["ppg_spread"]
    assert lopsided["mean_abs_diff"] > level["mean_abs_diff"]


def test_teams_short_of_the_games_floor_are_excluded_from_the_spread():
    t = lowdown.tightness([_team(4, 4, 12, 12), _team(4, 4, 12, 12), _team(4, 4, 12, 12),
                           _team(4, 4, 12, 12), _team(2, 1, 9, 1)])
    assert t["teams"] == 4
    assert t["ppg_spread"] == 0.0  # the 1-game outlier would otherwise dominate it


def test_a_division_too_small_or_too_early_is_not_ranked():
    assert lowdown.tightness([_team(4, 4, 12, 12), _team(4, 4, 12, 12)]) is None
    assert lowdown.tightness([_team(2, 1, 5, 2) for _ in range(6)]) is None


def test_goals_per_game_is_per_team_per_game():
    t = lowdown.tightness([_team(4, 4, 16, 16) for _ in range(4)])
    assert t["goals_per_game"] == 4.0


# --- diff_snapshot ----------------------------------------------------------------------------

def test_no_prior_snapshot_claims_nothing():
    d = lowdown.diff_snapshot({"players": {"1": {"p": 9}}, "teams": {}}, None)
    assert d == {"teams": {}, "players": {}, "from": None}


def test_deltas_are_counter_differences():
    d = lowdown.diff_snapshot(
        {"date": "2026-10-22", "teams": {"7": {"lvl": 79, "gp": 6, "pts": 11}}, "players": {}},
        {"date": "2026-10-15", "teams": {"7": {"lvl": 79, "gp": 4, "pts": 7}}, "players": {}})
    assert d["teams"]["7"]["pts"] == 4
    assert d["teams"]["7"]["gp"] == 2
    assert d["from"] == "2026-10-15"
    assert "lvl" not in d["teams"]["7"]  # a division id is not a counter


class FakeLeagueContext:
    """Stands in for LeagueContext: _lowdown_snapshot reads only these two indexes."""

    def __init__(self, standings, populations):
        self.standings = standings
        self.populations = populations
        self.league_labels = {4: "BH Adult"}


def test_the_snapshot_cut_is_the_same_whatever_order_the_scrape_wrote_the_rows():
    """The bug this guards: the cap was a plain row count over a points-only sort, which is a
    stable sort over scrape order. 13 players tie on 2 points at the 25th place in Adult C3 Lower,
    so which of them landed inside the cap flipped between two scrapes of the same day -- and next
    week that reads as the player having been absent, which silently drops a real gainer note."""
    import random
    import build_site_data as b
    rows = [{"player_id": 1000 + i, "name": f"P{i}", "gp": 3, "goals": 1, "assists": 1,
             "pts": 2, "hat": 0} for i in range(40)]
    rows += [{"player_id": 2000 + i, "name": f"Q{i}", "gp": 3, "goals": 5, "assists": 5,
              "pts": 10, "hat": 1} for i in range(10)]
    first = None
    for seed in range(6):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        ctx = FakeLeagueContext({(4, 19): []}, {(4, 19, 15): shuffled})
        got = set(b._lowdown_snapshot(ctx, 4, 19, "2026-10-22")["players"])
        if first is None:
            first = got
        assert got == first, f"seed {seed} produced a different set of players"
    # Everyone level with the last player kept is in, so nobody is cut arbitrarily: the 10 on 10
    # points plus all 40 tied on 2, not an arbitrary 15 of those 40.
    assert len(first) == 50


def test_the_comparison_snapshot_must_be_about_a_week_old():
    """Which stored snapshot the league card diffs against. Comparing with yesterday would call a
    real week empty; comparing with opening night would call it a blowout. So the window is
    5-10 days, and outside it the card says nothing rather than something wrong."""
    import build_site_data as b
    import json, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for day in ("2026-10-21", "2026-10-16", "2026-10-14", "2026-09-30"):
            (d / f"{day}.json").write_text(json.dumps({"date": day}), encoding="utf-8")
        # Oct 21 is too new, Sep 30 too old; of the two in range the newer wins.
        assert b._prior_snapshot(d, "2026-10-22")["date"] == "2026-10-16"
        # Nothing in range at all -> None, so the notes are omitted instead of being wrong.
        assert b._prior_snapshot(d, "2026-12-01") is None
        assert b._prior_snapshot(d / "nope", "2026-10-22") is None
        # A stray non-date filename must not crash the pick.
        (d / "latest.json").write_text("{}", encoding="utf-8")
        assert b._prior_snapshot(d, "2026-10-22")["date"] == "2026-10-16"


def test_a_player_missing_last_week_is_flagged_rather_than_credited_with_the_season():
    d = lowdown.diff_snapshot(
        {"players": {"1": {"p": 12}, "2": {"p": 5}}, "teams": {}},
        {"date": "2026-10-15", "players": {"1": {"p": 8}}, "teams": {}})
    assert d["players"]["1"] == {"was_absent": False, "p": 4}
    assert d["players"]["2"]["was_absent"] is True
    assert d["players"]["2"]["p"] == 5  # the number is there, but the flag says not to trust it
