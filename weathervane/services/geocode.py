"""Place search (forward geocoding) and reverse lookup."""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Optional

from ..config import Config
from ..errors import ApiError, UpstreamError
from .meteo import num

log = logging.getLogger(__name__)

# "12.97, 77.59" / "12.97 77.59" / "-33.86,151.21"
_COORD_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")

_COUNTRY_CODES = {"PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "PCL", "TERR"}


def kind_for(feature_code: Optional[str], population: Optional[float]) -> str:
    """Map a GeoNames feature code to a friendly kind used by the UI."""
    code = (feature_code or "").upper()
    if code in _COUNTRY_CODES:
        return "country"
    if code == "ADM1":
        return "region"
    if code.startswith("ADM"):
        return "district"
    if code == "PPLC":
        return "capital"
    if code in {"PPLX", "PPLQ"}:
        return "neighbourhood"
    if code.startswith("PPL"):
        pop = population or 0
        if code.startswith("PPLA") or pop >= 100_000:
            return "city"
        return "town"
    return "place"


def make_label(*parts: Optional[str]) -> str:
    """Join non-empty, non-repeating parts: ("Delhi", "Delhi", "India") -> "Delhi, India"."""
    seen: list = []
    for part in parts:
        if part and part.strip() and part.strip() not in seen:
            seen.append(part.strip())
    return ", ".join(seen)


def parse_coordinates(query: str) -> Optional[tuple]:
    match = _COORD_RE.match(query or "")
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def _normalise(item: dict) -> Optional[dict]:
    lat, lon = num(item.get("latitude")), num(item.get("longitude"))
    name = item.get("name")
    if lat is None or lon is None or not name:
        return None
    population = num(item.get("population"))
    admin1, country = item.get("admin1"), item.get("country")
    kind = kind_for(item.get("feature_code"), population)
    # For an admin region or country the "admin1"/"country" parts repeat the name.
    return {
        "id": item.get("id"),
        "name": name,
        "admin1": admin1,
        "admin2": item.get("admin2"),
        "country": country,
        "country_code": item.get("country_code"),
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "elevation": num(item.get("elevation")),
        "timezone": item.get("timezone"),
        "population": int(population) if population else None,
        "kind": kind,
        "label": make_label(name, admin1, country),
    }


def search_places(client: Any, cfg: Config, query: str, count: int = 8, language: str = "en") -> list:
    """Search places by name, postal code or ``lat, lon``."""
    query = (query or "").strip()
    coords = parse_coordinates(query)
    if coords:
        lat, lon = coords
        return [{
            "id": None, "name": f"{lat:.4f}, {lon:.4f}", "admin1": None, "admin2": None,
            "country": None, "country_code": None, "lat": round(lat, 4), "lon": round(lon, 4),
            "elevation": None, "timezone": None, "population": None,
            "kind": "coordinates", "label": f"{lat:.4f}, {lon:.4f}",
        }]

    data = client.get_json(cfg.geocode_url, {
        "name": query, "count": max(1, min(count, 20)),
        "language": language, "format": "json",
    })
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return []
    out, seen = [], set()
    for item in results:
        place = _normalise(item) if isinstance(item, dict) else None
        if not place:
            continue
        key = (place["label"], round(place["lat"], 2), round(place["lon"], 2))
        if key in seen:
            continue
        seen.add(key)
        out.append(place)
    return out


# --------------------------------------------------------------------------- #
# Reverse geocoding (Nominatim). Their usage policy: identify yourself, cache,
# and send at most one request per second - enforced by the gate below.
# --------------------------------------------------------------------------- #
class _Gate:
    def __init__(self, interval: float = 1.1):
        self._interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self._interval - (time.monotonic() - self._last)
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


_gate = _Gate()


def _coordinate_place(lat: float, lon: float) -> dict:
    label = f"{abs(lat):.2f}\u00b0{'N' if lat >= 0 else 'S'}, {abs(lon):.2f}\u00b0{'E' if lon >= 0 else 'W'}"
    return {"name": "Pinned location", "admin1": None, "country": None,
            "country_code": None, "label": label, "resolved": False}


def reverse_place(client: Any, cfg: Config, lat: float, lon: float, use_gate: bool = True) -> dict:
    """Name a coordinate. Never raises: falls back to a coordinate label."""
    try:
        if use_gate:
            _gate.wait()
        data = client.get_json(cfg.reverse_url, {
            "format": "jsonv2", "lat": f"{lat:.5f}", "lon": f"{lon:.5f}",
            "zoom": 10, "accept-language": "en", "addressdetails": 1,
        })
    except ApiError as exc:
        log.info("reverse geocode failed: %s", exc)
        return _coordinate_place(lat, lon)

    address = data.get("address") if isinstance(data, dict) else None
    if not isinstance(address, dict):
        return _coordinate_place(lat, lon)

    name = next((address.get(k) for k in (
        "city", "town", "village", "municipality", "suburb", "hamlet",
        "city_district", "county", "state_district") if address.get(k)), None)
    admin1 = address.get("state") or address.get("region") or address.get("province")
    country = address.get("country")
    if not name:
        name = admin1 or country
        if not name:
            return _coordinate_place(lat, lon)
    return {
        "name": name,
        "admin1": admin1 if admin1 != name else None,
        "country": country if country != name else None,
        "country_code": (address.get("country_code") or "").upper() or None,
        "label": make_label(name, admin1, country),
        "resolved": True,
    }
