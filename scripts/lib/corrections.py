"""Applies manual stat corrections on top of a scraped box score.

Each data/corrections/<game_id>.json file is:
{
  "corrections": [
    {
      "team": "home" | "away",
      "period": "1",              # matched against the goal's raw scraped period/time text
      "time": "4:32",
      "field": "scorer_number" | "assist1_number" | "assist2_number",
      "original": 31,             # sanity-checked: the scoresheet value, or the current one if
                                  # an earlier correction already changed this field

      "corrected": 9,
      "reason": "Scorekeeper swapped the primary and secondary assist.",
      "corrected_by": "Alex Albano",
      "corrected_at": "2026-09-11T00:00:00Z",
      "source_issue": 12
    }
  ]
}

A roster entry can be corrected the same way (e.g. the sheet says "ALT Goalie" and we know who was
actually in net) with `"kind": "roster"`, identified by team side and jersey number:
{
  "kind": "roster",
  "team": "home",
  "number": 1,
  "name": "ALT Goalie",       # optional: needed when two entries share the number
  "field": "name",            # "name", "position" or "number"
  "original": "ALT Goalie",
  "corrected": "Brad Parker",
  "reason": "...", "corrected_by": "...", "corrected_at": "..."
}

When a sheet lists two skaters with the same number, goals on that number are credited to nobody
(the build can't tell them apart) and the box score shows both names. There are two ways out. If
the scorekeeper simply wrote the wrong number for one of them, correct that entry's `"number"`,
identifying it by `"number"` + `"name"`: e.g. number 47, name "James Roig", field "number",
original 47, corrected 8 -- every goal/assist/penalty on #47 then belongs to the remaining #47. If
they really did both wear it, name the player on the goals that were theirs: `"corrected"` on a
`scorer_number`/`assist1_number`/`assist2_number` takes a roster name as well as a number.

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
    # What the scoresheet said before any correction, per goal field. Corrections are applied in
    # the order they were filed, so a second correction to the same field is checked against the
    # value the first one already wrote -- but the form asks for the "current (wrong)" number and a
    # human re-correcting a goal reads it off the original scoresheet. Accepting either value lets
    # the later correction win while still catching one aimed at the wrong goal or field.
    scraped = {(g["team"], g["period"], g["time"], f): g.get(f)
               for g in box["goals"]
               for f in ("scorer_number", "assist1_number", "assist2_number")}
    for c in corrections:
        if c.get("kind") == "roster_add":
            _apply_roster_add(box, c)
            continue
        if c.get("kind") == "roster":
            _apply_roster_correction(box, c)
            continue
        goal = next((g for g in box["goals"]
                     if g["team"] == c["team"] and g["period"] == c["period"] and g["time"] == c["time"]),
                    None)
        if goal is None:
            box.setdefault("_correction_errors", []).append(
                {**c, "error": "no matching goal found (team/period/time)"})
            continue

        field = c["field"]
        current = goal.get(field)
        was = scraped.get((c["team"], c["period"], c["time"], field))
        if c["original"] not in (current, was):
            box.setdefault("_correction_errors", []).append(
                {**c, "error": f"expected original {c['original']!r} but the value is {current!r}"
                               + (f" (scoresheet said {was!r})" if was != current else "")})
            continue

        # A scorer/assist is a jersey number, or a roster name when the number can't say which
        # player -- two of them wear it, usually a sub who brought their own jersey. A name that
        # isn't on that side's roster would credit nobody and look like it had worked, so it's
        # refused here instead.
        if isinstance(c["corrected"], str):
            side_name = box["home_name"] if c["team"] == "home" else box["away_name"]
            if not any(p.get("name") == c["corrected"] for p in box.get("rosters", {}).get(side_name, [])):
                box.setdefault("_correction_errors", []).append(
                    {**c, "error": f"{c['corrected']!r} is not on {side_name}'s roster for this game"})
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


def _apply_roster_correction(box: dict, c: dict) -> None:
    """Fixes one field of one roster entry in place, identified by side + jersey number (+ name,
    when two entries share the number)."""
    team_name = box["home_name"] if c["team"] == "home" else box["away_name"]
    matches = [p for p in box.get("rosters", {}).get(team_name, [])
               if p.get("number") == c["number"] and ("name" not in c or p.get("name") == c["name"])]
    if not matches:
        box.setdefault("_correction_errors", []).append(
            {**c, "error": "no matching roster entry found (team/number/name)"})
        return
    if len(matches) > 1:
        box.setdefault("_correction_errors", []).append(
            {**c, "error": f"{len(matches)} roster entries wear #{c['number']} -- add \"name\" to pick one"})
        return
    player = matches[0]
    field = c["field"]
    if field not in ("name", "position", "number"):
        box.setdefault("_correction_errors", []).append({**c, "error": f"unsupported roster field {field!r}"})
        return
    current = player.get(field)
    if current != c["original"]:
        box.setdefault("_correction_errors", []).append(
            {**c, "error": f"expected original {c['original']!r} but scraped value is {current!r}"})
        return
    player[field] = c["corrected"]
    player.setdefault("_corrections", {})[field] = {
        "original": c["original"],
        "reason": c.get("reason"),
        "corrected_by": c.get("corrected_by"),
        "corrected_at": c.get("corrected_at"),
        "source_issue": c.get("source_issue"),
    }


def _apply_roster_add(box: dict, c: dict) -> None:
    """Adds a skater the scoresheet left off entirely.

    Beer-league sheets sometimes omit a player who dressed and played. Without the roster entry
    nothing downstream can reach them: goals and assists on their number resolve to nobody, on-ice
    tags key on jersey number so they cannot be tagged at all, and they lose the game from their
    games-played. There is no way to express this as a field correction, since there is no entry to
    correct.

    A sub wearing a number someone already on the sheet is wearing -- common, since a sub brings
    their own jersey -- is added with that number as `wore` (shown in the box score) and no
    `number`. The number stays the scoresheet's join key, so it has to keep pointing at one
    player: making it shared instead would hand every goal, assist and penalty written against it
    to nobody, including the ones that really were the player already on the sheet. The sub is
    reachable by name everywhere that matters -- on-ice tags take a name, and so does a goal
    correction -- which is how the two of them are told apart at all.

    Still refuses a duplicate name: two entries for one player is not a thing the rest of the
    build can make sense of.
    """
    team_name = box["home_name"] if c["team"] == "home" else box["away_name"]
    roster = box.setdefault("rosters", {}).setdefault(team_name, [])
    if any(p.get("name") == c.get("name") for p in roster):
        box.setdefault("_correction_errors", []).append(
            {**c, "error": f"{c.get('name')!r} is already on this roster"})
        return
    number, wore = c.get("number"), None
    if number is not None and any(p.get("number") == number for p in roster):
        number, wore = None, number
    roster.append({
        "number": number,
        "wore": wore,
        "position": c.get("position"),
        "name": c.get("name"),
        "_corrections": {"added": {
            "original": None,
            "reason": c.get("reason"),
            "corrected_by": c.get("corrected_by"),
            "corrected_at": c.get("corrected_at"),
            "source_issue": c.get("source_issue"),
        }},
    })
