"""Air quality: normalise Open-Meteo's air-quality API and add health context."""
from __future__ import annotations

from typing import Any, Optional

from ..config import Config
from .astro import parse_local
from .meteo import num, rnd

AQ_CURRENT = ",".join([
    "us_aqi", "european_aqi", "pm10", "pm2_5", "carbon_monoxide",
    "nitrogen_dioxide", "sulphur_dioxide", "ozone", "dust",
])

# WHO 2021 24-hour guideline values in ug/m3 (CO: 4 mg/m3). Ozone is the
# 8-hour peak-season guideline. Shown as a yardstick, not a legal limit.
WHO_GUIDELINES = {
    "pm2_5": ("PM2.5", 15.0),
    "pm10": ("PM10", 45.0),
    "ozone": ("Ozone", 100.0),
    "nitrogen_dioxide": ("Nitrogen dioxide", 25.0),
    "sulphur_dioxide": ("Sulphur dioxide", 40.0),
    "carbon_monoxide": ("Carbon monoxide", 4000.0),
}

# US EPA categories: (upper bound, label, advice)
_US_BANDS = [
    (50, "Good", "Air quality is good. Enjoy time outdoors."),
    (100, "Moderate", "Acceptable for most people. Unusually sensitive people may want to take it easier outdoors."),
    (150, "Unhealthy for sensitive groups",
     "Children, older adults and people with asthma or heart conditions should limit long or intense outdoor activity."),
    (200, "Unhealthy",
     "Everyone may feel effects. Reduce prolonged outdoor exertion; sensitive groups should stay indoors."),
    (300, "Very unhealthy",
     "Avoid outdoor exertion. Keep windows closed and wear an N95/FFP2 mask if you must go out."),
    (10_000, "Hazardous", "Stay indoors with filtered air and avoid all outdoor activity."),
]

# European Air Quality Index bands.
_EU_BANDS = [
    (20, "Good"), (40, "Fair"), (60, "Moderate"),
    (80, "Poor"), (100, "Very poor"), (10_000, "Extremely poor"),
]


def us_category(aqi: Optional[float]) -> Optional[dict]:
    if aqi is None:
        return None
    for index, (limit, label, advice) in enumerate(_US_BANDS):
        if aqi <= limit:
            return {"level": index, "label": label, "advice": advice}
    return None


def eu_category(aqi: Optional[float]) -> Optional[str]:
    if aqi is None:
        return None
    for limit, label in _EU_BANDS:
        if aqi <= limit:
            return label
    return None


def fetch_air(client: Any, cfg: Config, lat: float, lon: float) -> dict:
    return client.get_json(cfg.air_url, {
        "latitude": lat,
        "longitude": lon,
        "current": AQ_CURRENT,
        "hourly": "us_aqi",
        "timezone": "auto",
        "forecast_days": 2,
    })


def build_air(raw: dict) -> Optional[dict]:
    """Return ``None`` when the provider has no air-quality data for the point."""
    current = raw.get("current") if isinstance(raw, dict) else None
    if not isinstance(current, dict):
        return None

    us_aqi = rnd(current.get("us_aqi"), 0)
    eu_aqi = rnd(current.get("european_aqi"), 0)
    if us_aqi is None and eu_aqi is None:
        return None

    pollutants = []
    for key, (label, guideline) in WHO_GUIDELINES.items():
        value = rnd(current.get(key), 1)
        if value is None:
            continue
        pollutants.append({
            "key": key, "label": label, "value": value, "unit": "\u00b5g/m\u00b3",
            "guideline": guideline, "ratio": round(value / guideline, 2),
        })
    dominant = max(pollutants, key=lambda p: p["ratio"])["label"] if pollutants else None

    category = us_category(us_aqi)
    hourly = []
    hr = raw.get("hourly") or {}
    times, values = hr.get("time") or [], hr.get("us_aqi") or []
    now = parse_local(current.get("time"))
    for t, v in zip(times, values):
        stamp = parse_local(t)
        if stamp is None or now is None:
            continue
        if stamp >= now.replace(minute=0, second=0, microsecond=0):
            hourly.append({"time": t, "us_aqi": rnd(v, 0)})
        if len(hourly) >= 24:
            break

    return {
        "us_aqi": us_aqi,
        "eu_aqi": eu_aqi,
        "category": category["label"] if category else None,
        "level": category["level"] if category else None,
        "advice": category["advice"] if category else None,
        "eu_category": eu_category(eu_aqi),
        "dominant": dominant,
        "pollutants": pollutants,
        "dust": rnd(current.get("dust"), 1),
        "hourly": hourly,
    }
