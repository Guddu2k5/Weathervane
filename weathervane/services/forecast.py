"""Fetch and normalise a forecast.

The provider returns parallel arrays keyed by variable name. This module turns
them into small, predictable dictionaries (metric units; the front end converts
for display) and layers on derived guidance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import Config
from ..errors import UpstreamError
from . import astro, guidance, wmo
from .meteo import (beaufort, compass, dew_point_comfort, feels_label,
                    num, pressure_trend, rnd, uv_label)

log = logging.getLogger(__name__)

CURRENT_VARS = ",".join([
    "temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day",
    "precipitation", "weather_code", "cloud_cover", "pressure_msl",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
])
HOURLY_VARS = ",".join([
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
    "precipitation_probability", "precipitation", "weather_code", "pressure_msl",
    "cloud_cover", "visibility", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "uv_index", "is_day",
])
DAILY_VARS = ",".join([
    "weather_code", "temperature_2m_max", "temperature_2m_min",
    "apparent_temperature_max", "apparent_temperature_min", "sunrise", "sunset",
    "daylight_duration", "sunshine_duration", "uv_index_max", "precipitation_sum",
    "precipitation_probability_max", "precipitation_hours", "wind_speed_10m_max",
    "wind_gusts_10m_max", "wind_direction_10m_dominant",
])

HOURS_SHOWN = 48


def fetch_forecast(client: Any, cfg: Config, lat: float, lon: float) -> dict:
    return client.get_json(cfg.forecast_url, {
        "latitude": lat,
        "longitude": lon,
        "current": CURRENT_VARS,
        "hourly": HOURLY_VARS,
        "daily": DAILY_VARS,
        "timezone": "auto",
        "forecast_days": cfg.forecast_days,
        "wind_speed_unit": "kmh",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
    })


def _column(block: dict, name: str, length: int) -> list:
    """A column from a provider block, padded/truncated to ``length``."""
    values = block.get(name)
    if not isinstance(values, list):
        return [None] * length
    if len(values) < length:
        values = values + [None] * (length - len(values))
    return values[:length]


def _hour_index(times: list, current_time: Optional[str]) -> int:
    """Index of the hour containing ``current_time`` (clamped to valid range)."""
    if not times:
        return 0
    if not current_time:
        return 0
    floor = current_time[:13] + ":00"
    try:
        return times.index(floor)
    except ValueError:
        pass
    # Fall back to the last hour that is not after the current time.
    idx = 0
    for i, t in enumerate(times):
        if isinstance(t, str) and t <= floor:
            idx = i
        else:
            break
    return idx


def build_forecast(raw: dict, lat: float, lon: float, air: Optional[dict] = None) -> dict:
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), dict) for k in ("current", "hourly", "daily")):
        raise UpstreamError("The weather data service returned an unexpected response.", 502, "upstream_invalid")

    cur, hr, dy = raw["current"], raw["hourly"], raw["daily"]
    times = hr.get("time")
    if not isinstance(times, list) or not times:
        raise UpstreamError("The weather data service returned no hourly data.", 502, "upstream_invalid")
    n = len(times)

    cols = {name: _column(hr, name, n) for name in (
        "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
        "precipitation_probability", "precipitation", "weather_code", "pressure_msl",
        "cloud_cover", "visibility", "wind_speed_10m", "wind_direction_10m",
        "wind_gusts_10m", "uv_index", "is_day")}

    idx = _hour_index(times, cur.get("time"))
    utc_offset = raw.get("utc_offset_seconds") or 0

    def hour_at(i: int) -> dict:
        is_day = bool(num(cols["is_day"][i]) or 0)
        cond = wmo.describe(cols["weather_code"][i], is_day)
        prob = num(cols["precipitation_probability"][i])
        wdir = num(cols["wind_direction_10m"][i])
        return {
            "time": times[i],
            "temp": rnd(cols["temperature_2m"][i]),
            "feels_like": rnd(cols["apparent_temperature"][i]),
            "humidity": rnd(cols["relative_humidity_2m"][i], 0),
            "dew_point": rnd(cols["dew_point_2m"][i]),
            "precip_prob": None if prob is None else int(round(prob)),
            "precip": rnd(cols["precipitation"][i], 2),
            "code": cond["code"],
            "condition": cond["label"],
            "icon": cond["icon"],
            "scene": cond["scene"],
            "wind": rnd(cols["wind_speed_10m"][i]),
            "gust": rnd(cols["wind_gusts_10m"][i]),
            "wind_dir": rnd(wdir, 0),
            "cloud": rnd(cols["cloud_cover"][i], 0),
            "visibility": rnd(cols["visibility"][i], 0),
            "pressure": rnd(cols["pressure_msl"][i]),
            "uv": rnd(cols["uv_index"][i]),
            "is_day": is_day,
        }

    hourly = [hour_at(i) for i in range(idx, min(n, idx + HOURS_SHOWN))]
    if not hourly:
        raise UpstreamError("The weather data service returned no usable hourly data.", 502, "upstream_invalid")
    now_hour = hourly[0]

    # ---- current conditions: prefer the live "current" block, fall back to the hour
    is_day_now = bool(num(cur.get("is_day")) if num(cur.get("is_day")) is not None else now_hour["is_day"])
    code_now = cur.get("weather_code") if num(cur.get("weather_code")) is not None else now_hour["code"]
    cond = wmo.describe(code_now, is_day_now)

    def pick(key: str, fallback: Any, digits: int = 1) -> Optional[float]:
        value = rnd(cur.get(key), digits)
        return value if value is not None else fallback

    wind_speed = pick("wind_speed_10m", now_hour["wind"])
    wind_dir = pick("wind_direction_10m", now_hour["wind_dir"], 0)
    temp_now = pick("temperature_2m", now_hour["temp"])
    feels_now = pick("apparent_temperature", now_hour["feels_like"])
    dew_now = now_hour["dew_point"]
    humidity_now = pick("relative_humidity_2m", now_hour["humidity"], 0)

    current = {
        "time": cur.get("time") or now_hour["time"],
        "temp": temp_now,
        "feels_like": feels_now,
        "feels_label": feels_label(feels_now),
        "humidity": humidity_now,
        "dew_point": dew_now,
        "dew_comfort": dew_point_comfort(dew_now),
        "pressure": pick("pressure_msl", now_hour["pressure"]),
        "pressure_trend": pressure_trend(cols["pressure_msl"], idx),
        "cloud": pick("cloud_cover", now_hour["cloud"], 0),
        "visibility": now_hour["visibility"],
        "uv": now_hour["uv"],
        "uv_label": uv_label(now_hour["uv"]),
        "precip": pick("precipitation", now_hour["precip"], 2),
        "wind": {
            "speed": wind_speed,
            "gust": pick("wind_gusts_10m", now_hour["gust"]),
            "dir": wind_dir,
            "compass": compass(wind_dir),
            "beaufort": beaufort(wind_speed),
        },
        "is_day": is_day_now,
        "code": cond["code"],
        "condition": cond["label"],
        "icon": cond["icon"],
        "scene": cond["scene"],
    }

    # ---- daily
    d_times = dy.get("time") or []
    m = len(d_times)
    dcols = {name: _column(dy, name, m) for name in (
        "weather_code", "temperature_2m_max", "temperature_2m_min",
        "apparent_temperature_max", "apparent_temperature_min", "sunrise", "sunset",
        "daylight_duration", "sunshine_duration", "uv_index_max", "precipitation_sum",
        "precipitation_probability_max", "precipitation_hours", "wind_speed_10m_max",
        "wind_gusts_10m_max", "wind_direction_10m_dominant")}

    daily = []
    for i in range(m):
        dcond = wmo.describe(dcols["weather_code"][i], True)
        prob = num(dcols["precipitation_probability_max"][i])
        wd = num(dcols["wind_direction_10m_dominant"][i])
        sun_s = num(dcols["sunshine_duration"][i])
        daily.append({
            "date": d_times[i],
            "code": dcond["code"],
            "condition": dcond["label"],
            "icon": dcond["icon"],
            "scene": dcond["scene"],
            "high": rnd(dcols["temperature_2m_max"][i]),
            "low": rnd(dcols["temperature_2m_min"][i]),
            "feels_high": rnd(dcols["apparent_temperature_max"][i]),
            "feels_low": rnd(dcols["apparent_temperature_min"][i]),
            "precip_sum": rnd(dcols["precipitation_sum"][i]),
            "precip_prob": None if prob is None else int(round(prob)),
            "precip_hours": rnd(dcols["precipitation_hours"][i]),
            "uv_max": rnd(dcols["uv_index_max"][i]),
            "uv_label": uv_label(dcols["uv_index_max"][i]),
            "wind_max": rnd(dcols["wind_speed_10m_max"][i]),
            "gust_max": rnd(dcols["wind_gusts_10m_max"][i]),
            "wind_dir": wd if wd is None else round(wd),
            "wind_compass": compass(wd),
            "sunrise": dcols["sunrise"][i],
            "sunset": dcols["sunset"][i],
            "daylight_seconds": rnd(dcols["daylight_duration"][i], 0),
            "sunshine_seconds": None if sun_s is None else round(sun_s),
        })

    # Match "today" to the location's local date, not blindly index 0.
    today_date = current["time"][:10]
    today_i = next((i for i, d in enumerate(daily) if d["date"] == today_date), 0)

    # ---- astronomy
    local_now = astro.parse_local(current["time"])
    sun = astro.sun_info(
        dcols["sunrise"][today_i] if m else None,
        dcols["sunset"][today_i] if m else None,
        dcols["daylight_duration"][today_i] if m else None,
        local_now,
        dcols["daylight_duration"][today_i + 1] if m and today_i + 1 < m else None,
    )
    moon = astro.moon_info(local_now, utc_offset, lat)

    # ---- guidance
    us_aqi = air["us_aqi"] if air else None
    alerts = guidance.build_alerts(hourly, daily[today_i:], air)
    rain = guidance.rain_outlook(hourly)
    window = guidance.best_outdoor_window(hourly, us_aqi)

    return {
        "location": {
            "lat": round(num(raw.get("latitude")) if num(raw.get("latitude")) is not None else lat, 4),
            "lon": round(num(raw.get("longitude")) if num(raw.get("longitude")) is not None else lon, 4),
            "elevation": rnd(raw.get("elevation"), 0),
            "timezone": raw.get("timezone"),
            "timezone_abbr": raw.get("timezone_abbreviation"),
            "utc_offset_seconds": int(utc_offset) if num(utc_offset) is not None else 0,
        },
        "current": current,
        "today": daily[today_i] if daily else None,
        "hourly": hourly,
        "daily": daily[today_i:],
        "sun": sun,
        "moon": moon,
        "air": air,
        "alerts": alerts,
        "guidance": {
            "rain": rain,
            "outfit": guidance.outfit(hourly),
            "outdoor": window,
        },
        "meta": {
            "source": "Open-Meteo",
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


# --------------------------------------------------------------------------- #
# Lightweight multi-place snapshot (for the saved-places strip)
# --------------------------------------------------------------------------- #
def get_snapshot(client: Any, cfg: Config, places: list) -> list:
    """Current temperature and condition for up to 12 ``(lat, lon)`` pairs."""
    if not places:
        return []
    raw = client.get_json(cfg.forecast_url, {
        "latitude": ",".join(f"{p[0]:.4f}" for p in places),
        "longitude": ",".join(f"{p[1]:.4f}" for p in places),
        "current": "temperature_2m,weather_code,is_day",
        "timezone": "auto",
    })
    items = raw if isinstance(raw, list) else [raw]  # one place -> object, many -> list
    out = []
    for place, item in zip(places, items):
        current = item.get("current") if isinstance(item, dict) else None
        if not isinstance(current, dict):
            out.append({"lat": place[0], "lon": place[1], "temp": None})
            continue
        cond = wmo.describe(current.get("weather_code"), bool(num(current.get("is_day")) or 0))
        out.append({
            "lat": place[0], "lon": place[1],
            "temp": rnd(current.get("temperature_2m")),
            "icon": cond["icon"], "condition": cond["label"],
        })
    return out
