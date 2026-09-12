"""Fetches public adult-hockey rink events (stick & puck, drop-in, open events) from a DaySmart
Recreation facility's JSON:API, to overlay on our own schedule calendar.

The API needs `Accept: application/vnd.api+json` and a same-site-looking `Referer`/`Origin` -- without
those it returns a bare 406, even though no auth/API key is actually required for public event data.
"""
from __future__ import annotations

import time

import requests

BASE_URL = "https://api.daysmartrecreation.com/v1/events"
APP_ORIGIN = "https://apps.daysmartrecreation.com"
USER_AGENT = (
    "MidIceCrisisStatsBot/1.0 (+https://github.com/; small beer-league hockey team stats project; "
    "contact: albano0731@gmail.com)"
)
REQUEST_DELAY_SECONDS = 1.0
PAGE_SIZE = 50

_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/vnd.api+json",
    "Referer": APP_ORIGIN + "/",
    "Origin": APP_ORIGIN,
})


def fetch_events(company: str, sport_id: int, start_date: str, end_date: str, facility_id: int | None = None) -> list[dict]:
    """Returns every event's `attributes` dict (desc, start, end, best_description, ...) for the given
    facility/company between start_date and end_date (both 'YYYY-MM-DD'), walking JSON:API pagination.
    """
    events: list[dict] = []
    page = 1
    while True:
        params = {
            "cache[save]": "false",
            "page[size]": PAGE_SIZE,
            "page[number]": page,
            "sort": "start",
            "filter[start_date__gte]": start_date,
            "filter[start_date__lte]": end_date,
            "filter[unconstrained]": 1,
            "filter[homeTeam.sport_id__in]": sport_id,
            "company": company,
        }
        if facility_id is not None:
            params["filter[resource.facility_id__in]"] = facility_id

        resp = _session.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        time.sleep(REQUEST_DELAY_SECONDS)
        payload = resp.json()

        for row in payload.get("data", []):
            events.append({"id": row["id"], **row.get("attributes", {})})

        meta = payload.get("meta", {}).get("page", {})
        if not meta or meta.get("current-page", page) >= meta.get("last-page", page):
            break
        page += 1

    return events
