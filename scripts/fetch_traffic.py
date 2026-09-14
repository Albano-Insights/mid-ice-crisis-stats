"""Pull site traffic from the GoatCounter API into docs/data/traffic.json.

Feeds the unlisted docs/traffic.html page. Requires GOATCOUNTER_API_TOKEN
(create one at Settings -> API in GoatCounter with "Read statistics" permission).

    GOATCOUNTER_API_TOKEN=... python scripts/fetch_traffic.py [--days 90]
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

SITE_CODE = os.environ.get("GOATCOUNTER_SITE", "midicecrisis")
API = f"https://{SITE_CODE}.goatcounter.com/api/v0"
OUT = Path(__file__).resolve().parent.parent / "docs" / "data" / "traffic.json"

# Breakdown pages exposed by GET /api/v0/stats/{page}
BREAKDOWNS = ["toprefs", "locations", "browsers", "systems", "sizes"]


def api_get(session, path, **params):
    r = session.get(f"{API}/{path}", params=params, timeout=30)
    if r.status_code == 429:  # GoatCounter allows ~4 req/s
        time.sleep(1)
        r = session.get(f"{API}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    token = os.environ.get("GOATCOUNTER_API_TOKEN")
    if not token:
        sys.exit("GOATCOUNTER_API_TOKEN is not set")

    end = date.today()
    start = end - timedelta(days=args.days - 1)
    window = {"start": start.isoformat(), "end": end.isoformat()}

    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"

    total = api_get(s, "stats/total", **window)
    daily = [{"day": d["day"], "visits": d["daily"]} for d in total.get("stats", [])]

    hits = api_get(s, "stats/hits", daily="true", limit=20, **window)
    pages = [
        {"path": h["path"], "title": h.get("title") or "", "visits": h["count"]}
        for h in hits.get("hits", [])
        if not h.get("event")
    ]

    breakdowns = {}
    for page in BREAKDOWNS:
        data = api_get(s, f"stats/{page}", limit=15, **window)
        breakdowns[page] = [{"name": r["name"], "visits": r["count"]} for r in data.get("stats", [])]

    # Rollups for the KPI row
    def window_sum(n):
        return sum(d["visits"] for d in daily[-n:])

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site": f"https://{SITE_CODE}.goatcounter.com",
        "window": window,
        "totals": {
            "visits": total.get("total", 0),
            "last_7d": window_sum(7),
            "prev_7d": window_sum(14) - window_sum(7),
            "last_30d": window_sum(30),
        },
        "daily": daily,
        "pages": pages,
        **breakdowns,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({out['totals']['visits']} visits over {args.days} days)")


if __name__ == "__main__":
    main()
