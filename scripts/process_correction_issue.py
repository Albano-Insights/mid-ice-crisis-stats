"""Parses a "Stat correction" GitHub Issue Form submission and writes/updates
data/corrections/<game_id>.json. Run by .github/workflows/process-correction-issue.yml.

GitHub renders an issue form's body as a sequence of "### <Label>\n\n<value>" blocks in field
order. This maps those labels back to the field ids declared in
.github/ISSUE_TEMPLATE/stat-correction.yml.

Usage: python scripts/process_correction_issue.py --body-file body.txt --issue-number 12
       --author "some-login" --created-at 2026-09-11T00:00:00Z
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
CORRECTIONS_DIR = ROOT / "data" / "corrections"

_LABEL_TO_FIELD = {
    "Game ID": "game_id",
    "Team": "team",  # first version of the form (home/away dropdown) -- still accepted
    "Who scored": "scoring_team_name",
    "Home team (pre-filled)": "home_team_name",
    "Away team (pre-filled)": "away_team_name",
    "Period": "period",
    "Time": "time",
    "What's wrong": "field",
    "Current (wrong) jersey number": "original",
    "Correct jersey number": "corrected",
    "Reason": "reason",
}


def parse_issue_body(body: str) -> dict:
    sections = re.split(r"^### (.+)$", body, flags=re.MULTILINE)
    # sections = ["", "Label1", "value1\n", "Label2", "value2\n", ...]
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


def scoring_side(fields: dict) -> str:
    """home/away for the goal, derived from 'Who scored' vs the two pre-filled team names. GitHub
    doesn't reliably pre-fill dropdowns, which is why the form no longer asks for home/away
    directly; the old dropdown value is the fallback for issues filed with the first form."""
    scorer = _norm(fields.get("scoring_team_name"))
    if scorer:
        for side in ("home", "away"):
            if scorer == _norm(fields.get(f"{side}_team_name")):
                return side
    if fields.get("team") in ("home", "away"):
        return fields["team"]
    raise ValueError(f"can't tell which side scored: {fields.get('scoring_team_name')!r} is neither "
                     f"{fields.get('home_team_name')!r} nor {fields.get('away_team_name')!r}")


_FIELD_ALIASES = {"scorer": "scorer_number", "assist1": "assist1_number", "assist2": "assist2_number",
                  "scorer_number": "scorer_number", "assist1_number": "assist1_number", "assist2_number": "assist2_number"}


def field_name(raw: str | None) -> str:
    key = re.sub(r"[^a-z0-9_]", "", (raw or "").lower().replace(" ", ""))
    if key not in _FIELD_ALIASES:
        raise ValueError(f"'What's wrong' should be scorer, assist1 or assist2, got {raw!r}")
    return _FIELD_ALIASES[key]


def build_correction(fields: dict, issue_number: int, author: str, created_at: str) -> dict:
    original = fields.get("original")
    corrected = fields.get("corrected")
    return {
        "team": scoring_side(fields),
        "period": fields["period"],
        "time": fields["time"],
        "field": field_name(fields["field"]),
        "original": int(original) if original not in (None, "") else None,
        "corrected": int(corrected) if corrected not in (None, "") else None,
        "reason": fields.get("reason"),
        "corrected_by": author,
        "corrected_at": created_at,
        "source_issue": issue_number,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--author", required=True)
    parser.add_argument("--created-at", default=datetime.now(timezone.utc).isoformat())
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    fields = parse_issue_body(body)

    required = ["game_id", "period", "time", "field", "corrected"]
    missing = [f for f in required if not fields.get(f)]
    if missing:
        raise SystemExit(f"Issue is missing required fields: {missing}. Parsed: {fields}")

    game_id = int(fields["game_id"])
    correction = build_correction(fields, args.issue_number, args.author, args.created_at)

    CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = CORRECTIONS_DIR / f"{game_id}.json"
    data = {"corrections": []}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))

    data["corrections"].append(correction)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote correction for game {game_id} from issue #{args.issue_number}")


if __name__ == "__main__":
    main()
