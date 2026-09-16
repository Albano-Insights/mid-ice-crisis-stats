"""Applies manual stat corrections on top of a scraped box score.

Each data/corrections/<game_id>.json file is:
{
  "corrections": [
    {
      "team": "home" | "away",
      "period": "1",              # matched against the goal's raw scraped period/time text
      "time": "4:32",
      "field": "scorer_number" | "assist1_number" | "assist2_number",
      "original": 31,             # sanity-checked against the current scraped value
      "corrected": 9,
      "reason": "Scorekeeper swapped the primary and secondary assist.",
      "corrected_by": "Alex Albano",
      "corrected_at": "2026-09-11T00:00:00Z",
      "source_issue": 12
    }
  ]
}

A goal is identified by (team, period, time) rather than list position, since that's what a human
reading a box score would naturally reference, and it stays stable even if parsing/ordering changes.
Raw scraped data is never mutated on disk -- corrections are applied fresh at build time, and every
corrected field is annotated with `_corrections` on the goal so the dashboard can show what changed
and why.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


def load_corrections(corrections_dir: Path, game_id: int) -> list[dict]:
    path = corrections_dir / f"{game_id}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        # A hand-edited file may leave an empty {} behind -- ignore it rather than crash the build.
        return [c for c in json.load(f).get("corrections", []) if c.get("team")]


def apply_corrections(box: dict, corrections: list[dict]) -> dict:
    """Returns a corrected deep copy of `box`; does not mutate the input."""
    box = copy.deepcopy(box)
    for c in corrections:
        goal = next((g for g in box["goals"]
                     if g["team"] == c["team"] and g["period"] == c["period"] and g["time"] == c["time"]),
                    None)
        if goal is None:
            box.setdefault("_correction_errors", []).append(
                {**c, "error": "no matching goal found (team/period/time)"})
            continue

        field = c["field"]
        current = goal.get(field)
        if current != c["original"]:
            box.setdefault("_correction_errors", []).append(
                {**c, "error": f"expected original {c['original']!r} but scraped value is {current!r}"})
            continue

        goal[field] = c["corrected"]
        goal.setdefault("_corrections", {})[field] = {
            "original": c["original"],
            "reason": c.get("reason"),
            "corrected_by": c.get("corrected_by"),
            "corrected_at": c.get("corrected_at"),
            "source_issue": c.get("source_issue"),
        }
    return box
