"""Error types shared by services and the HTTP layer."""
from __future__ import annotations


class ApiError(Exception):
    """An error that is safe to show to the person using the app."""

    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class UpstreamError(ApiError):
    """A data provider (Open-Meteo, Nominatim) failed or was unreachable."""

    def __init__(self, message: str, status: int = 502, code: str = "upstream_error"):
        super().__init__(message, status, code)
