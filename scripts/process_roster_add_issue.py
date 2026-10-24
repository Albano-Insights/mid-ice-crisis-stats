"""Parses a "Missing skater" GitHub Issue Form submission and appends a `kind: roster_add`
correction to data/corrections/<game_id>.json. Run by .github/workflows/process-roster-add-issue.yml.

Beer-league scorekeepers routinely leave a sub off the sheet. Nothing downstream can reach a player
who isn't on the game's roster: the "Tag on-ice" grid is built from it, so they can't be tagged at
all, goals and assists on their number resolve to nobody, and they lose the game from their games
played. `lib/corrections._apply_roster_add` fixes that at build time; this is the path to it that
doesn't require hand-editing a JSON file and pushing.

Usage: python scripts/process_roster_add_issue.py --body-file body.txt --issue-number 42
       --author some-login --created-at 2026-10-23T00:00:00Z
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
CORRECTIONS_DIR = ROOT / "data" / "corrections"
SEASONS_RAW_DIR = ROOT / "data" / "raw" / "seasons"

_LABEL_TO_FIELD = {
    "Game ID": "game_id",
    "Which team they played for": "team_name",
    "Home team (pre-filled)": "home_team_name",
    "Away team (pre-filled)": "away_team_name",
    "Player name": "name",
    "Jersey number": "number",
    "Position (optional)": "position",
    "Reason (optional)": "reason",
}


def parse_issue_body(body: str) -> dict:
    sections = re.split(r"^### (.+)$", body, flags=re.MULTILINE)
    fields = {}
    for i in range(1, len(sections), 2):
        label = sections[i].strip()
        value = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if value.lower() in ("_no response_", ""):
            value = None
        field_id = _LABEL_TO_FIELD.get(label)
        if field_id:
            fields[field_id] = value
    return fields


def _norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def load_raw_boxscore(game_id: int) -> dict | None:
    """The scraped sheet, uncorrected. Used only to check the submission against reality before
    writing it -- an unknown team name or a number already worn is worth saying on the issue
    rather than leaving for the build to log and the dashboard to not show."""
    for path in sorted(SEASONS_RAW_DIR.glob(f"*/boxscore_{game_id}.json")):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return None


def team_side(fields: dict, box: dict | None) -> str:
    """home/away for the bench they dressed on, from the team name. The box score is the better
    source (a hand-filed issue may not carry the pre-filled names); the form fields are the
    fallback when the scrape isn't in the checkout."""
    wanted = _norm(fields.get("team_name"))
    if not wanted:
        raise ValueError("no team name given")
    names = {}
    if box:
        names = {"home": box.get("home_name"), "away": box.get("away_name")}
    else:
        names = {"home": fields.get("home_team_name"), "away": fields.get("away_team_name")}
    for side, name in names.items():
        if wanted == _norm(name):
            return side
    raise ValueError(f"{fields.get('team_name')!r} is neither {names.get('home')!r} nor "
                     f"{names.get('away')!r} in game {fields.get('game_id')}")


def parse_number(raw: str | None) -> int | None:
    t = (raw or "").strip().lstrip("#")
    if not t:
        return None
    if not t.isdigit():
        raise ValueError(f"jersey number should be a number, got {raw!r}")
    return int(t)


def check_against_sheet(box: dict | None, side: str, name: str, number: int | None) -> str | None:
    """Refuses what `_apply_roster_add` refuses, early, so the issue says why; returns a note to
    comment back when the add needs explaining.

    A number someone on the sheet already wears is not a refusal: a sub brings their own jersey
    and a clash is ordinary. The overlay keeps it off the number -- the scoresheet's join key has
    to go on naming one player, or every goal written against that number, including the ones
    that really were the player already on the sheet, would be credited to nobody -- and records
    it as the number they wore. They're reached by name after that, which is how the two of them
    are told apart anyway."""
    if box is None:
        return None
    team_name = box["home_name"] if side == "home" else box["away_name"]
    roster = box.get("rosters", {}).get(team_name, [])
    if any(_norm(p.get("name")) == _norm(name) for p in roster):
        raise ValueError(f"{name} is already on {team_name}'s sheet for this game")
    if number is not None:
        worn = [p for p in roster if p.get("number") == number]
        if worn:
            return (f"#{number} is already {worn[0].get('name')}'s on this sheet, so the number stays "
                    f"theirs and {name} is tagged and credited by name instead.")
    return None


def build_correction(fields: dict, side: str, number: int | None, issue_number: int,
                     author: str, created_at: str) -> dict:
    position = (fields.get("position") or "").strip().upper() or None
    return {
        "kind": "roster_add",
        "team": side,
        "number": number,
        "name": fields["name"].strip(),
        "position": position,
        "reason": fields.get("reason"),
        "corrected_by": author,
        "corrected_at": created_at,
        "source_issue": issue_number,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--issue-number", required=True, type=int)
    ap.add_argument("--author", required=True)
    ap.add_argument("--created-at", default=datetime.now(timezone.utc).isoformat())
    args = ap.parse_args()

    fields = parse_issue_body(Path(args.body_file).read_text(encoding="utf-8"))
    missing = [f for f in ("game_id", "team_name", "name") if not fields.get(f)]
    if missing:
        raise SystemExit(f"Issue is missing required fields: {missing}. Parsed: {fields}")

    game_id = int(fields["game_id"])
    box = load_raw_boxscore(game_id)
    side = team_side(fields, box)
    number = parse_number(fields.get("number"))
    note = check_against_sheet(box, side, fields["name"], number)
    correction = build_correction(fields, side, number, args.issue_number, args.author, args.created_at)

    CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = CORRECTIONS_DIR / f"{game_id}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"corrections": []}
    data.setdefault("corrections", [])
    # Roster entries first, goal corrections after -- the overlay doesn't care about the order,
    # but a file read by a human should introduce the player before crediting them with a goal.
    insert_at = next((i for i, c in enumerate(data["corrections"]) if c.get("kind") not in ("roster", "roster_add")),
                     len(data["corrections"]))
    data["corrections"].insert(insert_at, correction)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"added {correction['name']} to game {game_id} ({side}) from issue #{args.issue_number}")
    if note:
        # The workflow reads this back out to comment on the issue -- a silently reinterpreted
        # jersey number is exactly the kind of thing someone should hear about.
        print(f"::notice::{note}")
        Path("roster_add_note.txt").write_text(note, encoding="utf-8")


if __name__ == "__main__":
    main()
