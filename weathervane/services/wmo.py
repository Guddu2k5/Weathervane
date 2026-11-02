"""WMO weather interpretation codes -> plain-language conditions.

Open-Meteo reports conditions as WMO codes. Each maps to a label, an icon key
(the front end draws the icon) and a "scene" that drives the animated sky.
"""
from __future__ import annotations

from typing import Optional

# code: (label, icon, scene)
# Icons ending in "-day"/"-night" are resolved using is_day; others are shared.
_CODES = {
    0: ("Clear sky", "clear", "clear"),
    1: ("Mainly clear", "mostly-clear", "clear"),
    2: ("Partly cloudy", "partly", "cloudy"),
    3: ("Overcast", "overcast", "cloudy"),
    45: ("Fog", "fog", "fog"),
    48: ("Freezing fog", "fog", "fog"),
    51: ("Light drizzle", "drizzle", "rain"),
    53: ("Drizzle", "drizzle", "rain"),
    55: ("Heavy drizzle", "drizzle", "rain"),
    56: ("Light freezing drizzle", "sleet", "rain"),
    57: ("Freezing drizzle", "sleet", "rain"),
    61: ("Light rain", "rain", "rain"),
    63: ("Rain", "rain", "rain"),
    65: ("Heavy rain", "rain-heavy", "rain"),
    66: ("Light freezing rain", "sleet", "rain"),
    67: ("Freezing rain", "sleet", "rain"),
    71: ("Light snow", "snow", "snow"),
    73: ("Snow", "snow", "snow"),
    75: ("Heavy snow", "snow-heavy", "snow"),
    77: ("Snow grains", "snow", "snow"),
    80: ("Light rain showers", "showers", "rain"),
    81: ("Rain showers", "showers", "rain"),
    82: ("Violent rain showers", "rain-heavy", "rain"),
    85: ("Light snow showers", "snow", "snow"),
    86: ("Heavy snow showers", "snow-heavy", "snow"),
    95: ("Thunderstorm", "thunder", "storm"),
    96: ("Thunderstorm with hail", "thunder", "storm"),
    99: ("Severe thunderstorm with hail", "thunder", "storm"),
}

_DAY_NIGHT_ICONS = {"clear", "mostly-clear", "partly", "showers"}

SNOW_CODES = frozenset({71, 73, 75, 77, 85, 86})
RAIN_CODES = frozenset({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82})
THUNDER_CODES = frozenset({95, 96, 99})
FREEZING_CODES = frozenset({56, 57, 66, 67})
FOG_CODES = frozenset({45, 48})
WET_CODES = SNOW_CODES | RAIN_CODES | THUNDER_CODES


def describe(code: Optional[int], is_day: bool = True) -> dict:
    """Return ``{"code", "label", "icon", "scene"}`` for a WMO code."""
    try:
        code_int = int(code) if code is not None else None
    except (TypeError, ValueError):
        code_int = None
    entry = _CODES.get(code_int) if code_int is not None else None
    if entry is None:
        return {"code": code_int, "label": "Unknown", "icon": "overcast", "scene": "cloudy"}
    label, icon, scene = entry
    if icon in _DAY_NIGHT_ICONS:
        icon = f"{icon}-{'day' if is_day else 'night'}"
    return {"code": code_int, "label": label, "icon": icon, "scene": scene}
