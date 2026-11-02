"""Orchestrates the ML insights for a location. Every part fails soft."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..config import Config
from ..services.meteo import num
from ..utils.cache import DiskCache
from . import anomaly, climate, confidence, history

log = logging.getLogger(__name__)

FORECAST_DAYS_ANALYSED = 7

METHOD = {
    "anomaly": "IsolationForest and a z-score fitted on 1991\u20132020 ERA5 reanalysis for the same time of year",
    "trend": "Linear regression (scikit-learn) on annual mean temperature since 1991, with a 95% confidence interval",
    "agreement": "Spread between ECMWF, NOAA GFS, DWD ICON and Canada GEM forecasts",
}


def _daily_inputs(raw: dict) -> list:
    daily = raw.get("daily") or {}
    times = daily.get("time") or []

    def col(name: str) -> list:
        values = daily.get(name)
        return values if isinstance(values, list) and len(values) == len(times) else [None] * len(times)

    highs, lows = col("temperature_2m_max"), col("temperature_2m_min")
    precip, wind = col("precipitation_sum"), col("wind_speed_10m_max")
    return [{"date": t, "high": num(highs[i]), "low": num(lows[i]),
             "precip": num(precip[i]), "wind": num(wind[i])} for i, t in enumerate(times)]


def _local_today(raw: dict) -> date:
    stamp = (raw.get("current") or {}).get("time")
    try:
        return datetime.fromisoformat(stamp).date()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).date()


def compute_insights(client: Any, cfg: Config, disk: DiskCache, lat: float, lon: float,
                     forecast_raw: dict) -> dict:
    today = _local_today(forecast_raw)
    inputs = [d for d in _daily_inputs(forecast_raw) if d["date"] >= today.isoformat()][:FORECAST_DAYS_ANALYSED]
    notes: list = []

    def run_history():
        hist = history.load_history(client, cfg, disk, lat, lon, today)
        return climate.climate_trend(hist, today.year), anomaly.analyse_days(hist, inputs)

    def run_models():
        return confidence.build_confidence(confidence.fetch_models(client, cfg, lat, lon))

    with ThreadPoolExecutor(max_workers=2) as pool:
        h_future, m_future = pool.submit(run_history), pool.submit(run_models)
        trend, days = None, []
        try:
            trend, days = h_future.result()
            if trend is None:
                notes.append("Not enough complete years of history to estimate a climate trend here.")
        except Exception as exc:  # fail soft: the forecast itself must never depend on this
            log.warning("climate history analysis failed: %s", exc, exc_info=not hasattr(exc, "code"))
            notes.append("Climate comparison is unavailable right now.")
        agreement = None
        try:
            agreement = m_future.result()
            if agreement is None:
                notes.append("Model comparison is unavailable for this location.")
        except Exception as exc:
            log.warning("model agreement failed: %s", exc, exc_info=not hasattr(exc, "code"))
            notes.append("Model comparison is unavailable right now.")

    by_date = {d["date"]: d for d in (agreement or {}).get("days", [])}
    merged = []
    seen = set()
    for item in days:
        merged.append({**item, "agreement": by_date.get(item["date"])})
        seen.add(item["date"])
    for date_str, item in by_date.items():
        if date_str not in seen:
            merged.append({"date": date_str, "agreement": item})
    merged.sort(key=lambda d: d["date"])

    return {
        "days": merged,
        "trend": trend,
        "models": (agreement or {}).get("models", []),
        "notes": notes,
        "method": METHOD,
    }
