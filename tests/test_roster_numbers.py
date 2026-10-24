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


def _season(league_index: dict | None = None):
    """A SeasonData without its scrape -- only the name resolution these tests exercise."""
    season = bsd.SeasonData.__new__(bsd.SeasonData)
    season.league_name_to_player_id = league_index or {}
    return season


def test_on_ice_token_resolves_by_number_or_name():
    season = _season()
    name_map = {p["name"]: i for i, p in enumerate(ROSTER)}
    assert bsd.resolve_on_ice(season, 9, ROSTER, name_map) == name_map["Alex May"]
    assert bsd.resolve_on_ice(season, 1, ROSTER, name_map) == name_map["Shane Meyer"]
    assert bsd.resolve_on_ice(season, 47, ROSTER, name_map) is None  # ambiguous by number...
    assert bsd.resolve_on_ice(season, "James Roig", ROSTER, name_map) == name_map["James Roig"]  # ...fine by name
    assert bsd.resolve_on_ice(season, "Josh Schuldiner", ROSTER, name_map) == name_map["Josh Schuldiner"]


def test_a_sub_resolves_through_the_league_index():
    """The point of adding a missing skater: a sub is on no team page of ours, so only the
    league-wide index can name them -- otherwise the tag counts for nobody."""
    roster = [*ROSTER, {"number": 7, "position": None, "name": "Dominic Rosalez"}]
    season = _season({"Dominic Rosalez": 4242})
    assert bsd.resolve_on_ice(season, 7, roster, {}) == 4242
    assert bsd.resolve_on_ice(season, "Dominic Rosalez", roster, {}) == 4242
    assert bsd.resolve_on_ice(season, 7, roster, {"Dominic Rosalez": 11}) == 11  # team page wins
    assert bsd.resolve_on_ice(_season(), 7, roster, {}) is None  # unknown to the league: still nobody


def test_issue_form_skaters_accept_names():
    assert onice.parse_skaters("9, #1, James Roig, Josh Schuldiner") == [1, 9, "James Roig", "Josh Schuldiner"]


def test_credited_name_takes_a_number_or_an_already_resolved_name():
    """A goal field is the number the scorekeeper wrote, unless a correction had to name the
    player because two of them wore it."""
    unique, _ = bsd.roster_index(ROSTER)
    assert bsd.credited_name(9, unique) == "Alex May"
    assert bsd.credited_name(47, unique) is None  # shared: the number names nobody
    assert bsd.credited_name("James Roig", unique) == "James Roig"
    assert bsd.credited_name(None, unique) is None


def test_a_sub_added_on_a_taken_number_is_tagged_by_name_and_leaves_the_number_alone():
    """The whole point of keeping the clash off the join key: #9 still credits Alex May."""
    roster = [*ROSTER, {"number": None, "wore": 9, "position": None, "name": "Sub Mcsubface"}]
    unique, shared = bsd.roster_index(roster)
    assert unique[9] == "Alex May"
    assert 9 not in shared
    season = _season({"Sub Mcsubface": 5150})
    assert bsd.resolve_on_ice(season, "Sub Mcsubface", roster, {}) == 5150
    assert bsd.credited_name("Sub Mcsubface", unique) == "Sub Mcsubface"
