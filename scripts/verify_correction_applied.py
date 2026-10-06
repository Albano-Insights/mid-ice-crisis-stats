"""Exits non-zero if the correction from a given issue was recorded but not applied.

build_site_data.py applies corrections on top of the scraped box score; one it can't apply lands in
`_correction_errors` on the game instead (see lib/corrections.py) and the build still succeeds. That
left the workflow commenting "Applied to the dashboard" on corrections that were never applied --
issues #57, #111 and #124 all got that comment while the dashboard kept the old number.

Usage: python scripts/verify_correction_applied.py --issue-number 124
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
GAMES_DIR = ROOT / "data" / "derived" / "games"


def rejected_for(issue_number: int) -> list[tuple[int, dict]]:
    """Every (game_id, error) the build recorded for this issue."""
    found = []
    for path in sorted(GAMES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            game = json.load(f)
        for err in game.get("_correction_errors", []):
            if err.get("source_issue") == issue_number:
                found.append((game.get("game_id"), err))
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", required=True, type=int)
    args = parser.parse_args()

    rejected = rejected_for(args.issue_number)
    if not rejected:
        print(f"correction from issue #{args.issue_number} applied cleanly")
        return

    for game_id, err in rejected:
        print(f"game {game_id}: {err.get('team')} P{err.get('period')} {err.get('time')} "
              f"{err.get('field')} -> {err.get('corrected')!r}: {err.get('error')}")
    raise SystemExit(f"correction from issue #{args.issue_number} was NOT applied")


if __name__ == "__main__":
    main()
