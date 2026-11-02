"""Rule-based guidance derived from forecast data.

Everything here is deterministic and unit-tested: alerts, outfit advice, the
"best time outdoors" score and the plain-language rain outlook.

Alerts are *derived from model data*; they are not official government
warnings and the UI says so.
"""
from __future__ import annotations

from typing import Any, Optional

from . import wmo
from .meteo import clamp, num

SEVERITY_ORDER = {"advisory": 1, "warning": 2, "danger": 3}


# --------------------------------------------------------------------------- #
# Rain outlook
# --------------------------------------------------------------------------- #
def _is_wet(hour: dict) -> bool:
    precip = num(hour.get("precip")) or 0.0
    code = hour.get("code")
    return precip >= 0.1 or (code in wmo.WET_CODES)


def _precip_kind(hours: list) -> str:
    codes = [h.get("code") for h in hours if _is_wet(h)]
    if any(c in wmo.THUNDER_CODES for c in codes):
        return "thunderstorms"
    if any(c in wmo.SNOW_CODES for c in codes):
        return "snow"
    if any(c in wmo.FREEZING_CODES for c in codes):
        return "freezing rain"
    temps = [num(h.get("temp")) for h in hours if _is_wet(h)]
    temps = [t for t in temps if t is not None]
    if codes and all(c is None for c in codes) and temps and max(temps) <= 0.5:
        return "snow"
    return "rain"


def rain_outlook(hours: list) -> dict:
    """Describe wet/dry for the next 24 hours. ``hours`` are normalised hourly dicts."""
    window = hours[:24]
    total = round(sum((num(h.get("precip")) or 0.0) for h in window), 1)
    probs = [num(h.get("precip_prob")) for h in window]
    probs = [p for p in probs if p is not None]
    peak_prob = int(max(probs)) if probs else None

    base = {"state": "dry", "kind": "rain", "start": None, "end": None,
            "peak_prob": peak_prob, "total_mm": total}
    if not window:
        return base

    wet_flags = [_is_wet(h) for h in window]
    if wet_flags[0]:
        end = next((window[i]["time"] for i, w in enumerate(wet_flags) if not w), None)
        run = [h for h, w in zip(window, wet_flags) if w]
        return {**base, "state": "wet-now", "kind": _precip_kind(run), "end": end}

    first = next((i for i, w in enumerate(wet_flags) if w), None)
    if first is None:
        return base
    end_idx = next((i for i in range(first, len(window)) if not wet_flags[i]), None)
    run = window[first:end_idx] if end_idx is not None else window[first:]
    return {
        **base,
        "state": "wet-later",
        "kind": _precip_kind(run),
        "start": window[first]["time"],
        "end": window[end_idx]["time"] if end_idx is not None else None,
    }


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
def _tier(value: float, tiers: list) -> Optional[tuple]:
    """tiers: [(threshold, severity, title)] ascending. Return the highest met."""
    hit = None
    for threshold, severity, title in tiers:
        if value >= threshold:
            hit = (severity, title)
    return hit


def _window(hours: list, predicate) -> tuple:
    idx = [i for i, h in enumerate(hours) if predicate(h)]
    if not idx:
        return None, None
    last = hours[idx[-1]]["time"]
    return hours[idx[0]]["time"], last


