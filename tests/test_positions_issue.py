"""The positions issue form is the one intake that carries many changes at once, so the parser has
to be tolerant of how GitHub renders a textarea and strict about what it will write.

Keys are strings, not ints: most are a league player id, but a player who dressed for us while the
league credits his stats to another division's team -- or whose name maps to two player ids --
has no single id of ours, so he is keyed
`name:<Full Name>` instead. Guessing an id from a name is not an option -- 120 of 2560 names in
this league map to more than one player id."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import process_positions_issue as pp  # noqa: E402


def test_parses_the_shape_the_dashboard_writes():
    body = "### Assignments\n\n```text\n6320 F  # Dylan Tadros\n6323 D  # Derek Dettman\n```\n"
    got, rejected = pp.parse_assignments(body)
    assert got == {"6320": "F", "6323": "D"}
    assert rejected == []


def test_a_dash_clears_a_player_back_to_unknown():
    got, _ = pp.parse_assignments("9999 -  # typo'd earlier\n")
    assert got == {"9999": None}


def test_prose_and_headings_are_not_rejected_as_bad_lines():
    body = "### Assignments\n\nFrom the Nov 11 sheet.\n\n6320 F\n\n### Note\n\n_No response_\n"
    got, rejected = pp.parse_assignments(body)
    assert got == {"6320": "F"}
    assert rejected == []


def test_a_numeric_line_with_a_bad_position_is_reported_not_silently_dropped():
    got, rejected = pp.parse_assignments("6320 F\n6323 W\n")
    assert got == {"6320": "F"}
    assert rejected == ["6323 W"]


def test_lowercase_is_accepted():
    got, _ = pp.parse_assignments("6320 f\n6323 d\n")
    assert got == {"6320": "F", "6323": "D"}


def test_a_name_key_with_spaces_parses_as_one_key():
    """The whole point of the name key is players with no id, and every real name has a space in
    it, so the key cannot stop at the first one."""
    got, rejected = pp.parse_assignments("name:Eric McAlpin D  # 1 game\n")
    assert got == {"name:Eric McAlpin": "D"}
    assert rejected == []


def test_name_and_id_keys_mix_in_one_issue():
    body = "```text\n6320 F  # Dylan Tadros\nname:Perry Mayer D\nname:Mark Peck -\n```"
    got, rejected = pp.parse_assignments(body)
    assert got == {"6320": "F", "name:Perry Mayer": "D", "name:Mark Peck": None}
    assert rejected == []


def test_a_broken_name_line_is_reported_not_silently_dropped():
    got, rejected = pp.parse_assignments("name:Eric McAlpin W\n")
    assert got == {}
    assert rejected == ["name:Eric McAlpin W"]


def test_apply_reports_only_real_changes():
    positions = {"6320": {"name": "Dylan Tadros", "pos": "F"}}
    known = {"6320": "Dylan Tadros", "6323": "Derek Dettman"}
    _, changed, unknown = pp.apply({"6320": "F", "6323": "D"}, positions, known)
    assert unknown == []
    # 6320 was already F, so only 6323 counts as a change.
    assert len(changed) == 1 and "Derek Dettman" in changed[0]


def test_apply_fills_the_name_for_a_newly_keyed_player():
    positions = {}
    out, _, _ = pp.apply({"6323": "D"}, positions, {"6323": "Derek Dettman"})
    assert out["6323"] == {"name": "Derek Dettman", "pos": "D"}


def test_apply_writes_a_name_key_under_that_key():
    positions = {}
    known = {"name:Eric McAlpin": "Eric McAlpin"}
    out, changed, unknown = pp.apply({"name:Eric McAlpin": "D"}, positions, known)
    assert unknown == []
    assert out["name:Eric McAlpin"] == {"name": "Eric McAlpin", "pos": "D"}
    assert len(changed) == 1 and "Eric McAlpin" in changed[0]


def test_an_unknown_player_id_is_skipped_rather_than_written():
    positions = {}
    out, changed, unknown = pp.apply({"123456": "F"}, positions, {"6323": "Derek Dettman"})
    assert out == {} and changed == [] and unknown == ["123456"]


def test_an_unknown_name_key_is_skipped_rather_than_written():
    """A misspelled name must not create a second, parallel entry for the same person."""
    positions = {}
    known = {"name:Eric McAlpin": "Eric McAlpin"}
    out, changed, unknown = pp.apply({"name:Eric McAlpen": "D"}, positions, known)
    assert out == {} and changed == [] and unknown == ["name:Eric McAlpen"]


def test_goalies_are_not_offered_as_keyable(tmp_path, monkeypatch):
    """A goalie is neither F nor D, so its key must not be accepted at all -- otherwise the
    roster table and the parser disagree about what a valid assignment is."""
    roster = [
        {"key": "6320", "name": "Dylan Tadros", "is_goalie": False},
        {"key": "name:Brad Parker", "name": "Brad Parker", "is_goalie": True},
    ]
    path = tmp_path / "our_roster.json"
    path.write_text(json.dumps(roster), encoding="utf-8")
    monkeypatch.setattr(pp, "ROSTER_PATH", path)
    monkeypatch.setattr(pp, "INDEX_PATH", tmp_path / "missing.json")
    known = pp.known_players()
    assert "6320" in known
    assert "name:Brad Parker" not in known


def test_the_real_positions_file_round_trips_through_the_parser():
    """Every key the dashboard will emit must survive the parser unchanged."""
    positions = json.loads((ROOT / "data" / "positions.json").read_text(encoding="utf-8"))
    keys = [k for k in positions if k != "_help"]
    assert keys, "positions.json should be seeded"
    body = "\n".join(f"{k} F  # {positions[k]['name']}" for k in keys)
    got, rejected = pp.parse_assignments(body)
    assert rejected == []
    assert set(got) == set(keys)


def test_every_keyable_roster_row_is_a_key_the_parser_accepts():
    """The table writes these keys and the workflow reads them; a format either side invents on
    its own is a silent no-op, which is exactly what happened with ids before."""
    path = ROOT / "data" / "derived" / "our_roster.json"
    if not path.exists():
        pytest.skip("derived data not built")
    roster = json.loads(path.read_text(encoding="utf-8"))
    keyable = [r for r in roster if not r["is_goalie"]]
    assert keyable, "our_roster.json should list skaters"
    body = "\n".join(f"{r['key']} F  # {r['name']}" for r in keyable)
    got, rejected = pp.parse_assignments(body)
    assert rejected == []
    assert set(got) == {r["key"] for r in keyable}


# --------------------------------------------------------------------------------------------
# The coverage gate on position-narrowed ranking.
#
# Positions are keyed from memory and only for your own bench, so the division will never be
# fully covered. These pin the rule that a thin, one-team sample never gets to call itself
# "defensemen".
# --------------------------------------------------------------------------------------------
import spotlight_shim  # noqa: E402,F401  (imports lib/spotlight under a stable name)


def _population(n_d, n_f, n_unknown, ppg=0.5):
    pop, positions, pid = [], {}, 1
    for count, pos in ((n_d, "D"), (n_f, "F"), (n_unknown, None)):
        for _ in range(count):
            pop.append({"player_id": pid, "gp": 10, "pts": int(ppg * 10)})
            if pos:
                positions[pid] = pos
            pid += 1
    return pop, positions


def test_narrows_to_defensemen_when_the_division_is_well_covered():
    from lib import spotlight as sp
    pop, positions = _population(n_d=6, n_f=6, n_unknown=0)
    got = sp.percentile_in_division(0.5, pop, "D", positions)
    assert got["peers"] == "defensemen"
    assert got["of"] == 6


def test_stays_on_all_skaters_when_only_one_team_is_keyed():
    """Coverage here is one team's bench against a hundred-skater division, which is all you can
    ever key from memory; it must not narrow."""
    from lib import spotlight as sp
    pop, positions = _population(n_d=6, n_f=11, n_unknown=83)
    got = sp.percentile_in_division(0.5, pop, "D", positions)
    assert got["peers"] == "all skaters"
    assert got["of"] == 100


def test_a_tiny_same_position_group_never_narrows_even_at_full_coverage():
    from lib import spotlight as sp
    pop, positions = _population(n_d=4, n_f=20, n_unknown=0)
    got = sp.percentile_in_division(0.5, pop, "D", positions)
    assert got["peers"] == "all skaters"
