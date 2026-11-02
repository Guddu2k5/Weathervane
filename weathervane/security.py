"""Security headers and a small per-IP rate limiter."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from flask import Flask, Response, jsonify, request

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://unpkg.com",
    "style-src 'self' 'unsafe-inline' https://unpkg.com",
    "font-src 'self'",
    "img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


class RateLimiter:
    """Sliding-window limiter. Process-local; use a shared store behind many workers."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._hits: dict = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def check(self, key: str) -> float:
        """Return 0 if allowed, otherwise the seconds to wait."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1.0, self.window - (now - hits[0]))
            hits.append(now)
            if now - self._last_sweep > self.window:  # forget idle clients
                self._last_sweep = now
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    del self._hits[k]
            return 0.0


def init_security(app: Flask, rate_limit_per_minute: int) -> None:
    limiter = RateLimiter(rate_limit_per_minute) if rate_limit_per_minute > 0 else None

    @app.before_request
    def _limit():
        if limiter is None or not request.path.startswith("/api/") or request.path == "/api/health":
            return None
        wait = limiter.check(request.remote_addr or "unknown")
        if wait:
            response = jsonify({"error": {"code": "rate_limited",
                                          "message": "Too many requests. Please slow down and try again shortly."}})
            response.status_code = 429
            response.headers["Retry-After"] = str(int(wait) + 1)
            return response
        return None

    @app.after_request
    def _headers(response: Response) -> Response:
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response
