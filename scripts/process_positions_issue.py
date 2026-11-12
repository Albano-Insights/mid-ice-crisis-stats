"""Parses a "Positions (F/D)" GitHub Issue Form submission and applies every line of it to
data/positions.json in one pass. Run by .github/workflows/process-positions-issue.yml.

Why one issue and not one per player: positions are keyed in a sitting, from a roster sheet or
from memory, thirty-odd at a time. The other issue forms each describe a single event (one goal,
one missing skater), so one-per-change is right for them. A position is not an event -- it is a
fact about a player that someone is filling in -- so the natural unit is the whole sitting.

The league site records no positions at all (its only roster codes are C for captain and G for
goalie), so this file is the sole source for the Players tab's position filter and for ranking
defensemen against defensemen.

Body format, one assignment per line, anything after `#` ignored:

    6320 F              # Dylan Tadros
    6323 D              # Derek Dettman
    9999 -              # clears this player back to unknown
    name:Eric McAlpin D # a player the league credits to another division's team

Two kinds of key, because two kinds of player. Most are a league player id. The rest cannot be
pinned to one:

  - They dressed for us on a scoresheet but the league credits their stats elsewhere (Eric
    McAlpin is id 1061 on Underdawgs C2/C3), so the index has no row of ours for them.
  - Or their name is genuinely ambiguous: ids 7023 and 7037 are two different Perry Mayers, both
    credited to one of our teams, and nothing in the data says which one dressed.

Both are keyed by name instead. Guessing an id would silently attach a position to a stranger --
120 of 2560 names in this league map to more than one player id -- so the guess is never made. A
name-keyed entry is upgraded to an id key by the build the moment the league starts crediting
that player to us unambiguously.

Usage: python scripts/process_positions_issue.py --body-file body.txt --issue-number 42
       --author some-login
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The summary below uses arrows, which a Windows console's cp1252 cannot encode. The workflow runs
# on Ubuntu and never sees this, but running the script by hand locally would otherwise die in
# print() rather than on anything to do with the data.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
POSITIONS_PATH = ROOT / "data" / "positions.json"
INDEX_PATH = ROOT / "data" / "derived" / "players_index.json"
ROSTER_PATH = ROOT / "data" / "derived" / "our_roster.json"

VALID = {"F", "D"}
CLEAR = {"-", "—", "NONE", "NULL", ""}
# "6320 F  # Dylan Tadros" or "name:Eric McAlpin D  # 1 game" -> key, pos. The trailing comment is
# for the human reading the issue; the name in it is never trusted over the key, since the table
# that wrote it may be out of date. A name key may contain spaces, so it is matched greedily up to
# the last run of whitespace before the position token.
LINE_RE = re.compile(r"^\s*(\d+|name:.+?)\s+([A-Za-z\-—]+)\s*(?:#.*)?$")


def parse_assignments(body: str) -> tuple[dict[str, str | None], list[str]]:
    """Returns ({key: "F"|"D"|None}, [rejected line descriptions]), keys as they appear in
    positions.json: a decimal player id, or "name:<Full Name>".

    The whole issue body is scanned rather than just the Assignments section: GitHub renders a
    `render: text` textarea inside a fenced block, and hand-written issues skip the headings
    altogether. A line that does not look like an assignment is simply not one -- headings, blank
    lines and fences fall out here without needing to be special-cased.
    """
    out: dict[str, str | None] = {}
    rejected: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("```") or line.startswith("###"):
            continue
        m = LINE_RE.match(line)
        if not m:
            # Only complain about lines that look like an attempt: everything else is prose.
            if re.match(r"^\s*(\d|name:)", line):
                rejected.append(line)
            continue
        key, token = m.group(1).strip(), m.group(2).upper()
        if token in VALID:
            out[key] = token
        elif token in CLEAR:
            out[key] = None
        else:
            rejected.append(line)
    return out, rejected


def known_players() -> dict[str, str]:
    """key -> name for every key a position may be set on: league player ids from the built index,
    plus the name keys of players who have dressed for us but cannot be pinned to one id. Used to
    reject typos and to fill in the name field of a new entry, so positions.json stays readable by
    hand."""
    out: dict[str, str] = {}
    if INDEX_PATH.exists():
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        rows = data.get("players", data) if isinstance(data, dict) else data
        if isinstance(rows, list):
            rows = {str(r.get("player_id") or r.get("id")): r for r in rows}
        for pid, row in rows.items():
            if isinstance(row, dict) and str(pid).isdigit():
                out[str(pid)] = row.get("name") or row.get("player_name") or ""
    if ROSTER_PATH.exists():
        for row in json.loads(ROSTER_PATH.read_text(encoding="utf-8")):
            # A goalie is neither F nor D, so its key is deliberately not offered here: a line
            # naming one is rejected rather than silently stored.
            if isinstance(row, dict) and row.get("key") and not row.get("is_goalie"):
                out[str(row["key"])] = row.get("name") or ""
    return out


def apply(assignments: dict[str, str | None], positions: dict, known: dict[str, str]) -> tuple[dict, list[str], list[str]]:
    changed: list[str] = []
    unknown: list[str] = []
    for key, pos in assignments.items():
        if known and key not in known:
            unknown.append(key)
            continue
        entry = positions.get(key) or {"name": known.get(key, ""), "pos": None}
        if not entry.get("name"):
            entry["name"] = known.get(key, "")
        before = entry.get("pos")
        if before == pos:
            continue
        entry["pos"] = pos
        positions[key] = entry
        changed.append(f"{entry['name'] or key}: {before or '—'} → {pos or '—'}")
    return positions, changed, unknown


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--issue-number", required=True, type=int)
    ap.add_argument("--author", default="")
    ap.add_argument("--summary-file", help="write a human summary here for the issue comment")
    args = ap.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    assignments, rejected = parse_assignments(body)
    if not assignments:
        raise SystemExit(f"No assignments found. Rejected lines: {rejected}")

    positions = json.loads(POSITIONS_PATH.read_text(encoding="utf-8")) if POSITIONS_PATH.exists() else {}
    help_text = positions.pop("_help", None)
    positions, changed, unknown = apply(assignments, positions, known_players())

    ordered = {}
    if help_text:
        ordered["_help"] = help_text
    for key, row in sorted(positions.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
        ordered[key] = row
    POSITIONS_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    done = sum(1 for v in ordered.values() if isinstance(v, dict) and v.get("pos"))
    total = sum(1 for k in ordered if k != "_help")
    lines = [f"Applied **{len(changed)}** change(s) from @{args.author}." if args.author
             else f"Applied **{len(changed)}** change(s).",
             f"{done}/{total} players now have a position."]
    if changed:
        lines += ["", "<details><summary>What changed</summary>", ""] + [f"- {c}" for c in changed] + ["", "</details>"]
    if unknown:
        lines += ["", f"⚠ Skipped {len(unknown)} unknown player key(s): {unknown}"]
    if rejected:
        lines += ["", f"⚠ Skipped {len(rejected)} unparseable line(s): {rejected[:10]}"]
    summary = "\n".join(lines)
    print(summary)
    if args.summary_file:
        Path(args.summary_file).write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
