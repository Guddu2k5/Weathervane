"""Load ~35 years of daily climate history (ERA5 reanalysis) for a place."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from ..config import Config
from ..errors import ApiError
from ..utils.cache import DiskCache

log = logging.getLogger(__name__)

START_YEAR = 1991               # WMO standard normal period starts here
BASELINE = (1991, 2020)         # WMO 30-year climate normal
ARCHIVE_LAG_DAYS = 8            # ERA5 lags real time by several days
MIN_ROWS = 3000                 # ~8 years; below this statistics are meaningless
DAILY_VARS = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"


@dataclass
class History:
    dates: np.ndarray      # datetime64[D]
    years: np.ndarray      # int
    doy: np.ndarray        # day of year, 1..366
    tmax: np.ndarray       # degC, NaN where missing
    tmin: np.ndarray
    precip: np.ndarray     # mm
    wind: np.ndarray       # km/h

    @property
    def tmean(self) -> np.ndarray:
        return (self.tmax + self.tmin) / 2.0


def _to_float(values: Any, length: int) -> np.ndarray:
    if not isinstance(values, list) or len(values) != length:
        return np.full(length, np.nan)
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def history_from_payload(payload: dict) -> History:
    times = payload.get("time")
    if not isinstance(times, list) or len(times) < MIN_ROWS:
        raise ApiError("Not enough climate history is available for this location.", 404, "no_history")
    n = len(times)
    dates = np.array(times, dtype="datetime64[D]")
    year_start = dates.astype("datetime64[Y]")
    years = year_start.astype(int) + 1970
    doy = (dates - year_start.astype("datetime64[D]")).astype(int) + 1
    return History(
        dates=dates, years=years, doy=doy,
        tmax=_to_float(payload.get("tmax"), n),
        tmin=_to_float(payload.get("tmin"), n),
        precip=_to_float(payload.get("precip"), n),
        wind=_to_float(payload.get("wind"), n),
    )


def load_history(client: Any, cfg: Config, disk: DiskCache, lat: float, lon: float,
                 today: date) -> History:
    # Round to 0.1 degrees (~11 km): finer than the reanalysis grid, and nearby
    # searches share one cached download.
    glat, glon = round(lat, 1), round(lon, 1)
    key = f"history:v1:{glat:.1f}:{glon:.1f}:{today.year}"
    cached = disk.get(key, cfg.history_ttl)
    if cached:
        try:
            return history_from_payload(cached)
        except (ApiError, ValueError, TypeError):
            log.warning("discarding unreadable cached history for %s", key)

    end = today - timedelta(days=ARCHIVE_LAG_DAYS)
    raw = client.get_json(cfg.archive_url, {
        "latitude": glat,
        "longitude": glon,
        "start_date": f"{START_YEAR}-01-01",
        "end_date": end.isoformat(),
        "daily": DAILY_VARS,
        "timezone": "auto",
    }, timeout=(cfg.connect_timeout, 90))  # a 35-year download can be slow
    daily = raw.get("daily") if isinstance(raw, dict) else None
    if not isinstance(daily, dict):
        raise ApiError("Climate history is unavailable for this location.", 404, "no_history")

    payload = {
        "time": daily.get("time"),
        "tmax": daily.get("temperature_2m_max"),
        "tmin": daily.get("temperature_2m_min"),
        "precip": daily.get("precipitation_sum"),
        "wind": daily.get("wind_speed_10m_max"),
    }
    history = history_from_payload(payload)  # validates before we cache
    disk.set(key, payload)
    return history
