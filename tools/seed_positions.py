#!/usr/bin/env python3
"""Seed data/positions.json from the roster, so the one hand-maintained file in the repo starts as
a checklist instead of a blank page.

    python tools/seed_positions.py            # add anyone missing, print what still needs a pos
    python tools/seed_positions.py --all      # seed every player in the division, opponents too

The league site records no positions at all, which is why this file exists: the Players tab ranks
defensemen against defensemen, and production-based grades are only a fair comparison within a
position. Until a player has "F" or "D" here they are simply unranked by position -- not wrong,
just absent from that filter.

The default population is `data/derived/our_roster.json` -- everyone who has dressed for us, read
off the scoresheets -- rather than the players index. The index is a different set, "skaters the
league credits to a team in our division", and on this roster it was short by nine: a league-wide
placeholder slot standing in for the goalie, and eight real skaters who cannot be pinned to a
single id, either because the league credits their stats to another division's team or because
their name maps to two different player ids. Entries are keyed by league player id where there is
one and by `name:<Full Name>` where there is not; goalies are skipped, since a goalie is neither
F nor D.

Existing entries are never overwritten, so this is safe to re-run after a roster change; it only
appends newcomers and reports the ones still set to null.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSITIONS = ROOT / "data" / "positions.json"
ROSTER = ROOT / "data" / "derived" / "our_roster.json"
INDEX = ROOT / "data" / "derived" / "players_index.json"

HELP = ('Hand-maintained: the league site records no positions. pos is "F" or "D" (null = unknown). '
        'Keys are a league player id, or "name:<Full Name>" for someone who dressed for us but '
        'cannot be pinned to one id -- the league credits their stats to another division\'s '
        'team, or the name maps to two different player ids. '
        'Applied by scripts/build_site_data.py; never overwritten by the scraper. '
        'Seed new names with: python tools/seed_positions.py')


def candidates(seed_all: bool) -> list[tuple[str, str]]:
    """[(key, name)] to offer a position for, most-played first."""
    if seed_all:
        if not INDEX.exists():
            print(f"{INDEX} not found -- run scripts/build_site_data.py first", file=sys.stderr)
            return []
        rows = json.loads(INDEX.read_text(encoding="utf-8"))
        rows.sort(key=lambda r: (-(r.get("gp") or 0), (r.get("name") or "").lower()))
        return [(str(r["player_id"]), r.get("name") or "") for r in rows if r.get("player_id") is not None]

    if not ROSTER.exists():
        print(f"{ROSTER} not found -- run scripts/build_site_data.py first", file=sys.stderr)
        return []
    # Already sorted by the build (goalies last, then games descending).
    return [(r["key"], r["name"]) for r in json.loads(ROSTER.read_text(encoding="utf-8"))
            if not r.get("is_goalie")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="seed every player in the index, not just the people who have played for us")
    args = ap.parse_args()

    rows = candidates(args.all)
    if not rows:
        return 1

    existing = json.loads(POSITIONS.read_text(encoding="utf-8")) if POSITIONS.exists() else {}
    existing["_help"] = HELP

    added = 0
    for key, name in rows:
        if key in existing:
            continue
        existing[key] = {"name": name, "pos": None}
        added += 1

    ordered = {"_help": existing.pop("_help")}
    for key, row in sorted(existing.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
        ordered[key] = row
    POSITIONS.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    unknown = [(k, r["name"]) for k, r in ordered.items() if k != "_help" and r.get("pos") is None]
    print(f"{POSITIONS.relative_to(ROOT)}: {added} added, {len(ordered) - 1} total, "
          f"{len(unknown)} still need a position")
    for key, name in unknown:
        print(f"   {key:>24}  {name}")
    if unknown:
        print('\nSet each to "F" or "D" by hand, or use the "Set positions" table on the '
              "dashboard's Players tab, which opens one pre-filled issue for the whole sitting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
