"""Small, well-defined meteorology helpers (no I/O)."""
from __future__ import annotations

import bisect
import math
from typing import Any, Iterable, Optional

COMPASS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

# Beaufort scale. Upper bounds are in km/h; speed < bounds[i] means force i.
_BEAUFORT_BOUNDS = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
_BEAUFORT_LABELS = [
    "Calm", "Light air", "Light breeze", "Gentle breeze", "Moderate breeze",
    "Fresh breeze", "Strong breeze", "Near gale", "Gale", "Strong gale",
    "Storm", "Violent storm", "Hurricane force",
]


def num(value: Any) -> Optional[float]:
    """Coerce to a finite float, or ``None`` (JSON nulls, NaN and junk -> None)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def rnd(value: Any, digits: int = 1) -> Optional[float]:
    out = num(value)
    return None if out is None else round(out, digits)


def compass(degrees: Any) -> Optional[str]:
    deg = num(degrees)
    if deg is None:
        return None
    return COMPASS_16[int(round((deg % 360) / 22.5)) % 16]


def beaufort(speed_kmh: Any) -> Optional[dict]:
    speed = num(speed_kmh)
    if speed is None or speed < 0:
        return None
    force = bisect.bisect_right(_BEAUFORT_BOUNDS, speed)
    return {"force": force, "label": _BEAUFORT_LABELS[force]}


def uv_label(uv: Any) -> Optional[str]:
    value = num(uv)
    if value is None:
        return None
    if value < 3:
        return "Low"
    if value < 6:
        return "Moderate"
    if value < 8:
        return "High"
    if value < 11:
        return "Very high"
    return "Extreme"


def dew_point_comfort(dew_c: Any) -> Optional[str]:
    dew = num(dew_c)
    if dew is None:
        return None
    if dew < 10:
        return "Dry"
    if dew < 16:
        return "Comfortable"
    if dew < 18:
        return "Slightly humid"
    if dew < 21:
        return "Humid"
    if dew < 24:
        return "Muggy"
    return "Oppressive"


def feels_label(apparent_c: Any) -> Optional[str]:
    value = num(apparent_c)
    if value is None:
        return None
    if value < -10:
        return "Bitterly cold"
    if value < 0:
        return "Freezing"
    if value < 8:
        return "Cold"
    if value < 15:
        return "Cool"
    if value < 24:
        return "Comfortable"
    if value < 30:
        return "Warm"
    if value < 35:
        return "Hot"
    if value < 41:
        return "Very hot"
    return "Dangerously hot"


def pressure_trend(series: Iterable[Any], idx: int) -> Optional[str]:
    """Rising / falling / steady, from the change over the next three hours."""
    values = list(series)
    if idx < 0 or idx + 3 >= len(values):
        return None
    now, later = num(values[idx]), num(values[idx + 3])
    if now is None or later is None:
        return None
    delta = later - now
    if delta >= 3:
        return "Rising fast"
    if delta >= 1:
        return "Rising"
    if delta <= -3:
        return "Falling fast"
    if delta <= -1:
        return "Falling"
    return "Steady"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
