"""Player Spotlight: turns one skater's cross-league career page into "what caliber of player is this".

The league site's career page lists every team-season a player has ever been rostered on, in every
league the site hosts -- but it never says what *division* each of those teams was in, and raw
points mean nothing without that (8 points in A is not 8 points in D). So each stint is:

  1. pinned to a division by matching (team name, season) against the standings of every configured
     lookup league,
  2. percentile-ranked on points-per-game against every skater in that same division-season, and
  3. converted into a rung on one ladder (D=1 ... A=6, with +/-0.25 for Upper/Lower splits), pulled
     up or down by how the player ranked there: a 90th-percentile D stint grades like a mid-C3 one,
     a 10th-percentile C3 stint grades like a strong D one.

The caliber score is the GP- and recency-weighted mean of those rungs (a stint two years old counts
half), plus two things a points-only grade can't see: a small bonus for being kept on a roster at
the top tier season after season, and a with-vs-without-you goal-differential adjustment from our
own division's games. A player who dominates D and holds his own in C3 lands between the two, and
the label says so in plain words. Everything here is
self-referential to the player's own divisions -- no cross-league normalization beyond the shared
letter ladder, which is the one thing both adult leagues actually agree on.

Deliberately plain Python, same as analytics.py: the populations are a few dozen to a couple of
hundred skaters per division, so this doesn't earn a numpy dependency.
"""
from __future__ import annotations

import re

MIN_STINT_GP = 3          # a stint shorter than this is shown but doesn't move the grade
MIN_POPULATION_GP = 3     # same bar for the division population a stint is ranked within
TREND_WINDOWS = (5, 10, 20)

# Base rungs. Sub-divisions ("C2 Upper", "B1", "C2 Gold") shift by a quarter rung -- enough to
# order them, not enough to pretend the site's naming is more precise than it is.
_BASE_TIERS = {"D": 1.0, "C4": 1.5, "C3": 2.0, "C2": 3.0, "C1": 4.0, "B": 5.0, "A": 6.0}
_TIER_ORDER = ["D", "C3", "C2", "C1", "B", "A"]
_UPPER_WORDS = ("upper", "gold", "plat", "platinum", "1")
_LOWER_WORDS = ("lower", "bronze", "2")


def parse_tier(level_label: str | None) -> dict | None:
    """'Adult C2 Upper' -> {name: 'C2', rung: 3.25, label: 'C2 Upper'}; None when the division
    isn't on the letter ladder at all (40+, Free Agent League, tournaments, youth)."""
    if not level_label:
        return None
    text = level_label.replace("Adult", "").strip()
    low = text.lower()
    # Combined divisions sit between their two letters.
    if re.fullmatch(r"a\s*/\s*b", low):
        return {"name": "A/B", "rung": 5.5, "label": text}
    if re.fullmatch(r"b\s*/\s*c", low):
        return {"name": "B/C", "rung": 4.5, "label": text}
    m = re.match(r"^(c[1-4]|d|b|a)(?=$|[\s/0-9])\s*(.*)$", low)  # 'd1', 'b2' split into letter + sub-tier
    if not m:
        return None
    base = m.group(1).upper()
    rest = m.group(2).strip()
    rung = _BASE_TIERS[base]
    tokens = re.split(r"[\s/]+", rest) if rest else []  # trailing 'A'/'B' (Silver A, Bronze B) is ignored
    if any(t in _UPPER_WORDS for t in tokens):
        rung += 0.25
    elif any(t in _LOWER_WORDS for t in tokens):
        rung -= 0.25
    return {"name": base, "rung": rung, "label": text}


def _points_per_game(row: dict) -> float | None:
    gp = row.get("gp") or 0
    if gp < 1:
        return None
    return (row.get("pts") or 0) / gp


MIN_POSITION_POPULATION = 5  # same-position peers needed before ranking D against D only


def percentile_in_division(player_ppg: float, population: list[dict], position: str | None = None,
                           positions: dict[int, str] | None = None) -> dict | None:
    """Where a P/GP sits among every skater in the division with MIN_POPULATION_GP+ games:
    {pct (0-100), rank, of, division_avg_ppg, peers}. Ties split the difference so a big clump of
    zero-point players doesn't all read as 'better than half the league'.

    When the player's position is known AND enough of the division has a known position too, the
    comparison narrows to same-position peers (a defenseman ranked against defensemen) -- positions
    are hand-maintained, so this only kicks in where someone has done that work."""
    eligible = [p for p in population if (p.get("gp") or 0) >= MIN_POPULATION_GP]
    peers = "all skaters"
    if position and positions:
        same = [p for p in eligible if positions.get(p.get("player_id")) == position]
        if len(same) >= MIN_POSITION_POPULATION:
            eligible, peers = same, {"F": "forwards", "D": "defensemen"}.get(position, position)
    rates = [r for r in (_points_per_game(p) for p in eligible) if r is not None]
    if len(rates) < 5:
        return None
    below = sum(1 for r in rates if r < player_ppg - 1e-9)
    ties = sum(1 for r in rates if abs(r - player_ppg) <= 1e-9)
    n = len(rates)
    pct = 100.0 * (below + 0.5 * max(0, ties - 1)) / max(1, n - 1)
    rank = n - below - max(0, ties - 1)  # best case among ties, matches how a leaderboard would show it
    return {"pct": round(min(100.0, max(0.0, pct)), 1), "rank": rank, "of": n,
            "division_avg_ppg": round(sum(rates) / n, 2), "peers": peers}


