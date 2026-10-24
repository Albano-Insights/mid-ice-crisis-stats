"""The game write-up: three lines, regenerated from the scoresheet on every build, so they have to
be deterministic and they have to describe the game they were built from.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site_data as bsd  # noqa: E402


def _box(game_id: int, our_goals: list[tuple[str, str, int]], their_goals: list[tuple[str, str]], **kw) -> dict:
    """our_goals: (period, time, scorer_number). their_goals: (period, time)."""
    goals = [{"team": "home", "period": p, "time": t, "scorer_number": n,
              "assist1_number": None, "assist2_number": None, "situation": None} for p, t, n in our_goals]
    goals += [{"team": "away", "period": p, "time": t, "scorer_number": 99,
               "assist1_number": None, "assist2_number": None, "situation": None} for p, t in their_goals]
    return {
        "game_id": game_id, "home_name": "Mid Ice Crisis", "away_name": "Puckaneers",
        "home_final": len(our_goals), "away_final": len(their_goals), "rink": "Rink 1", "date": "Wed Oct 21",
        "rosters": {
            "Mid Ice Crisis": [{"number": 9, "position": None, "name": "Alex Albano"},
                               {"number": 21, "position": None, "name": "Matthew Killeen"},
                               {"number": 30, "position": "G", "name": "Brad Parker"}],
            "Puckaneers": [{"number": 99, "position": None, "name": "Their Guy"}],
        },
        "goals": goals, "penalties": {"home": [], "away": []}, **kw,
    }


def _recap(box, **kw):
    return bsd.build_recap(box, "Mid Ice Crisis", kw.pop("record_after", None), kw.pop("h2h_after", None),
                           kw.pop("streak_after", None), **kw)


def test_three_lines_that_never_replay_the_goals():
    r = _recap(_box(1, [("1", "10:00", 9), ("2", "5:00", 21), ("2", "1:00", 9)], [("3", "4:00")]))
    assert len(r["paragraphs"]) == 3
    # The goals are listed under the card with their own film links; prose that repeats them is
    # what this format exists to get rid of.
    assert "10:00" not in " ".join(r["paragraphs"])
    assert "Alex Albano (2) and Matthew Killeen scored." in r["paragraphs"][1]


def test_the_same_game_reads_the_same_way_every_build():
    box = _box(7, [("1", "10:00", 9)], [("2", "4:00"), ("3", "2:00")])
    first = _recap(box)["paragraphs"]
    assert first == _recap(box)["paragraphs"]
    # ...and a different game id reaches for a different wording from the same bank.
    other = _recap(_box(8, [("1", "10:00", 9)], [("2", "4:00"), ("3", "2:00")]))["paragraphs"]
    assert first[0] != other[0]


def test_a_shutout_names_the_goalie_and_a_blowout_counts_the_run():
    shutout = _recap(_box(2, [("1", "10:00", 9), ("2", "5:00", 21)], []))
    assert "Brad Parker" in shutout["paragraphs"][0]

    rout = _recap(_box(4, [("1", f"{m}:00", 9) for m in range(10, 4, -1)], [("3", "1:00")]))
    assert "in a row" in rout["paragraphs"][0] or "straight" in rout["paragraphs"][0]


def test_a_blowout_does_not_bother_naming_a_game_winner():
    """The game-winner of a 6-1 is a first-period goal nobody remembers."""
    rout = _recap(_box(5, [("1", f"{m}:00", 9) for m in range(10, 4, -1)], [("3", "1:00")]))
    assert "the winner" not in " ".join(rout["paragraphs"])
    tight = _recap(_box(6, [("1", "10:00", 9), ("3", "2:00", 21)], [("2", "5:00")]))
    assert "Matthew Killeen had the winner" in tight["paragraphs"][1]


def test_a_blown_lead_says_so_rather_than_restating_the_score():
    r = _recap(_box(3, [("1", "10:00", 9), ("1", "8:00", 21)], [("2", "5:00"), ("3", "4:00"), ("3", "1:00")]))
    assert "Led by 2 and gave it back." in r["paragraphs"][0]
    assert "3-2" not in " ".join(r["paragraphs"])


def test_one_meeting_is_a_first_meeting_not_an_all_time_record():
    r = _recap(_box(1, [("1", "10:00", 9)], []), h2h_after={"w": 1, "l": 0, "t": 0})
    assert "First time we've played Puckaneers." in r["paragraphs"][2]
    r2 = _recap(_box(1, [("1", "10:00", 9)], []), h2h_after={"w": 3, "l": 1, "t": 0})
    assert "All-time vs Puckaneers: 3-1." in r2["paragraphs"][2]


def test_no_em_dashes_anywhere():
    """House style: the em dash is the tell that nobody wrote this."""
    for gid in range(1, 12):
        r = _recap(_box(gid, [("1", "10:00", 9)], [("2", "4:00")]), record_after={"w": 1, "l": 1, "otl": 0})
        assert "—" not in " ".join(r["paragraphs"])
