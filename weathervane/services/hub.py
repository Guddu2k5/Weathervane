"""Service hub: wires the HTTP client, caches and domain services together."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from ..config import Config
from ..errors import ApiError
from ..ml import insights as ml_insights
from ..utils.cache import DiskCache, TTLCache
from . import air as air_service
from . import forecast as forecast_service
from . import geocode

log = logging.getLogger(__name__)


class Hub:
    def __init__(self, config: Config, client: Any):
        self.config = config
        self.client = client
        self.cache = TTLCache(maxsize=1024)
        self.disk = DiskCache(config.cache_dir)

    # ---- forecast -------------------------------------------------------- #
    def _raw_forecast(self, lat: float, lon: float) -> dict:
        key = f"raw:{lat:.2f}:{lon:.2f}"
        return self.cache.get_or_set(
            key, self.config.forecast_ttl,
            lambda: forecast_service.fetch_forecast(self.client, self.config, lat, lon))

    def _air(self, lat: float, lon: float) -> Optional[dict]:
        key = f"air:{lat:.2f}:{lon:.2f}"
        return self.cache.get_or_set(
            key, self.config.air_ttl,
            lambda: air_service.build_air(air_service.fetch_air(self.client, self.config, lat, lon)))

    def weather(self, lat: float, lon: float) -> dict:
        key = f"wx:{lat:.2f}:{lon:.2f}"
        return self.cache.get_or_set(key, self.config.forecast_ttl, lambda: self._build_weather(lat, lon))

    def _build_weather(self, lat: float, lon: float) -> dict:
        with ThreadPoolExecutor(max_workers=2) as pool:
            forecast_future = pool.submit(self._raw_forecast, lat, lon)
            air_future = pool.submit(self._air, lat, lon)
            raw = forecast_future.result()       # a forecast failure is fatal
            air = None
            try:
                air = air_future.result()
            except ApiError as exc:              # air quality is optional
                log.info("air quality unavailable for %.2f,%.2f: %s", lat, lon, exc)
            except Exception:
                log.exception("unexpected air quality failure")
        return forecast_service.build_forecast(raw, lat, lon, air)

    # ---- ML insights ------------------------------------------------------- #
    def insights(self, lat: float, lon: float) -> dict:
        key = f"ins:{lat:.2f}:{lon:.2f}"

        def build() -> dict:
            raw = self._raw_forecast(lat, lon)
            return ml_insights.compute_insights(self.client, self.config, self.disk, lat, lon, raw)

        return self.cache.get_or_set(key, self.config.insights_ttl, build)

    # ---- places -------------------------------------------------------------- #
    def search(self, query: str, count: int = 8, language: str = "en") -> list:
        key = f"geo:{language}:{count}:{query.strip().lower()}"
        return self.cache.get_or_set(
            key, self.config.geocode_ttl,
            lambda: geocode.search_places(self.client, self.config, query, count, language))

    def reverse(self, lat: float, lon: float) -> dict:
        key = f"rev:{lat:.2f}:{lon:.2f}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        place = geocode.reverse_place(self.client, self.config, lat, lon, use_gate=not self.config.demo)
        if place.get("resolved"):  # never cache a failed lookup for a day
            self.cache.set(key, place, self.config.reverse_ttl)
        return place

    def snapshot(self, places: list) -> list:
        key = "snap:" + ";".join(f"{a:.2f},{b:.2f}" for a, b in places)
        return self.cache.get_or_set(
            key, 300, lambda: forecast_service.get_snapshot(self.client, self.config, places))
