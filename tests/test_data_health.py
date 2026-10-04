"""Stale-result detection: a division game whose date has passed but whose result never landed
must be flagged, because nothing else on the site notices. build_division_recaps silently skips a
game with no box score and build_outlook treats `is_final` with no goals as not-final, so a game
stopped early -- a fight, an injury, a forfeit -- drops out of the standings while still counting
as remaining in the projections.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site_data as b  # noqa: E402


class FakeSeason:
    """Stands in for SeasonData: build_data_health only needs these four members."""

    def __init__(self, games, boxscores=()):
        self.season_id = 19
        self.team_name_by_id = {1: "Night Raiders", 2: "Puckaneers"}
        self.division_team_pages = {1: {"games": games}}
        self._boxscores = set(boxscores)

    def load_corrected_boxscore(self, game_id):
        return {"home_final": 3, "away_final": 4} if game_id in self._boxscores else None


def _game(game_id, days_ago, *, is_final, hg=None, ag=None, home="Night Raiders", away="Puckaneers"):
    return {
        "game_id": game_id,
        "iso_date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "date": "Sat Oct 3", "time": "10:45 PM", "rink": "Baptist Health Iceplex Rink 2",
        "game_type": "Regular 2", "home_name": home, "away_name": away,
        "is_final": is_final, "home_goals": hg, "away_goals": ag,
    }


def _states(games, boxscores=()):
    rows = b.build_data_health([FakeSeason(games, boxscores)])["stale_games"]
    return {r["game_id"]: r["state"] for r in rows}


def test_unposted_result_past_the_grace_period_is_flagged():
    assert _states([_game(8821, 10, is_final=False)]) == {8821: "awaiting_result"}


def test_recent_game_is_not_flagged_yet():
    """The league is normally same-day but gets a few days' grace, so last night is not an alarm."""
    assert _states([_game(8821, 1, is_final=False)]) == {}
    assert _states([_game(8821, b.STALE_AFTER_DAYS, is_final=False)]) == {}


def test_future_game_is_never_flagged():
    assert _states([_game(9048, -30, is_final=False)]) == {}


def test_final_with_no_score_is_flagged():
    """The fight-shortened case: the league marks it played but posts no goals. build_outlook
    treats this as not-final, so the game would vanish from the standings without a word."""
    assert _states([_game(8821, 10, is_final=True)]) == {8821: "final_without_score"}


def test_final_with_score_but_no_boxscore_is_flagged():
    assert _states([_game(8821, 10, is_final=True, hg=3, ag=4)]) == {8821: "final_without_boxscore"}


def test_properly_posted_game_is_clean():
    assert _states([_game(8821, 10, is_final=True, hg=3, ag=4)], boxscores={8821}) == {}


def test_a_game_on_both_teams_pages_is_reported_once():
    season = FakeSeason([_game(8821, 10, is_final=False)])
    season.division_team_pages[2] = {"games": [_game(8821, 10, is_final=False)]}
    rows = b.build_data_health([season])["stale_games"]
    assert [r["game_id"] for r in rows] == [8821]


def test_missing_or_bad_date_is_skipped_not_crashed():
    bad = _game(8821, 10, is_final=False)
    bad["iso_date"] = None
    worse = _game(8822, 10, is_final=False)
    worse["iso_date"] = "not-a-date"
    assert _states([bad, worse]) == {}


def test_in_division_flag_distinguishes_a_cross_division_opponent():
    rows = b.build_data_health([FakeSeason([
        _game(8821, 10, is_final=False),
        _game(8822, 10, is_final=False, away="Some Other Level Team"),
    ])])["stale_games"]
    assert {r["game_id"]: r["in_division"] for r in rows} == {8821: True, 8822: False}


def test_report_carries_the_threshold_and_is_date_sorted():
    out = b.build_data_health([FakeSeason([
        _game(8830, 5, is_final=False),
        _game(8821, 40, is_final=False),
    ])])
    assert out["stale_after_days"] == b.STALE_AFTER_DAYS
    assert [r["game_id"] for r in out["stale_games"]] == [8821, 8830]
    assert out["stale_games"][0]["days_late"] == 40


# --- the Actions reporter -------------------------------------------------------------------

import report_data_health as rdh  # noqa: E402


def _health(*rows):
    return {"generated_at": "2026-10-04T13:00+00:00", "stale_after_days": 3, "stale_games": list(rows)}


_ROW = {"game_id": 8821, "iso_date": "2026-10-03", "date": "Sat Oct 3", "days_late": 10,
        "away_name": "Puckaneers", "home_name": "Night Raiders", "state": "awaiting_result"}


def test_clean_report_says_so_rather_than_printing_an_empty_table():
    lines = rdh.summary_lines(_health())
    assert "None" in "\n".join(lines)
    assert "|" not in "\n".join(lines)
    assert rdh.annotations(_health()) == []


def test_stale_report_renders_a_row_per_game():
    lines = rdh.summary_lines(_health(_ROW))
    body = "\n".join(lines)
    assert "| 8821 | Sat Oct 3 | Puckaneers @ Night Raiders | `awaiting_result` | 10 |" in body
    assert body.count("\n|") >= 3  # header, separator, one data row


def test_each_stale_game_gets_one_actions_warning():
    notes = rdh.annotations(_health(_ROW, {**_ROW, "game_id": 8822}))
    assert len(notes) == 2
    assert all(n.startswith("::warning title=Missing league result::") for n in notes)
    assert "game 8821" in notes[0] and "10 days past" in notes[0]


def test_report_survives_a_health_file_with_no_optional_fields():
    """Never let the reporter be the thing that breaks the refresh."""
    assert rdh.summary_lines({}) and rdh.annotations({}) == []