PERCENTILE_PULL = 0.75  # rungs a 100th (or 0th) percentile stint moves off its division's rung
RECENCY_HALF_LIFE_DAYS = 730   # a stint two years old counts half as much as one from this month
PERSISTENCE_STEP = 0.15        # bonus per extra season kept on a roster at the player's top tier...
PERSISTENCE_CAP = 0.30         # ...capped, so a lifer doesn't drift up a whole rung on tenure alone
WOWY_WEIGHT = 0.25             # rungs at a +/-2 goals-per-game with-vs-without swing (clamped)
WOWY_MIN_GAMES = 3             # games dressed AND games missed needed before WOWY says anything
TRAJECTORY_WINDOW_DAYS = 365   # "recent" = stints ending within this of the player's latest game
TRAJECTORY_STEP = 0.25         # score delta that earns a rising/fading arrow


def stint_rung(tier_rung: float, pct: float) -> float:
    """A stint's contribution to the caliber score: the division's rung, pulled up by an elite
    percentile or down by a poor one (50th percentile = exactly the division's rung). The pull is
    sized so that dominating a division (~90th pct) grades like holding your own one rung up, and
    the bottom of a division grades like the top of the one below."""
    return tier_rung + (pct - 50.0) / 50.0 * PERCENTILE_PULL


def recency_weight(age_days: int | None) -> float:
    """Exponential decay on a stint's age (days between its last game and the player's latest game
    anywhere). None (undated stint) counts as old."""
    if age_days is None:
        return 0.25
    return 0.5 ** (max(0, age_days) / RECENCY_HALF_LIFE_DAYS)


def persistence_bonus(seasons_at_top_tier: int) -> float:
    """Being kept on a roster at a level, season after season, is evidence you belong there that
    a points-only grade can't see (stay-at-home D, checkers). Small and capped."""
    return min(PERSISTENCE_CAP, PERSISTENCE_STEP * max(0, seasons_at_top_tier - 1))


def wowy_adjustment(with_diff: float | None, without_diff: float | None) -> float | None:
    """Team goal differential per game with the player dressed minus without, clamped to +/-2 and
    scaled to at most WOWY_WEIGHT rungs. None when either side has too few games."""
    if with_diff is None or without_diff is None:
        return None
    swing = max(-2.0, min(2.0, with_diff - without_diff))
    return round(swing / 2.0 * WOWY_WEIGHT, 3)


def trajectory(recent: float | None, earlier: float | None) -> dict | None:
    """Recent-vs-earlier caliber: is the player's level rising, fading, or flat?"""
    if recent is None or earlier is None:
        return None
    delta = round(recent - earlier, 2)
    direction = "rising" if delta >= TRAJECTORY_STEP else "fading" if delta <= -TRAJECTORY_STEP else "flat"
    return {"recent": round(recent, 2), "earlier": round(earlier, 2), "delta": delta, "direction": direction}


def caliber_label(score: float) -> dict:
    """Score -> {tier, descriptor, label}. Bands are centered on each base rung (D = 0.5..1.5, ...),
    and the descriptor says where in the band it lands so 'Solid C3' and 'Top-end C3' read differently."""
    names = ["D", "C3", "C2", "C1", "B", "A"]
    rungs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    idx = min(range(len(rungs)), key=lambda i: abs(rungs[i] - score))
    if score > rungs[idx] + 0.5 and idx < len(rungs) - 1:
        idx += 1
    tier = names[idx]
    frac = score - (rungs[idx] - 0.5)  # 0..1 position inside the band
    descriptor = "Entry-level" if frac < 0.33 else "Solid" if frac < 0.67 else "Top-end"
    return {"tier": tier, "descriptor": descriptor, "label": f"{descriptor} {tier}"}


def confidence_for(graded_gp: int) -> str:
    return "high" if graded_gp >= 30 else "medium" if graded_gp >= 10 else "low"


def fit_vs_current(score: float, current_rung: float | None) -> dict | None:
    """How the grade compares with the division the player is in *right now*."""
    if current_rung is None:
        return None
    gap = score - current_rung
    if gap >= 0.5:
        return {"direction": "above", "gap": round(gap, 2),
                "text": "Producing above this division -- a candidate to play up."}
    if gap <= -0.5:
        return {"direction": "below", "gap": round(gap, 2),
                "text": "Producing below this division's median so far -- a depth role at this level."}
    return {"direction": "level", "gap": round(gap, 2), "text": "Right where the numbers say they belong."}


def window_stats(games: list[dict], n: int | None) -> dict:
    """Totals + P/GP over the last n games (None = all). `games` chronological, oldest first."""
    chunk = games if n is None else games[-n:]
    gp = len(chunk)
    g = sum(x.get("goals") or 0 for x in chunk)
    a = sum(x.get("assists") or 0 for x in chunk)
    pts = sum(x.get("pts") or 0 for x in chunk)
    return {"gp": gp, "goals": g, "assists": a, "points": pts,
            "points_per_game": round(pts / gp, 2) if gp else 0.0}


def ordinal(n: float) -> str:
    n = int(round(n))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def tier_sort_key(name: str | None) -> int:
    return _TIER_ORDER.index(name) if name in _TIER_ORDER else -1
