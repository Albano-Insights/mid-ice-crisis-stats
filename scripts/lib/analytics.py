"""Small, dependency-free trend/sparkline helpers, following the user's standing dashboard design
template (see ~/code/dashboard-design-template.md): half-split trend as the primary "is this entity
improving or declining" signal, a composite momentum score as the default sort for every leaderboard,
and Python-generated inline SVG sparklines rather than client-side chart instances.

Deliberately plain Python (no numpy/scipy) -- the series here are at most a season's worth of games
(dozens of points), so this is simpler than adding a dependency for it.
"""
from __future__ import annotations

import math

MOMENTUM_SECONDARY_WEIGHT = 0.25
# Bucket thresholds for momentum's 3 visual bands (hi/md/lo). Calibrated to this league's scale --
# a half-split swing of ~0.5 points/game across a window is a real, noticeable hot/cold stretch for a
# beer-league scorer (unlike the NHL, where 0.3 of an NHL point/game is the template's own reference).
MOMENTUM_HOT_THRESHOLD = 0.5
MOMENTUM_COLD_THRESHOLD = -0.5


def rolling_average(values: list[float], window: int) -> list[float]:
    """Trailing rolling average, same length as `values` (early points average over fewer games)."""
    out = []
    for i in range(len(values)):
        lo = max(0, i + 1 - window)
        chunk = values[lo:i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def half_split_trend(values: list[float]) -> float:
    """Second-half mean minus first-half mean of a chronological series.

    This is the template's primary trend signal: cheap, needs no baseline, no model, no external
    reference. Reads as "within this window, is the entity improving or declining?"
    """
    n = len(values)
    if n < 2:
        return 0.0
    mid = n // 2
    if not mid:
        return 0.0
    fh, lh = values[:mid], values[mid:]
    return sum(lh) / len(lh) - sum(fh) / len(fh)


def momentum_score(primary: list[float], secondary: list[float]) -> float:
    """momentum = half_split(primary) + 0.25 * half_split(secondary), the default sort key for every
    leaderboard per the design template. `primary` is normally points, `secondary` goals (isolates
    recent finishing form as a lower-weight supporting signal)."""
    return round(half_split_trend(primary) + MOMENTUM_SECONDARY_WEIGHT * half_split_trend(secondary), 3)


def momentum_band(momentum: float) -> str:
    """Buckets a momentum score into 3 visual bands with a deadband in the middle -- most entities
    are not moving, and saying so plainly is more informative than a faint gradient tint."""
    if momentum >= MOMENTUM_HOT_THRESHOLD:
        return "hi"
    if momentum <= MOMENTUM_COLD_THRESHOLD:
        return "lo"
    return "md"


def trend_label(momentum: float) -> dict:
    """Human-facing {direction, label} for a momentum/trend value, direction matching momentum_band's
    3 bands (hot/steady/cold) so the front end can pick one badge class."""
    band = momentum_band(momentum)
    direction = {"hi": "hot", "lo": "cold", "md": "steady"}[band]
    sign = "+" if momentum >= 0 else ""
    label = f"{sign}{momentum:.2f}/gm" if direction != "steady" else "steady"
    return {"direction": direction, "value": momentum, "label": label}


def zscore(value: float, population: list[float]) -> float:
    """Standard score of `value` within `population`. 0.0 if the population has no spread."""
    n = len(population)
    if n < 2:
        return 0.0
    mean = sum(population) / n
    variance = sum((x - mean) ** 2 for x in population) / n
    stdev = math.sqrt(variance)
    return (value - mean) / stdev if stdev else 0.0


def line_spark_svg(values: list[float], w: int = 60, h: int = 18) -> str:
    """Inline SVG sparkline as a ready-to-embed HTML string (design template section 4.8) -- no JS,
    no chart instance, works directly inside a table cell. The stroke color itself encodes direction
    (last-third mean vs first-third mean), with a deadband to grey so a flat line doesn't read as a
    false signal.
    """
    v = [x for x in values if x is not None]
    if len(v) < 2:
        return ""
    mn, mx = min(v), max(v)
    rng = (mx - mn) or 0.001
    pts = [f"{round(i / (len(v) - 1) * w, 1)},{round(h - 2 - (x - mn) / rng * (h - 4), 1)}"
           for i, x in enumerate(v)]
    third = max(1, len(v) // 3)
    diff = sum(v[-third:]) / third - sum(v[:third]) / third
    color = "#3fb950" if diff > 0.05 else "#f85149" if diff < -0.05 else "#8b949e"
    path = " L ".join(pts)
    return (f'<svg width="{w}" height="{h}" style="display:inline-block;vertical-align:middle;">'
            f'<path d="M {path}" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')
