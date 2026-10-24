"""The "Missing skater" issue path: a sub the scoresheet left off becomes a `roster_add`
correction, and a submission that would make the data worse is refused on the issue rather than
written and silently dropped by the build.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import process_roster_add_issue as ra  # noqa: E402
from lib import corrections as corr  # noqa: E402

BODY = """### Game ID

8908

### Which team they played for

Mid Ice Crisis

### Home team (pre-filled)

Mid Ice Crisis

### Away team (pre-filled)

Broward Barracudas

### Player name

Dominic Rosalez

### Jersey number

7

### Position (optional)

_No response_

### Reason (optional)

Subbed in, scorekeeper never wrote him on the sheet.
"""

BOX = {
    "home_name": "Mid Ice Crisis",
    "away_name": "Broward Barracudas",
    "rosters": {
        "Mid Ice Crisis": [{"number": 11, "position": None, "name": "Jared Chase"}],
        "Broward Barracudas": [{"number": 43, "position": "C", "name": "Shawn Cash"}],
    },
    "goals": [],
}


def test_parses_a_filled_in_form():
    fields = ra.parse_issue_body(BODY)
    assert fields["game_id"] == "8908"
    assert fields["name"] == "Dominic Rosalez"
    assert fields["position"] is None  # "_No response_" is not a position
    assert ra.team_side(fields, BOX) == "home"
    assert ra.parse_number(fields["number"]) == 7


def test_builds_a_roster_add_the_overlay_accepts():
    fields = ra.parse_issue_body(BODY)
    c = ra.build_correction(fields, "home", 7, 42, "someone", "2026-10-23T00:00:00Z")
    assert c["kind"] == "roster_add"
    out = corr.apply_corrections(BOX, [c])
    added = [p for p in out["rosters"]["Mid Ice Crisis"] if p["name"] == "Dominic Rosalez"]
    assert added and added[0]["number"] == 7
    assert "_correction_errors" not in out


def test_no_number_is_allowed_and_tagged_by_name():
    assert ra.parse_number("") is None
    assert ra.parse_number(None) is None
    assert ra.parse_number("#23") == 23
    with pytest.raises(ValueError):
        ra.parse_number("seven")


def test_unknown_team_is_refused():
    fields = {**ra.parse_issue_body(BODY), "team_name": "Rink Ratz D1"}
    with pytest.raises(ValueError, match="neither"):
        ra.team_side(fields, BOX)


def test_a_number_already_worn_is_kept_off_the_sheets_join_key():
    """A sub brings their own jersey, so a clash with someone already on the sheet is ordinary.
    The number has to go on naming one player -- sharing it would credit every goal written
    against it to nobody, the player already on the sheet included -- so the sub keeps it as
    `wore` and is reached by name."""
    note = ra.check_against_sheet(BOX, "home", "Someone Else", 11)
    assert note and "Jared Chase" in note and "by name" in note

    c = ra.build_correction({"name": "Someone Else"}, "home", 11, 7, "someone", "2026-10-24T00:00:00Z")
    out = corr.apply_corrections(BOX, [c])
    added = next(p for p in out["rosters"]["Mid Ice Crisis"] if p["name"] == "Someone Else")
    assert (added["number"], added["wore"]) == (None, 11)
    assert [p for p in out["rosters"]["Mid Ice Crisis"] if p["number"] == 11] == [
        {"number": 11, "position": None, "name": "Jared Chase"}]
    assert "_correction_errors" not in out


def test_a_free_number_stays_the_join_key():
    c = ra.build_correction({"name": "Someone Else"}, "home", 77, 7, "someone", "2026-10-24T00:00:00Z")
    out = corr.apply_corrections(BOX, [c])
    added = next(p for p in out["rosters"]["Mid Ice Crisis"] if p["name"] == "Someone Else")
    assert (added["number"], added["wore"]) == (77, None)


def test_someone_already_on_the_sheet_is_refused():
    with pytest.raises(ValueError, match="already on"):
        ra.check_against_sheet(BOX, "away", "shawn  cash", None)


def test_without_the_scrape_the_form_names_the_sides():
    fields = ra.parse_issue_body(BODY)
    assert ra.team_side(fields, None) == "home"
    ra.check_against_sheet(None, "home", "Dominic Rosalez", 11)  # nothing to check against
