"""Surfaces data/derived/data_health.json on the Actions run page.

build_site_data.py detects division games whose result never landed; that detection is useless if
it only ever reaches the build log, which nobody reads. This writes a table into the run summary
and emits a ::warning:: annotation per stale game, so a stalled scoresheet shows up on the run
itself. It never exits non-zero: a result the league hasn't posted is their doing, not a broken
refresh, and failing here would discard a perfectly good data pull.

Usage: python scripts/report_data_health.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HEALTH_PATH = Path(__file__).parent.parent / "data" / "derived" / "data_health.json"


def summary_lines(health: dict) -> list[str]:
    rows = health.get("stale_games", [])
    after = health.get("stale_after_days", "?")
    out = ["## Division results still missing", ""]
    if not rows:
        out.append(f"None — every division game more than {after} days past its scheduled date has a posted result.")
        return out
    out += [f"A game stopped early (a fight, an injury, a forfeit) can sit unposted on the league site. "
            f"Until it lands it is missing from the standings but still counted as a game remaining "
            f"in the outlook, so these numbers are understated for both teams.", "",
            "| game | date | matchup | state | days late |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['game_id']} | {r.get('date') or r['iso_date']} | "
                   f"{r['away_name']} @ {r['home_name']} | `{r['state']}` | {r['days_late']} |")
    return out


def annotations(health: dict) -> list[str]:
    return [f"::warning title=Missing league result::game {r['game_id']} "
            f"({r['iso_date']}, {r['away_name']} @ {r['home_name']}) is {r['state']}, "
            f"{r['days_late']} days past its scheduled date"
            for r in health.get("stale_games", [])]


def main() -> None:
    if not HEALTH_PATH.exists():
        print("no data_health.json -- run scripts/build_site_data.py first")
        return
    health = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(summary_lines(health)) + "\n")
    for line in annotations(health):
        print(line)
    print(f"{len(health.get('stale_games', []))} division game(s) still missing a result")


if __name__ == "__main__":
    main()
