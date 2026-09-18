"""Correction overlay tests: goal-field corrections and roster corrections must apply cleanly,
annotate what changed, and refuse to apply when the scraped value no longer matches.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lib import corrections as corr  # noqa: E402


def _box() -> dict:
    return {
        "home_name": "Mid Ice Crisis",
        "away_name": "Puckaneers",
        "rosters": {
            "Mid Ice Crisis": [
                {"number": 1, "position": "G", "name": "ALT Goalie"},
                {"number": 21, "position": None, "name": "Matthew Killeen"},
            ],
            "Puckaneers": [{"number": 40, "position": None, "name": "Alex Maxwell"}],
        },
        "goals": [
            {"team": "home", "period": "2", "time": "10:05", "scorer_number": 21,
             "assist1_number": None, "assist2_number": None, "situation": "PP"},
        ],
    }


def test_goal_correction_applies_and_annotates():
    out = corr.apply_corrections(_box(), [{
        "team": "home", "period": "2", "time": "10:05", "field": "assist1_number",
        "original": None, "corrected": 71, "reason": "Shortreed had the pass",
    }])
    goal = out["goals"][0]
    assert goal["assist1_number"] == 71
    assert goal["_corrections"]["assist1_number"]["original"] is None
    assert "_correction_errors" not in out


def test_roster_correction_names_the_alt_goalie():
    out = corr.apply_corrections(_box(), [{
        "kind": "roster", "team": "home", "number": 1, "field": "name",
        "original": "ALT Goalie", "corrected": "Brad Parker", "reason": "Brad was in net",
    }])
    goalie = next(p for p in out["rosters"]["Mid Ice Crisis"] if p["number"] == 1)
    assert goalie["name"] == "Brad Parker"
    assert goalie["position"] == "G"
    assert goalie["_corrections"]["name"]["original"] == "ALT Goalie"
    assert "_correction_errors" not in out


def test_roster_correction_refuses_stale_original():
    out = corr.apply_corrections(_box(), [{
        "kind": "roster", "team": "home", "number": 1, "field": "name",
        "original": "Someone Else", "corrected": "Brad Parker",
    }])
    goalie = next(p for p in out["rosters"]["Mid Ice Crisis"] if p["number"] == 1)
    assert goalie["name"] == "ALT Goalie"
    assert out["_correction_errors"][0]["error"].startswith("expected original")


def test_roster_correction_unknown_number_is_reported_not_fatal():
    out = corr.apply_corrections(_box(), [{
        "kind": "roster", "team": "away", "number": 99, "field": "name",
        "original": "x", "corrected": "y",
    }])
    assert out["_correction_errors"][0]["error"].startswith("no matching roster entry")


def test_input_box_is_not_mutated():
    box = _box()
    corr.apply_corrections(box, [{
        "kind": "roster", "team": "home", "number": 1, "field": "name",
        "original": "ALT Goalie", "corrected": "Brad Parker",
    }])
    assert box["rosters"]["Mid Ice Crisis"][0]["name"] == "ALT Goalie"
