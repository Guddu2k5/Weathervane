"""Is this forecast normal for the time of year?

Two complementary views, both fitted on the WMO 1991-2020 climate normal:

1. A *temperature* z-score and percentile against the same calendar window.
2. An *IsolationForest* (unsupervised anomaly detection) over the joint
   behaviour of daily high, low, rainfall and wind. A day can be ordinary in each
   variable yet rare in combination (for example hot, windy and wet together),
   which a simple z-score cannot see.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from .history import BASELINE, History

WINDOW_DAYS = 10        # +/- days around the calendar date used to define "normal"
RECORD_WINDOW = 3
MIN_SAMPLES = 150
MIN_STD = 0.75          # floor on the standard deviation (degC) to avoid absurd z-scores


def _circular_distance(doy: np.ndarray, target: int) -> np.ndarray:
    d = np.abs(doy - target)
    return np.minimum(d, 366 - d)


def _temp_label(z: float) -> str:
    if z >= 2:
        return "Much warmer than normal"
    if z >= 1:
        return "Warmer than normal"
    if z <= -2:
        return "Much cooler than normal"
    if z <= -1:
        return "Cooler than normal"
    return "Typical for the season"


def _rarity_label(rarity: float) -> Optional[str]:
    if rarity >= 0.97:
        return "Highly unusual combination"
    if rarity >= 0.90:
        return "Unusual combination"
    return None


def analyse_day(hist: History, day: dict) -> Optional[dict]:
    """``day``: {date, high, low, precip, wind} in metric units."""
    high, low = day.get("high"), day.get("low")
    if high is None or low is None:
        return None
    try:
        when = date.fromisoformat(day["date"])
    except (KeyError, ValueError, TypeError):
        return None
    target = when.timetuple().tm_yday

    in_base = (hist.years >= BASELINE[0]) & (hist.years <= BASELINE[1])
    near = _circular_distance(hist.doy, target) <= WINDOW_DAYS
    mean_t = hist.tmean
    sel = near & in_base & np.isfinite(mean_t)
    if int(sel.sum()) < MIN_SAMPLES:
        return None

    base_mean_t = mean_t[sel]
    mu, sigma = float(base_mean_t.mean()), max(float(base_mean_t.std(ddof=1)), MIN_STD)
    forecast_t = (float(high) + float(low)) / 2.0
    z = (forecast_t - mu) / sigma
    percentile = float((base_mean_t <= forecast_t).mean() * 100)

    # Records over all years in a narrower window.
    rec = (_circular_distance(hist.doy, target) <= RECORD_WINDOW) & np.isfinite(hist.tmax) & np.isfinite(hist.tmin)
    record_high = record_low = None
    if rec.any():
        i_hi = int(np.argmax(np.where(rec, hist.tmax, -np.inf)))
        i_lo = int(np.argmin(np.where(rec, hist.tmin, np.inf)))
        record_high = {"value": round(float(hist.tmax[i_hi]), 1), "year": int(hist.years[i_hi])}
        record_low = {"value": round(float(hist.tmin[i_lo]), 1), "year": int(hist.years[i_lo])}

    rarity = None
    precip, wind = day.get("precip"), day.get("wind")
    candidates = {
        "high": (hist.tmax, float(high)),
        "low": (hist.tmin, float(low)),
        "rain": (np.sqrt(np.clip(hist.precip, 0, None)),
                 None if precip is None else float(np.sqrt(max(precip, 0.0)))),
        "wind": (hist.wind, None if wind is None else float(wind)),
    }
    cols = [k for k, (arr, val) in candidates.items()
            if val is not None and np.isfinite(arr[near & in_base]).mean() > 0.9]
    if len(cols) >= 2:
        data = np.column_stack([candidates[k][0][near & in_base] for k in cols])
        ok = np.isfinite(data).all(axis=1)
        data = data[ok]
        if len(data) >= MIN_SAMPLES:
            forest = IsolationForest(n_estimators=100, contamination="auto", random_state=42)
            forest.fit(data)
            train_scores = forest.score_samples(data)          # higher = more normal
            today_score = float(forest.score_samples(
                np.array([[candidates[k][1] for k in cols]]))[0])
            rarity = float((train_scores > today_score).mean())

    return {
        "date": day["date"],
        "normal_high": round(float(np.nanmean(hist.tmax[sel])), 1),
        "normal_low": round(float(np.nanmean(hist.tmin[sel])), 1),
        "anomaly_c": round(forecast_t - mu, 1),
        "z": round(z, 2),
        "percentile": round(percentile),
        "label": _temp_label(z),
        "rarity": None if rarity is None else round(rarity, 3),
        "unusual": None if rarity is None else _rarity_label(rarity),
        "record_high": record_high,
        "record_low": record_low,
        "samples": int(sel.sum()),
    }


def analyse_days(hist: History, days: list) -> list:
    out = []
    for day in days:
        result = analyse_day(hist, day)
        if result is not None:
            out.append(result)
    return out
