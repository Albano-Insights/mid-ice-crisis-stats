"""Parses an "On-ice tag" GitHub Issue Form submission and writes/updates data/on_ice/<game_id>.json.
Run by .github/workflows/process-on-ice-issue.yml.

File format (one per game):
{
  "goals": [
    {"team": "home", "period": "2", "time": "7:40",           # identifies the scoresheet goal
     "on_ice": {"home": [9, 12, 24, 7, 15], "away": [...]},   # either side may be missing
     "video_t": 735,                                          # optional hand-anchored timestamp
     "tagged_by": "login", "tagged_at": "...", "source_issues": [17]}
  ]
}
One issue can carry both sides. A later tag for a goal replaces whichever sides it includes and
keeps the other.

Usage: python scripts/process_on_ice_issue.py --body-file body.txt --issue-number 17 --author x --created-at ...
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
ON_ICE_DIR = ROOT / "data" / "on_ice"
ANCHORS_DIR = ROOT / "data" / "film_anchors"

_LABEL_TO_FIELD = {
    "Game ID": "game_id",
    "Who scored": "scoring_team_name",
    "Scoring side on the scoresheet (home/away — pre-filled, leave as is)": "team",
    "Home team (pre-filled)": "home_team_name",
    "Away team (pre-filled)": "away_team_name",
    "Period": "period",
    "Time on the scoresheet (e.g. 7:40)": "time",
    "Home team skaters on the ice (jersey numbers, comma-separated)": "on_ice_home",
    "Away team skaters on the ice (jersey numbers, comma-separated)": "on_ice_away",
    "Video time where it went in, if the ▶ link was wrong (optional)": "video_t",
    "Notes (optional)": "notes",
    # First version of the form (one bench per issue) -- still accepted.
    "Scoring team": "team",
    "Which side's skaters are you tagging?": "side_tagged",
    "Jersey numbers on the ice for that side (comma-separated, skaters only)": "on_ice",
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


def parse_video_time(raw: str | None) -> int | None:
    """'13:33' -> 813, '1:02:15' -> 3735, '813' -> 813 -- the form converts, but a hand-edited issue
    might say it the human way."""
    t = (raw or "").strip()
    if not t:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return int(float(t))
    parts = t.split(":")
    if not 2 <= len(parts) <= 3 or not all(re.fullmatch(r"\d{1,2}", p.strip()) for p in parts):
        raise ValueError(f"video time should look like 13:33, got {raw!r}")
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


def parse_numbers(raw: str) -> list[int]:
    nums = sorted({int(x) for x in re.findall(r"\d+", raw or "")})
    if not 3 <= len(nums) <= 6:
        raise ValueError(f"expected 3-6 skaters on the ice, got {nums}")
    return nums


def apply(fields: dict, issue_number: int, author: str, created_at: str) -> Path:
    game_id = int(fields["game_id"])
    team, period, time = fields["team"], fields["period"], fields["time"]
    sides = {side: parse_numbers(fields[f"on_ice_{side}"]) for side in ("home", "away") if fields.get(f"on_ice_{side}")}
    if not sides:
        raise ValueError("no skaters given for either side")

    path = ON_ICE_DIR / f"{game_id}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"goals": []}
    goal = next((g for g in data["goals"] if (g["team"], g["period"], g["time"]) == (team, period, time)), None)
    if goal is None:
        goal = {"team": team, "period": period, "time": time, "on_ice": {}, "source_issues": []}
        data["goals"].append(goal)
    goal["on_ice"].update(sides)  # re-tagging one side keeps the other side's list
    goal["tagged_by"] = author
    goal["tagged_at"] = created_at
    goal["source_issues"] = sorted(set(goal.get("source_issues", [])) | {issue_number})
    if fields.get("notes"):
        goal["notes"] = fields["notes"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # A corrected video timestamp is a film anchor, stored by the goal's identity; film_sync.py
    # resolves it. An issue with only a video time is fine -- that alone fixes a ▶ link.
    if video_t is not None:
        apath = ANCHORS_DIR / f"{game_id}.json"
        anchors = json.loads(apath.read_text(encoding="utf-8")) if apath.exists() else {"goals": {}, "by_goal": []}
        anchors.setdefault("by_goal", [])
        anchors["by_goal"] = [a for a in anchors["by_goal"] if (a["team"], a["period"], a["time"]) != (team, period, time)]
        anchors["by_goal"].append({"team": team, "period": period, "time": time, "video_t": video_t})
        apath.parent.mkdir(parents=True, exist_ok=True)
        apath.write_text(json.dumps(anchors, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--issue-number", type=int, required=True)
    ap.add_argument("--author", required=True)
    ap.add_argument("--created-at", required=True)
    args = ap.parse_args()
    fields = parse_issue_body(Path(args.body_file).read_text(encoding="utf-8"))
    for key in ("game_id", "team", "period", "time"):
        if not fields.get(key):
            raise SystemExit(f"missing required field: {key}")
    if not (fields.get("on_ice_home") or fields.get("on_ice_away") or fields.get("on_ice") or fields.get("video_t")):
        raise SystemExit("need skaters for at least one side, or a video time")
    path = apply(fields, args.issue_number, args.author, args.created_at)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
