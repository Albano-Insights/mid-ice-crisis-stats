"""Scrapes the team's YouTube game-film playlist -- no API key, no headless browser.

Both the playlist page and each video's watch page are server-rendered with the full data embedded as
a JSON blob for SEO (`ytInitialData` / `ytInitialPlayerResponse`), same trick as the hockey stats site.
Must balanced-brace parse via `json.JSONDecoder().raw_decode` rather than a regex -- the JSON contains
nested braces a lazy regex mismatches.
"""
from __future__ import annotations

import json
import re
import time

import requests

BASE_URL = "https://www.youtube.com/"
USER_AGENT = (
    "MidIceCrisisStatsBot/1.0 (+https://github.com/; small beer-league hockey team stats project; "
    "contact: albano0731@gmail.com)"
)
REQUEST_DELAY_SECONDS = 1.0
GAME_ID_RE = re.compile(r"Game\s*#(\d+)")

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _fetch(url: str, params: dict | None = None) -> str:
    resp = _session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return resp.text


def _extract_json_var(html: str, var_name: str) -> dict | None:
    key = f"var {var_name} = "
    idx = html.find(key)
    if idx == -1:
        return None
    start = idx + len(key)
    try:
        data, _end = json.JSONDecoder().raw_decode(html, start)
    except json.JSONDecodeError:
        return None
    return data


def _find_all(obj, key: str, out: list) -> None:
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj[key])
        for v in obj.values():
            _find_all(v, key, out)
    elif isinstance(obj, list):
        for v in obj:
            _find_all(v, key, out)


def fetch_playlist_videos(playlist_id: str) -> list[dict]:
    """Returns [{video_id, title}] for every video the playlist page renders (no pagination handling
    -- fine while the playlist stays under the ~100-video single-page-load size; revisit with a
    continuation-token walk if it grows past that)."""
    html = _fetch(BASE_URL + "playlist", params={"list": playlist_id})
    data = _extract_json_var(html, "ytInitialData")
    if data is None:
        return []

    lockups: list = []
    _find_all(data, "lockupViewModel", lockups)

    videos = []
    seen = set()
    for v in lockups:
        video_id = v.get("contentId")
        if not video_id or video_id in seen:
            continue
        try:
            title = v["metadata"]["lockupMetadataViewModel"]["title"]["content"]
        except (KeyError, TypeError):
            continue
        seen.add(video_id)
        videos.append({"video_id": video_id, "title": title})
    return videos


def fetch_video_description(video_id: str) -> str:
    html = _fetch(BASE_URL + "watch", params={"v": video_id})
    data = _extract_json_var(html, "ytInitialPlayerResponse")
    if data is None:
        return ""
    return data.get("videoDetails", {}).get("shortDescription", "") or ""


def extract_game_id(description: str) -> int | None:
    m = GAME_ID_RE.search(description)
    return int(m.group(1)) if m else None
