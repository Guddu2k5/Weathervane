"""Application configuration, read from environment variables.

Every setting has a safe default, so the app runs with zero configuration.
Override any of them with ``WEATHERVANE_*`` environment variables.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_cache_dir() -> str:
    return os.path.join(tempfile.gettempdir(), "weathervane-cache")


@dataclass(frozen=True)
class Config:
    # Upstream services (all free, no API key required).
    forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    air_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    geocode_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    reverse_url: str = "https://nominatim.openstreetmap.org/reverse"

    # Identify ourselves politely to upstream services (required by Nominatim).
    user_agent: str = "Weathervane/1.0 (open-source weather dashboard)"

    # (connect, read) timeouts in seconds.
    connect_timeout: float = 5.0
    read_timeout: float = 25.0

    # Cache lifetimes in seconds.
    forecast_ttl: int = 600          # Open-Meteo refreshes about every 15 minutes
    air_ttl: int = 1800
    geocode_ttl: int = 86400
    reverse_ttl: int = 86400
    insights_ttl: int = 6 * 3600
    history_ttl: int = 7 * 86400     # 35 years of ERA5 history barely changes

    cache_dir: str = field(default_factory=_default_cache_dir)

    # Simple per-IP limit for /api/* so a public deployment stays polite.
    rate_limit_per_minute: int = 90

    forecast_days: int = 10
    demo: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        defaults = cls()
        return cls(
            user_agent=os.environ.get("WEATHERVANE_USER_AGENT", defaults.user_agent),
            forecast_ttl=_env_int("WEATHERVANE_FORECAST_TTL", defaults.forecast_ttl),
            air_ttl=_env_int("WEATHERVANE_AIR_TTL", defaults.air_ttl),
            cache_dir=os.environ.get("WEATHERVANE_CACHE_DIR", defaults.cache_dir),
            rate_limit_per_minute=_env_int(
                "WEATHERVANE_RATE_LIMIT", defaults.rate_limit_per_minute
            ),
            demo=_env_bool("WEATHERVANE_DEMO", False),
        )