def build_alerts(hours: list, days: list, air: Optional[dict] = None) -> list:
    hours48 = hours[:48]
    alerts: list = []

    def add(kind: str, severity: str, title: str, detail: str, start=None, end=None):
        alerts.append({"kind": kind, "severity": severity, "title": title,
                       "detail": detail, "start": start, "end": end})

    # Heat
    feels = [num(h.get("feels_like")) for h in hours48]
    feels_valid = [f for f in feels if f is not None]
    if feels_valid:
        peak = max(feels_valid)
        hit = _tier(peak, [(35, "advisory", "Very hot"),
                           (40, "warning", "Dangerous heat"),
                           (52, "danger", "Extreme heat danger")])
        if hit:
            start, end = _window(hours48, lambda h: (num(h.get("feels_like")) or -99) >= 35)
            add("heat", hit[0], hit[1],
                "Feels-like temperatures will peak at {:.0f}\u00b0C. Drink water, limit midday exertion "
                "and check on people who are elderly or unwell.".format(peak), start, end)
        low = min(feels_valid)
        hit = _tier(-low, [(15, "advisory", "Very cold"),
                           (25, "warning", "Dangerous cold"),
                           (40, "danger", "Extreme cold danger")])
        if hit:
            start, end = _window(hours48, lambda h: (num(h.get("feels_like")) or 99) <= -15)
            add("cold", hit[0], hit[1],
                "Feels-like temperatures will fall to {:.0f}\u00b0C. Cover exposed skin; frostbite is "
                "possible in under 30 minutes at the low end.".format(low), start, end)

    # Wind
    gusts = [num(h.get("gust")) for h in hours48]
    gusts_valid = [g for g in gusts if g is not None]
    if gusts_valid:
        peak = max(gusts_valid)
        hit = _tier(peak, [(60, "advisory", "Strong winds"),
                           (90, "warning", "Damaging winds"),
                           (120, "danger", "Destructive winds")])
        if hit:
            start, end = _window(hours48, lambda h: (num(h.get("gust")) or 0) >= 60)
            add("wind", hit[0], hit[1],
                "Gusts up to {:.0f} km/h. Secure loose objects and take care when driving "
                "high-sided vehicles.".format(peak), start, end)

    # Rain intensity and daily totals
    hourly_rain = [num(h.get("precip")) or 0.0 for h in hours48]
    day_rain = [num(d.get("precip_sum")) or 0.0 for d in days[:2]]
    rain_hit = None
    if hourly_rain:
        rain_hit = _tier(max(hourly_rain), [(10, "advisory", "Heavy rain"),
                                            (20, "warning", "Intense downpours"),
                                            (50, "danger", "Extreme rainfall")])
    day_hit = _tier(max(day_rain) if day_rain else 0, [(50, "advisory", "Heavy rain"),
                                                       (100, "warning", "Flood risk"),
                                                       (200, "danger", "Severe flood risk")])
    best = max([h for h in (rain_hit, day_hit) if h], key=lambda h: SEVERITY_ORDER[h[0]], default=None)
    if best:
        start, end = _window(hours48, lambda h: (num(h.get("precip")) or 0) >= 2)
        add("rain", best[0], best[1],
            "Up to {:.0f} mm of rain in a day and {:.0f} mm in a single hour. Expect ponding on roads "
            "and possible local flooding.".format(max(day_rain) if day_rain else 0, max(hourly_rain) if hourly_rain else 0),
            start, end)

    # Thunderstorms
    codes = [h.get("code") for h in hours48]
    if any(c in (96, 99) for c in codes):
        start, end = _window(hours48, lambda h: h.get("code") in (96, 99))
        add("storm", "warning", "Severe thunderstorms",
            "Thunderstorms with hail are forecast. Stay indoors and away from windows during storms.",
            start, end)
    elif any(c == 95 for c in codes):
        start, end = _window(hours48, lambda h: h.get("code") == 95)
        add("storm", "advisory", "Thunderstorms possible",
            "Lightning is possible. If you hear thunder, go indoors.", start, end)

    # Snow and ice
    if any(c in (75, 86) for c in codes):
        start, end = _window(hours48, lambda h: h.get("code") in (75, 86))
        add("snow", "warning", "Heavy snow",
            "Heavy snowfall is forecast. Expect difficult travel and reduced visibility.", start, end)
    elif any(c == 73 for c in codes):
        start, end = _window(hours48, lambda h: h.get("code") == 73)
        add("snow", "advisory", "Snow", "Moderate snowfall is forecast. Allow extra travel time.", start, end)
    if any(c in wmo.FREEZING_CODES for c in codes):
        start, end = _window(hours48, lambda h: h.get("code") in wmo.FREEZING_CODES)
        add("ice", "warning", "Freezing rain",
            "Rain that freezes on contact can make roads and paths extremely slippery.", start, end)

    # Fog
    vis = [num(h.get("visibility")) for h in hours48]
    vis_valid = [v for v in vis if v is not None]
    if any(c in wmo.FOG_CODES for c in codes) or (vis_valid and min(vis_valid) < 1000):
        thick = vis_valid and min(vis_valid) < 200
        start, end = _window(hours48, lambda h: h.get("code") in wmo.FOG_CODES
                             or (num(h.get("visibility")) is not None and num(h.get("visibility")) < 1000))
        add("fog", "warning" if thick else "advisory",
            "Dense fog" if thick else "Fog",
            "Visibility may drop below {} m. Slow down and use dipped headlights.".format(200 if thick else 1000),
            start, end)

    # UV
    uv_days = [num(d.get("uv_max")) for d in days[:2]]
    uv_valid = [u for u in uv_days if u is not None]
    if uv_valid:
        hit = _tier(max(uv_valid), [(8, "advisory", "Very high UV"), (11, "warning", "Extreme UV")])
        if hit:
            add("uv", hit[0], hit[1],
                "UV index up to {:.0f}. Unprotected skin can burn in minutes; use SPF 30+, a hat and "
                "shade around midday.".format(max(uv_valid)))

    # Air quality
    if air and air.get("us_aqi") is not None:
        aqi = air["us_aqi"]
        hit = _tier(aqi, [(101, "advisory", "Poor air for sensitive groups"),
                          (151, "warning", "Unhealthy air"),
                          (201, "danger", "Very unhealthy air")])
        if hit:
            add("air", hit[0], hit[1],
                "US AQI is {:.0f}. {}".format(aqi, air.get("advice", "")))

    alerts.sort(key=lambda a: -SEVERITY_ORDER[a["severity"]])
    return alerts


