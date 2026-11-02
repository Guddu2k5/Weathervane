"""Forecast agreement across independent weather models.

Operational forecasts come from different national centres running different
physics and data assimilation. When ECMWF, GFS, ICON and GEM agree, the forecast
is steadier; when they disagree, uncertainty is higher. This is a transparent
heuristic, **not** a calibrated probability.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..config import Config
from ..services.meteo import clamp, num

log = logging.getLogger(__name__)

MODELS = [
    ("ecmwf_ifs025", "ECMWF"),
    ("gfs_seamless", "NOAA GFS"),
    ("icon_seamless", "DWD ICON"),
    ("gem_seamless", "Canada GEM"),
]
DAYS = 7
RAIN_THRESHOLD_MM = 1.0


def fetch_models(client: Any, cfg: Config, lat: float, lon: float) -> dict:
    return client.get_json(cfg.forecast_url, {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,precipitation_sum",
        "models": ",".join(m for m, _ in MODELS),
        "timezone": "auto",
        "forecast_days": DAYS,
    })


def _label(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


def build_confidence(raw: dict) -> Optional[dict]:
    daily = raw.get("daily") if isinstance(raw, dict) else None
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        return None
    times = daily["time"]

    temps, rains, used = {}, {}, []
    for model_id, name in MODELS:
        t = daily.get(f"temperature_2m_max_{model_id}")
        p = daily.get(f"precipitation_sum_{model_id}")
        if isinstance(t, list) and any(num(v) is not None for v in t):
            temps[name] = t
            rains[name] = p if isinstance(p, list) else []
            used.append(name)
    if len(used) < 2:
        return None

    days = []
    for i, date_str in enumerate(times):
        highs = {m: num(temps[m][i]) for m in used if i < len(temps[m])}
        highs = {m: v for m, v in highs.items() if v is not None}
        if len(highs) < 2:
            continue
        spread = max(highs.values()) - min(highs.values())
        temp_score = clamp(100 - 12 * spread, 0, 100)

        wet = []
        for m in highs:
            amount = num(rains[m][i]) if i < len(rains[m]) else None
            if amount is not None:
                wet.append(amount >= RAIN_THRESHOLD_MM)
        if len(wet) >= 2:
            share = sum(wet) / len(wet)
            rain_score = (max(share, 1 - share) - 0.5) * 2 * 100
            rain_agreement = round(max(share, 1 - share), 2)
            score = 0.65 * temp_score + 0.35 * rain_score
        else:
            rain_agreement = None
            score = temp_score

        days.append({
            "date": date_str,
            "models_used": len(highs),
            "high_range": [round(min(highs.values()), 1), round(max(highs.values()), 1)],
            "spread": round(spread, 1),
            "rain_agreement": rain_agreement,
            "score": int(round(score)),
            "label": _label(score),
            "by_model": {m: round(v, 1) for m, v in highs.items()},
        })
    return {"models": used, "days": days}
