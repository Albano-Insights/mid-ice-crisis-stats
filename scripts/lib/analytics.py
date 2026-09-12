"""Small, dependency-free trend/regression helpers used to build sparklines and trend badges.

Deliberately plain Python (no numpy/scipy) -- the series here are at most a season's worth of games
(dozens of points), so a manual least-squares fit is simpler than adding a dependency for it.
"""
from __future__ import annotations

import math

# A slope is only worth calling out if it moves the metric by at least this fraction of its own
# mean over the window -- otherwise everything with any noise at all gets labeled "trending".
TREND_THRESHOLD_FRACTION = 0.08


def rolling_average(values: list[float], window: int) -> list[float]:
    """Trailing rolling average, same length as `values` (early points average over fewer games)."""
    out = []
    for i in range(len(values)):
        lo = max(0, i + 1 - window)
        chunk = values[lo:i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def ols_slope(values: list[float]) -> float:
    """Ordinary-least-squares slope of `values` against their index (0, 1, 2, ...).

    Returns 0.0 for fewer than 2 points or a zero-variance x (can't happen here since x is always
    0..n-1, but guarded anyway).
    """
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    den = sum((x - x_mean) ** 2 for x in xs)
    return num / den if den else 0.0


def classify_trend(values: list[float]) -> dict:
    """Summarizes a series as a trend: direction, slope, and a short human label.

    `values` should be a per-game (not cumulative) series, most-recent last -- e.g. points scored in
    each of a player's last N games. Direction is "hot"/"cold"/"steady" based on whether the fitted
    slope, projected across the window, moves the metric by more than TREND_THRESHOLD_FRACTION of its
    mean.
    """
    if len(values) < 3:
        return {"direction": "steady", "slope": 0.0, "label": "not enough games yet"}

    slope = ols_slope(values)
    mean = sum(values) / len(values)
    projected_swing = slope * (len(values) - 1)

    if mean == 0:
        direction = "hot" if slope > 0 else ("cold" if slope < 0 else "steady")
    else:
        ratio = projected_swing / mean if mean else 0
        if ratio >= TREND_THRESHOLD_FRACTION:
            direction = "hot"
        elif ratio <= -TREND_THRESHOLD_FRACTION:
            direction = "cold"
        else:
            direction = "steady"

    sign = "+" if slope >= 0 else ""
    return {
        "direction": direction,
        "slope": round(slope, 3),
        "label": f"{sign}{slope:.2f}/game" if direction != "steady" else "steady",
    }


def zscore(value: float, population: list[float]) -> float:
    """Standard score of `value` within `population`. 0.0 if the population has no spread."""
    n = len(population)
    if n < 2:
        return 0.0
    mean = sum(population) / n
    variance = sum((x - mean) ** 2 for x in population) / n
    stdev = math.sqrt(variance)
    return (value - mean) / stdev if stdev else 0.0