# --------------------------------------------------------------------------- #
# Comfort, outfit, best time outdoors
# --------------------------------------------------------------------------- #
def outfit(hours: list) -> list:
    """Clothing and gear advice for the next 12 hours."""
    window = hours[:12]
    if not window:
        return []
    feels = [num(h.get("feels_like")) for h in window]
    feels = [f for f in feels if f is not None]
    if not feels:
        return []
    cold = min(feels)
    items: list = []
    if cold < -10:
        items.append("Insulated winter coat, thermal layers, hat, scarf and gloves")
    elif cold < 0:
        items.append("Heavy coat, warm layers, hat and gloves")
    elif cold < 8:
        items.append("Warm jacket and layers")
    elif cold < 15:
        items.append("Light jacket or a sweater")
    elif cold < 24:
        items.append("T-shirt with an optional light layer")
    elif cold < 30:
        items.append("Light, breathable clothing")
    else:
        items.append("Minimal, breathable clothing and plenty of water")

    probs = [num(h.get("precip_prob")) or 0 for h in window]
    codes = [h.get("code") for h in window]
    wet_snow = any(c in wmo.SNOW_CODES for c in codes)
    if wet_snow:
        items.append("Waterproof boots with good grip")
    if max(probs) >= 50 or any(c in wmo.RAIN_CODES | wmo.THUNDER_CODES for c in codes):
        items.append("Umbrella or waterproof jacket")
    elif max(probs) >= 30:
        items.append("Compact umbrella, just in case")
    gust = max([num(h.get("gust")) or 0 for h in window])
    if gust >= 40:
        items.append("Windproof outer layer")
    uv = max([(num(h.get("uv")) or 0) for h in window if h.get("is_day")] or [0])
    if uv >= 6:
        items.append("Sunscreen, sunglasses and a hat")
    return items


def hour_score(hour: dict, aqi_factor: float = 1.0) -> float:
    """0-100 outdoor suitability for one hour."""
    feels = num(hour.get("feels_like"))
    if feels is None:
        feels = num(hour.get("temp"))
    if feels is None:
        return 0.0
    if feels < 16:
        temp_f = max(0.0, 1 - (16 - feels) / 20)
    elif feels > 24:
        temp_f = max(0.0, 1 - (feels - 24) / 16)
    else:
        temp_f = 1.0

    prob = (num(hour.get("precip_prob")) or 0) / 100
    mm = num(hour.get("precip")) or 0
    rain_f = 1 - min(1.0, 0.8 * prob + 0.2 * min(1.0, mm / 2))

    wind = num(hour.get("wind")) or 0
    wind_f = 1 - 0.8 * clamp((wind - 15) / 35, 0, 1)

    uv = num(hour.get("uv")) or 0
    uv_f = 0.8 if uv >= 11 else 0.9 if uv >= 8 else 1.0
    return round(100 * temp_f * rain_f * wind_f * uv_f * aqi_factor, 1)


def aqi_factor(us_aqi: Optional[float]) -> float:
    if us_aqi is None:
        return 1.0
    for limit, factor in ((50, 1.0), (100, 0.9), (150, 0.7), (200, 0.45), (300, 0.25)):
        if us_aqi <= limit:
            return factor
    return 0.1


def score_label(score: float) -> str:
    if score >= 75:
        return "Excellent"
    if score >= 55:
        return "Good"
    if score >= 35:
        return "Fair"
    return "Poor"


def best_outdoor_window(hours: list, us_aqi: Optional[float] = None) -> Optional[dict]:
    """Best two-hour daylight window in the next 24 hours."""
    window = hours[:24]
    factor = aqi_factor(us_aqi)
    scores = [hour_score(h, factor) for h in window]
    day = [bool(h.get("is_day")) for h in window]

    best: Optional[tuple] = None
    for i in range(len(window) - 1):
        if day[i] and day[i + 1]:
            avg = (scores[i] + scores[i + 1]) / 2
            if best is None or avg > best[0]:
                best = (avg, i, 2)
    if best is None:  # fall back to the best single daylight hour
        singles = [(scores[i], i, 1) for i in range(len(window)) if day[i]]
        if not singles:
            return None
        best = max(singles)
    avg, i, span = best
    end_time = window[i + span]["time"] if i + span < len(window) else _plus_hour(window[i + span - 1]["time"])
    return {"start": window[i]["time"], "end": end_time,
            "score": round(avg), "label": score_label(avg)}


def _plus_hour(local_iso: str) -> str:
    from datetime import datetime, timedelta
    try:
        return (datetime.fromisoformat(local_iso) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return local_iso
