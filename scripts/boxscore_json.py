"""Any league game as JSON, straight from the league site -- for the livebarn-youtube skill's
`describe` when a game isn't one of ours (another division, the C3/C4 teams, a scouting target).

Prints one JSON object: the parsed box score (rosters, goals, penalties) plus the scoresheet
header (date, time, rink, level) in the same field names data/derived/games/<id>.json uses,
so the description generator can treat it like one of our games.

Usage: python scripts/boxscore_json.py <game_id> [--us "<team name>"]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import ttscore_client as tt  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    game_id = int(sys.argv[1])
    us = sys.argv[sys.argv.index("--us") + 1] if "--us" in sys.argv else None

    html = tt.fetch("oss-scoresheet", game_id=game_id, mode="display")
    box = tt.parse_boxscore(html, game_id)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " "))
    pick = lambda pat: (m.group(1).strip() if (m := re.search(pat, text)) else None)  # noqa: E731
    date = pick(r"Date:\s*(\d{2}-\d{2}-\d{2})")
    iso = datetime.strptime(date, "%m-%d-%y").date().isoformat() if date else None
    level = pick(r"Level:\s*(.+?)\s+Attendance")

    home, away = box["home_name"], box["away_name"]
    if us and us not in (home, away):
        low = {home.lower(): home, away.lower(): away}
        us = low.get(us.lower()) or next((n for n in (home, away) if us.lower() in n.lower()), None)
    is_home = (us == home) if us else True
    out = {
        "game_id": game_id,
        "season_id": None,
        "season_label": level or "league game",
        "iso_date": iso,
        "date": datetime.fromisoformat(iso).strftime("%a %b %-d") if iso and sys.platform != "win32"
                else (datetime.fromisoformat(iso).strftime("%a %b %d").replace(" 0", " ") if iso else None),
        "time": pick(r"Time:\s*(\d{1,2}:\d{2}\s*[AP]M)"),
        "rink": pick(r"Location:\s*(.+?)\s+Scorekeeper"),
        "level_label": level,
        "game_type": "league game",
        "is_home": is_home,
        "opponent": away if is_home else home,
        "home_name": home,
        "away_name": away,
        "home_final": box.get("home_final"),
        "away_final": box.get("away_final"),
        "rosters": box.get("rosters", {}),
        "goals": box.get("goals", []),
        "penalties": box.get("penalties", {"home": [], "away": []}),
        "on_ice_tags": [],
        "tag_coverage": None,
        "from_league_site": True,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
