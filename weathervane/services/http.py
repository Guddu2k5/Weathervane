"""Resilient HTTP client for upstream data providers."""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 v1 and v2 both expose Retry here
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

from ..config import Config
from ..errors import UpstreamError

log = logging.getLogger(__name__)


class HttpClient:
    """Thin wrapper around ``requests`` with timeouts, retries and clean errors.

    Anything that talks to the internet goes through ``get_json`` so the rest of
    the code never sees a raw ``requests`` exception, and so the demo client can
    be swapped in with the same interface.
    """

    def __init__(self, config: Config):
        self._config = config
        self._session = requests.Session()
        retry = Retry(
            total=2,
            backoff_factor=0.4,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update(
            {"User-Agent": config.user_agent, "Accept": "application/json"}
        )

    def get_json(
        self,
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        timeout: Optional[tuple] = None,
    ) -> Any:
        timeout = timeout or (self._config.connect_timeout, self._config.read_timeout)
        try:
            response = self._session.get(url, params=params, timeout=timeout)
        except requests.Timeout:
            raise UpstreamError(
                "The weather data service took too long to respond. Try again in a moment.",
                504,
                "upstream_timeout",
            )
        except requests.RequestException as exc:
            log.warning("upstream request failed: %s", exc)
            raise UpstreamError(
                "Could not reach the weather data service. Check your internet connection.",
                502,
                "upstream_unreachable",
            )

        if response.status_code == 429:
            raise UpstreamError(
                "The free weather data service is busy right now. Try again in a minute.",
                503,
                "upstream_rate_limited",
            )

        try:
            data = response.json()
        except ValueError:
            data = None

        if response.status_code >= 400:
            reason = ""
            if isinstance(data, dict):
                reason = str(data.get("reason") or data.get("error") or "")[:200]
            log.warning("upstream %s returned %s: %s", url, response.status_code, reason)
            if response.status_code == 404:
                raise UpstreamError("No data is available for that location.", 404, "no_data")
            raise UpstreamError(
                "The weather data service rejected the request." + (f" ({reason})" if reason else ""),
                502,
                "upstream_rejected",
            )

        if data is None:
            raise UpstreamError(
                "The weather data service returned an unreadable response.", 502, "upstream_invalid"
            )
        if isinstance(data, dict) and data.get("error") is True:
            raise UpstreamError(
                "The weather data service reported an error: " + str(data.get("reason", "unknown"))[:200],
                502,
                "upstream_rejected",
            )
        return data
