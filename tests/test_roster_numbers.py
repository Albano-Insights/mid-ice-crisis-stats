"""Blank and shared jersey numbers on a scoresheet roster: every listed player still dresses for
the game, a number a skater shares with the goalie slot still credits the skater, and a number two
skaters share credits nobody rather than whichever name came last.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site_data as bsd  # noqa: E402
import process_on_ice_issue as onice  # noqa: E402

ROSTER = [
    {"number": 1, "position": "G", "name": "ALT Goalie"},
    {"number": 1, "position": None, "name": "Shane Meyer"},
    {"number": 47, "position": None, "name": "Christopher Kane"},
    {"number": 47, "position": None, "name": "James Roig"},
    {"number": 9, "position": None, "name": "Alex May"},
    {"number": None, "position": None, "name": "Josh Schuldiner"},
]


def test_roster_index_resolves_goalie_share_and_flags_skater_share():
    unique, shared = bsd.roster_index(ROSTER)
    assert unique == {1: "Shane Meyer", 9: "Alex May"}
    assert shared == {47: ["Christopher Kane", "James Roig"]}
    assert None not in unique  # a goal with no scorer must never match the blank-number player


def test_on_ice_token_resolves_by_number_or_name():
    name_map = {p["name"]: i for i, p in enumerate(ROSTER)}
    assert bsd.resolve_on_ice(9, ROSTER, name_map) == name_map["Alex May"]
    assert bsd.resolve_on_ice(1, ROSTER, name_map) == name_map["Shane Meyer"]
    assert bsd.resolve_on_ice(47, ROSTER, name_map) is None  # ambiguous by number...
    assert bsd.resolve_on_ice("James Roig", ROSTER, name_map) == name_map["James Roig"]  # ...fine by name
    assert bsd.resolve_on_ice("Josh Schuldiner", ROSTER, name_map) == name_map["Josh Schuldiner"]


def test_issue_form_skaters_accept_names():
    assert onice.parse_skaters("9, #1, James Roig, Josh Schuldiner") == [1, 9, "James Roig", "Josh Schuldiner"]
