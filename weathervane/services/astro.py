"""Sun and moon calculations.

Sunrise and sunset come from the forecast provider. Moon phase is computed
locally from the mean synodic month, which is accurate to within about a day.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .meteo import num

SYNODIC_MONTH = 29.530588853  # days
# A reference new moon: 2000-01-06 18:14 UTC.
_NEW_MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)

_PHASE_NAMES = [
    "New moon", "Waxing crescent", "First quarter", "Waxing gibbous",
    "Full moon", "Waning gibbous", "Last quarter", "Waning crescent",
]


def parse_local(value: Any) -> Optional[datetime]:
    """Parse the provider's local wall-clock strings ("2026-10-10T14:00")."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def moon_info(local_now: Optional[datetime], utc_offset_seconds: Any, latitude: float) -> dict:
    offset = int(num(utc_offset_seconds) or 0)
    if local_now is None:
        instant = datetime.now(timezone.utc)
    else:
        instant = (local_now - timedelta(seconds=offset)).replace(tzinfo=timezone.utc)

    age_days = (instant - _NEW_MOON_EPOCH).total_seconds() / 86400.0
    cycle = (age_days % SYNODIC_MONTH) / SYNODIC_MONTH  # 0 = new, 0.5 = full
    illumination = (1 - math.cos(2 * math.pi * cycle)) / 2
    name = _PHASE_NAMES[int(cycle * 8 + 0.5) % 8]

    to_full = ((0.5 - cycle) % 1.0) * SYNODIC_MONTH
    to_new = ((0.0 - cycle) % 1.0) * SYNODIC_MONTH
    local_date = (local_now or instant.replace(tzinfo=None)).date()
    return {
        "phase": round(cycle, 4),
        "name": name,
        "illumination": round(illumination, 3),
        "age_days": round((cycle * SYNODIC_MONTH), 1),
        "next_full": (local_date + timedelta(days=round(to_full))).isoformat(),
        "next_new": (local_date + timedelta(days=round(to_new))).isoformat(),
        # In the southern hemisphere the lit side is mirrored.
        "mirrored": latitude < 0,
    }


def sun_info(
    sunrise: Any,
    sunset: Any,
    daylight_seconds: Any,
    local_now: Optional[datetime],
    tomorrow_daylight_seconds: Any = None,
) -> dict:
    rise, sett = parse_local(sunrise), parse_local(sunset)
    daylight = num(daylight_seconds)
    tomorrow = num(tomorrow_daylight_seconds)

    polar: Optional[str] = None
    if daylight is not None:
        if daylight >= 86300:
            polar = "day"
        elif daylight <= 0:
            polar = "night"

    info: dict = {
        "sunrise": sunrise if rise else None,
        "sunset": sunset if sett else None,
        "daylight_seconds": int(daylight) if daylight is not None else None,
        "daylight_change_seconds": (
            int(round(tomorrow - daylight)) if daylight is not None and tomorrow is not None else None
        ),
        "polar": polar,
        "progress": None,
        "solar_noon": None,
        "golden_morning": None,
        "golden_evening": None,
        "is_daytime": None,
    }
    if polar == "day":
        info["is_daytime"] = True
    elif polar == "night":
        info["is_daytime"] = False

    if rise and sett and sett > rise:
        noon = rise + (sett - rise) / 2
        info["solar_noon"] = noon.strftime("%Y-%m-%dT%H:%M")
        info["golden_morning"] = [
            rise.strftime("%Y-%m-%dT%H:%M"),
            (rise + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        ]
        info["golden_evening"] = [
            (sett - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            sett.strftime("%Y-%m-%dT%H:%M"),
        ]
        if local_now is not None:
            span = (sett - rise).total_seconds()
            progress = (local_now - rise).total_seconds() / span if span > 0 else None
            info["progress"] = None if progress is None else round(progress, 4)
            info["is_daytime"] = rise <= local_now <= sett
    return info
