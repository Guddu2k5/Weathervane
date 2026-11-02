"""Small, dependency-free caches.

* ``TTLCache``  - thread-safe in-memory LRU with per-entry expiry and
  "single flight" loading, so ten simultaneous requests for the same place
  trigger one upstream call instead of ten.
* ``DiskCache`` - JSON files with a TTL, used for the 35-year climate history
  so a server restart does not re-download it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

_MISSING = object()


class TTLCache:
    def __init__(self, maxsize: int = 512, clock: Callable[[], float] = time.monotonic):
        self._maxsize = maxsize
        self._clock = clock
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.RLock()
        self._key_locks: dict[str, threading.Lock] = {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return default
            expires, value = item
            if expires <= self._clock():
                del self._data[key]
                return default
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._data[key] = (self._clock() + ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def _lock_for(self, key: str) -> threading.Lock:
        with self._lock:
            if len(self._key_locks) > 4096:
                # Drop locks nobody is holding so this dict cannot grow forever.
                self._key_locks = {k: l for k, l in self._key_locks.items() if l.locked()}
            lock = self._key_locks.get(key)
            if lock is None:
                lock = self._key_locks[key] = threading.Lock()
            return lock

    def get_or_set(self, key: str, ttl: float, factory: Callable[[], Any]) -> Any:
        hit = self.get(key, _MISSING)
        if hit is not _MISSING:
            return hit
        with self._lock_for(key):
            hit = self.get(key, _MISSING)
            if hit is not _MISSING:
                return hit
            value = factory()  # exceptions propagate and are never cached
            self.set(key, value, ttl)
            return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class DiskCache:
    """Best-effort JSON cache. Failures are logged and treated as cache misses."""

    def __init__(self, directory: str):
        self._dir = directory

    def _path(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
        return os.path.join(self._dir, f"{digest}.json")

    def get(self, key: str, ttl: float) -> Optional[Any]:
        path = self._path(key)
        try:
            if time.time() - os.path.getmtime(path) > ttl:
                return None
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("disk cache read failed for %s: %s", key, exc)
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(value, fh, separators=(",", ":"))
                os.replace(tmp, self._path(key))  # atomic on every platform
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except (OSError, TypeError, ValueError) as exc:
            log.warning("disk cache write failed for %s: %s", key, exc)
