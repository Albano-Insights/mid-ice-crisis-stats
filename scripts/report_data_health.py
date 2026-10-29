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
PLAYER_HEALTH_PATH = Path(__file__).parent.parent / "data" / "raw" / "player_health.json"


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


def player_summary_lines(health: dict) -> list[str]:
    degraded = health.get("degraded", [])
    attempted = health.get("attempted", 0)
    out = ["## Player career pages", ""]
    if not degraded:
        out.append(f"All {attempted} career page(s) the refresh needed were served.")
        return out
    cached = health.get("served_from_cache", 0)
    missing = health.get("missing", 0)
    out += [f"The league site refused {len(degraded)} of {attempted} career page(s). "
            f"{cached} fell back to a cached career and {missing} have none, so those spotlights "
            f"show no career history. Standings, scores and leaderboards are unaffected — they "
            f"come from pages that did load.", "",
            "| player | name | outcome |", "|---|---|---|"]
    for r in degraded[:50]:
        outcome = "served cached career" if r["had_cache"] else "**no career data**"
        out.append(f"| {r['player_id']} | {r.get('name') or '?'} | {outcome} |")
    if len(degraded) > 50:
        out.append(f"| … | _{len(degraded) - 50} more_ | |")
    return out


def player_annotations(health: dict) -> list[str]:
    degraded = health.get("degraded", [])
    if not degraded:
        return []
    attempted = health.get("attempted", 0)
    missing = health.get("missing", 0)
    # One annotation for the whole set, not one per player: when the site breaks this endpoint it
    # breaks it for everybody, and 300 identical warnings would bury the rest of the run page.
    return [f"::warning title=Career pages degraded::the league site refused {len(degraded)} of "
            f"{attempted} player career page(s); {health.get('served_from_cache', 0)} served from "
            f"cache, {missing} have no career data. The rest of the refresh completed normally."]


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

    if PLAYER_HEALTH_PATH.exists():
        player_health = json.loads(PLAYER_HEALTH_PATH.read_text(encoding="utf-8"))
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("\n".join(player_summary_lines(player_health)) + "\n")
        for line in player_annotations(player_health):
            print(line)
        print(f"{len(player_health.get('degraded', []))} career page(s) degraded")


if __name__ == "__main__":
    main()
