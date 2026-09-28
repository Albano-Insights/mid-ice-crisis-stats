"""Caching rules for per-season tables.

The scraper probes several seasons past the newest one we know about, so it can fetch a season's
standings before any game has been played and then cache that empty table forever. That is what
froze season 19 at "NO RECORD YET" for every team while the schedule showed results.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import scrape  # noqa: E402


def test_empty_table_is_unplayed():
    assert scrape._unplayed([])


def test_all_null_records_is_unplayed():
    rows = [{"name": "PB Hooker$ D", "gp": None, "w": None, "l": None, "pts": None},
            {"name": "Mid Ice Crisis", "gp": None, "w": None, "l": None, "pts": None}]
    assert scrape._unplayed(rows)


def test_all_zero_records_is_unplayed():
    # the site also serves a zeroed table between the schedule going up and the first game
    rows = [{"name": "A", "gp": 0, "pts": 0}, {"name": "B", "gp": 0, "pts": 0}]
    assert scrape._unplayed(rows)


def test_a_started_season_is_not_unplayed():
    rows = [{"name": "PB Hooker$ D", "gp": 2, "w": 2, "l": 0, "pts": 4},
            {"name": "Rink Ratz D1", "gp": 0, "w": 0, "l": 0, "pts": 0}]
    assert not scrape._unplayed(rows)


def test_one_played_team_is_enough():
    rows = [{"gp": None}, {"gp": None}, {"gp": 1}]
    assert not scrape._unplayed(rows)
