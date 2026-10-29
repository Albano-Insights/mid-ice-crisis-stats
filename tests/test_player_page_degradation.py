"""What happens when the league site breaks one player's career page.

On 2026-10-27 the site began serving HTTP 500 for every *real* player's career page while
nonexistent ids still returned a clean empty 200. The scraper raised on the first one and the
whole nightly refresh died at the enrichment step -- after standings, scores and box scores had
already been fetched successfully -- so the public dashboard silently froze for three days.

Two separate failures are pinned here:
  1. one unavailable page must not abort the refresh, and must not lose the cached career; and
  2. the 500 body is a *truncated* page that still parses (bio renders, stat tables never do),
     so "parsed without raising" is not evidence of a usable career.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import scrape  # noqa: E402
from lib import ttscore_client as tt  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
TRUNCATED = (FIXTURES / "player_461_truncated_500.html").read_text(encoding="utf-8", errors="replace")

GOOD_CACHE = {"player_id": 461, "name": "Jackie Ginsparg", "roster_name": "Jackie Ginsparg",
              "summary": [{"team": "Mid Ice Crisis", "season_label": "Fall 2025", "gp": 16, "pts": 9}],
              "games": [{"game_id": 8846, "date": "2025-10-14", "pts": 1}]}


# --- the truncated page itself -------------------------------------------------------------

def test_truncated_page_still_parses_and_yields_a_name():
    # This is the trap: it does NOT raise, so any caller trusting the parser alone is fooled.
    page = tt.parse_player_page(TRUNCATED)
    assert page["name"] == "Jackie Ginsparg"
    assert page["summary"] == []
    assert page["games"] == []


def test_truncated_page_is_not_a_complete_career():
    assert not scrape._career_is_complete(tt.parse_player_page(TRUNCATED))


def test_a_real_career_is_complete():
    assert scrape._career_is_complete(GOOD_CACHE)


# --- fetching one career page --------------------------------------------------------------

def _patch_fetch(monkeypatch, behaviour):
    monkeypatch.setattr(tt, "fetch", behaviour)


def test_unavailable_page_keeps_the_cached_career(monkeypatch):
    def boom(path, **params):
        raise tt.PageUnavailable("display-player-stats.php?player=461", 500)
    _patch_fetch(monkeypatch, boom)
    got = scrape._fetch_player_page(461, "Jackie Ginsparg", GOOD_CACHE)
    assert got is GOOD_CACHE  # identity: the caller uses this to tell a fallback from a refresh


def test_unavailable_page_without_cache_is_skipped_not_fatal(monkeypatch):
    def boom(path, **params):
        raise tt.PageUnavailable("display-player-stats.php?player=999", 500)
    _patch_fetch(monkeypatch, boom)
    assert scrape._fetch_player_page(999, "Nobody Cached", None) is None


def test_truncated_response_does_not_overwrite_a_good_career(monkeypatch):
    # The regression that would silently empty every spotlight: a 200 whose body is cut short.
    _patch_fetch(monkeypatch, lambda path, **params: TRUNCATED)
    got = scrape._fetch_player_page(461, "Jackie Ginsparg", GOOD_CACHE)
    assert got is GOOD_CACHE
    assert got["summary"], "cached career must survive a truncated response"


def test_a_good_response_is_used_and_stamped(monkeypatch):
    real = (FIXTURES / "player_6317.html").read_text(encoding="utf-8", errors="replace")
    _patch_fetch(monkeypatch, lambda path, **params: real)
    got = scrape._fetch_player_page(6317, "Roster Name", None)
    assert got is not None and got["summary"]
    assert got["player_id"] == 6317 and got["roster_name"] == "Roster Name"


# --- the HTTP layer ------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, text="body"):
        self.status_code, self.text, self.url = status, text, "http://x/y"


def test_5xx_is_retried_then_reported_as_page_unavailable(monkeypatch):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(1)
        return _Resp(500)
    monkeypatch.setattr(tt._session, "get", get)
    monkeypatch.setattr(tt.time, "sleep", lambda s: None)
    with pytest.raises(tt.PageUnavailable) as exc:
        tt.fetch("display-player-stats.php", player=461)
    assert exc.value.status == 500
    assert len(calls) == tt.MAX_RETRIES, "a 5xx should use every retry -- the site flaps under load"


def test_4xx_is_not_retried(monkeypatch):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(1)
        return _Resp(404)
    monkeypatch.setattr(tt._session, "get", get)
    monkeypatch.setattr(tt.time, "sleep", lambda s: None)
    with pytest.raises(tt.PageUnavailable):
        tt.fetch("display-player-stats.php", player=1)
    assert len(calls) == 1, "a 404 will not change; retrying only hammers a volunteer-run site"


def test_a_transient_5xx_that_recovers_is_returned(monkeypatch):
    seq = [_Resp(500), _Resp(200, "<html>ok</html>")]
    monkeypatch.setattr(tt._session, "get", lambda url, params=None, timeout=None: seq.pop(0))
    monkeypatch.setattr(tt.time, "sleep", lambda s: None)
    assert tt.fetch("display-stats", season=0) == "<html>ok</html>"


# --- the circuit breaker -------------------------------------------------------------------
# Tolerating a dead endpoint is not enough on its own: the first version of this fix asked all
# 187 pages with the full retry budget, and the escalating backoff alone would have stretched a
# 5-minute refresh past 40 minutes every night the site stayed broken.

def test_retries_budget_is_honoured_per_call(monkeypatch):
    calls = []
    monkeypatch.setattr(tt._session, "get",
                        lambda url, params=None, timeout=None: (calls.append(1), _Resp(500))[1])
    monkeypatch.setattr(tt.time, "sleep", lambda s: None)
    with pytest.raises(tt.PageUnavailable):
        tt.fetch("display-player-stats.php", retries=2, player=461)
    assert len(calls) == 2


def test_a_dead_endpoint_stops_being_asked(monkeypatch, tmp_path):
    """With every career page 500ing, the scrape must finish, keep every cached career, and give
    up on the endpoint instead of working through the whole roster."""
    roster = {pid: f"Player {pid}" for pid in range(1, 51)}
    asked: list[int] = []

    def dead(path, retries=None, **params):
        asked.append(params["player"])
        raise tt.PageUnavailable(path, 500)

    monkeypatch.setattr(tt, "fetch", dead)
    monkeypatch.setattr(scrape, "spotlight_player_ids", lambda *a, **k: roster)
    monkeypatch.setattr(scrape, "fetch_current_season_id", lambda league_id: (19, "BH Adult"))
    monkeypatch.setattr(scrape, "fetch_league_standings_cached",
                        lambda *a, **k: {"rows": [{"level_id": 12, "name": "Mid Ice Crisis"}]})
    monkeypatch.setattr(scrape, "fetch_league_level_players_cached",
                        lambda *a, **k: [{"player_id": pid} for pid in roster])
    monkeypatch.setattr(scrape, "PLAYERS_DIR", tmp_path / "players")
    monkeypatch.setattr(scrape, "PLAYER_HEALTH_PATH", tmp_path / "player_health.json")
    monkeypatch.setattr(scrape, "SEASON_LABELS_PATH", tmp_path / "season_labels.json")

    # one player has a good cached career; it must still be there afterwards
    (tmp_path / "players").mkdir()
    cached_path = tmp_path / "players" / "1.json"
    cached_path.write_text(__import__("json").dumps(GOOD_CACHE), encoding="utf-8")

    scrape.scrape_players({}, {754}, {19})  # must not raise

    assert len(asked) <= scrape.CAREER_ENDPOINT_GIVE_UP_AFTER, (
        f"breaker should stop after {scrape.CAREER_ENDPOINT_GIVE_UP_AFTER} failures, asked {len(asked)}")
    health = __import__("json").loads((tmp_path / "player_health.json").read_text(encoding="utf-8"))
    assert health["endpoint_down"] is True
    assert len(health["degraded"]) == len(roster)
    assert __import__("json").loads(cached_path.read_text(encoding="utf-8"))["summary"], \
        "a cached career must survive a total endpoint outage"
