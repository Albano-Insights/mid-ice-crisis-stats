"""Parser tests against real, cached pages from the league site.

The site's markup is the fragile part of this whole pipeline: when it changes, the scraper doesn't
error, it just starts writing empty pages (that's exactly how the career-page `.php` suffix bug
showed up -- 27 players with zero stints and no exception anywhere). These tests pin what each
parser must find on a known page, so a markup change fails loudly here instead of silently in
production. Fixtures are verbatim HTML; refresh one by re-downloading it when the site changes
on purpose.

Run: python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lib import ttscore_client as tt  # noqa: E402
from lib import spotlight as sp  # noqa: E402
from lib import analytics  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- career page

def test_player_page_parses_summary_and_games():
    page = tt.parse_player_page(fixture("player_6317.html"))
    assert page["name"] == "Shawn Cash"
    assert len(page["summary"]) == 6
    assert len(page["games"]) == 63
    first = page["summary"][0]
    assert set(first) == {"team", "season_label", "gp", "goals", "assists", "pims", "pts", "ppg", "shg", "gwg"}
    # Crosses leagues: both adult leagues and a tournament appear on one page.
    labels = {row["season_label"] for row in page["summary"]}
    assert {"ID Fall 2026", "WSummer 2026", "4th Annual 9/11 Tournament"} <= labels
    game = page["games"][0]
    assert game["date"].count("-") == 2 and game["game_id"] == 9323


def test_player_page_totals_are_consistent():
    page = tt.parse_player_page(fixture("player_6317.html"))
    for row in page["summary"]:
        assert row["pts"] == row["goals"] + row["assists"], row
        played = [g for g in page["games"] if (g["team"], g["season_label"]) == (row["team"], row["season_label"])]
        assert len(played) == row["gp"], row


def test_empty_player_page_yields_nothing():
    # The bare (non-.php) endpoint serves a stub page: the parser must return empty, not garbage.
    page = tt.parse_player_page("<html><body><table><tr><th>Nothing</th></tr></table></body></html>")
    assert page == {"name": "", "summary": [], "games": []}


# ---------------------------------------------------------------- standings

@pytest.mark.parametrize("name,league_label,season_id,levels", [
    ("standings_league1_current.html", "ID Adult", 20, {"Adult C1", "Adult D"}),
    ("standings_league4_current.html", "BH Adult", 19, {"Adult D1"}),
])
def test_standings_current_page(name, league_label, season_id, levels):
    html = fixture(name)
    rows = tt.parse_standings(html)
    assert rows, "no standings rows parsed"
    assert tt.parse_league_label(html) == league_label
    assert tt.parse_current_season_id(html) == season_id
    assert levels <= {r["level_label"] for r in rows}
    for r in rows:
        assert r["team_id"] and r["name"] and r["level_id"] is not None
        assert r["gp"] is None or isinstance(r["gp"], int)  # None before a season's first game


def test_season_options_carry_labels():
    opts = tt.parse_season_options(fixture("standings_league4_current.html"))
    assert opts["18"] == "WSummer 2026" and opts["13"] == "WM Fall 2025"
    assert "0" not in opts  # "Current" is an alias, never a real id


# ---------------------------------------------------------------- team page + division stats

def test_team_page_games_and_stats():
    page = tt.parse_team_page(fixture("team_552_s18.html"))
    assert len(page["games"]) >= 10
    assert page["player_stats"] and page["goalie_stats"]
    g = page["games"][0]
    assert g["level_label"] == "Adult D" and g["league_label"] == "BH Adult"
    assert all(row["player_id"] for row in page["player_stats"])
    finals = [g for g in page["games"] if g["is_final"]]
    assert finals and all(g["has_boxscore"] for g in finals)


def test_league_player_stats():
    rows = tt.parse_league_player_stats(fixture("league_stats_s18_l12.html"))
    assert len(rows) > 50
    assert all(r["player_id"] for r in rows)
    assert all(r["pts"] == r["goals"] + r["assists"] for r in rows)


# ---------------------------------------------------------------- box score

def test_scoresheet_boxscore():
    box = tt.parse_boxscore(fixture("scoresheet_8627.html"), 8627)
    assert box["home_name"] and box["away_name"]
    assert box["home_final"] + box["away_final"] == len(box["goals"]) == 4
    assert set(box["rosters"]) == {box["home_name"], box["away_name"]}
    for goal in box["goals"]:
        assert goal["team"] in ("home", "away") and goal["period"] in ("1", "2", "3")
    # Goals reference jersey numbers that exist on that side's roster
    for goal in box["goals"]:
        side_name = box["home_name"] if goal["team"] == "home" else box["away_name"]
        numbers = {p["number"] for p in box["rosters"][side_name]}
        assert goal["scorer_number"] in numbers


# ---------------------------------------------------------------- analytics / grading (pure)

def test_tier_ladder():
    assert sp.parse_tier("Adult D")["rung"] == 1.0
    assert sp.parse_tier("Adult D1")["rung"] == 1.25
    assert sp.parse_tier("Adult C3 Lower") == {"name": "C3", "rung": 1.75, "label": "C3 Lower"}
    assert sp.parse_tier("Adult C2 Gold")["rung"] == 3.25
    assert sp.parse_tier("Adult A/B")["rung"] == 5.5
    assert sp.parse_tier("Adult 40+") is None and sp.parse_tier(None) is None


def test_caliber_bands_and_pull():
    assert sp.caliber_label(1.0)["label"] == "Solid D"
    assert sp.caliber_label(1.6)["tier"] == "C3"
    assert sp.stint_rung(1.0, 50) == 1.0
    assert sp.stint_rung(1.0, 100) == pytest.approx(1.75)
    assert sp.persistence_bonus(1) == 0 and sp.persistence_bonus(10) == sp.PERSISTENCE_CAP
    assert sp.wowy_adjustment(1.0, -1.0) == pytest.approx(sp.WOWY_WEIGHT)
    assert sp.wowy_adjustment(None, 0.0) is None
    assert sp.recency_weight(0) == 1.0 and sp.recency_weight(sp.RECENCY_HALF_LIFE_DAYS) == pytest.approx(0.5)


def test_percentile_handles_ties_and_positions():
    pop = [{"player_id": i, "gp": 5, "pts": p} for i, p in enumerate([0, 0, 0, 5, 10, 10, 15, 20])]
    r = sp.percentile_in_division(2.0, pop)
    assert r["of"] == 8 and r["pct"] > 50 and r["peers"] == "all skaters"
    positions = {i: ("D" if i < 5 else "F") for i in range(8)}
    r = sp.percentile_in_division(2.0, pop, "D", positions)
    assert r["peers"] == "defensemen" and r["of"] == 5


def test_half_split_and_momentum():
    assert analytics.half_split_trend([0, 0, 2, 2]) == 2.0
    assert analytics.momentum_band(0.6) == "hi" and analytics.momentum_band(0.0) == "md"
    assert "<svg" in analytics.line_spark_svg([1, 2, 3])


def test_film_clock_model_and_interpolation():
    """The estimator learns lead/stretch/intermission from hand anchors and interpolates between a
    game's own anchors; goals outside the anchored range extrapolate with the learned stretch."""
    import film_sync as fs
    goals = [{"team": "home", "period": "1", "time": "10:00"}, {"team": "away", "period": "1", "time": "5:00"},
             {"team": "home", "period": "2", "time": "10:00"}, {"team": "away", "period": "2", "time": "5:00"},
             {"team": "home", "period": "3", "time": "10:00"}, {"team": "away", "period": "3", "time": "5:00"}]
    game = {"goals": goals}
    truth = lambda g: 100 + 1.5 * fs._elapsed_s(g) + 120 * fs._period_index(g)
    anchors = {"goals": {}, "by_goal": [{**g, "video_t": int(truth(g))} for g in goals]}
    model = fs.learn_clock_model([(game, anchors)])
    assert abs(model["stretch"] - 1.5) < 0.01 and abs(model["intermission"] - 120) < 1 and model["anchors"] == 6
    pts = fs._anchor_points(game, anchors)
    mid = {"team": "home", "period": "2", "time": "7:30"}
    assert abs(fs._estimate_video_t(mid, 4000, model, pts) + fs.EST_LEAD_IN_S - truth(mid)) < 2
    late = {"team": "home", "period": "3", "time": "1:00"}
    assert abs(fs._estimate_video_t(late, 4000, model, pts) + fs.EST_LEAD_IN_S - truth(late)) < 2
    assert fs.learn_clock_model([]) == fs.DEFAULT_CLOCK_MODEL
