#!/usr/bin/env python3
"""Mirror data/derived/ into docs/data/, the exact equivalent of what the workflows run:

    rsync -a --delete --exclude traffic.json data/derived/ docs/data/

    python scripts/sync_docs_data.py            # mirror
    python scripts/sync_docs_data.py --dry-run  # list what would be copied and deleted

This exists because rsync is not on the Windows laptop and `cp -a data/derived/. docs/data/` is
not a mirror -- it copies and never deletes. The difference is invisible until the derived set
*shrinks*, and then it is silent and published: in the sibling repo, correcting a reused team id
took the player index from 265 rows to 112, and 153 spotlight files for players from a division
that team had never played in stayed in docs/data/players, served and linkable, with nothing in
the build to notice.

traffic.json is excluded because it is written into docs/data by the traffic workflow, not by the
build, so a mirror would delete it on every run.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "derived"
DST = ROOT / "docs" / "data"
KEEP = {"traffic.json"}  # owned by the traffic workflow, not by the build


def relative_files(base: Path) -> set[Path]:
    return {p.relative_to(base) for p in base.rglob("*") if p.is_file()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report the plan without touching anything")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"{SRC} not found -- run scripts/build_site_data.py first")
        return 1
    DST.mkdir(parents=True, exist_ok=True)

    src_files = relative_files(SRC)
    dst_files = relative_files(DST)
    stale = sorted(p for p in dst_files - src_files if p.name not in KEEP)
    copied = 0

    for rel in sorted(src_files):
        s, d = SRC / rel, DST / rel
        if d.exists() and filecmp.cmp(s, d, shallow=False):
            continue
        copied += 1
        if not args.dry_run:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)

    for rel in stale:
        if not args.dry_run:
            (DST / rel).unlink()

    verb = "would copy" if args.dry_run else "copied"
    gone = "would delete" if args.dry_run else "deleted"
    print(f"{verb} {copied} file(s), {gone} {len(stale)} stale file(s); "
          f"docs/data now mirrors {len(src_files)} file(s)")
    for rel in stale[:10]:
        print(f"   - {rel.as_posix()}")
    if len(stale) > 10:
        print(f"   ... and {len(stale) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
