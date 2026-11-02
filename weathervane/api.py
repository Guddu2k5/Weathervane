"""HTTP API (JSON). Thin: validate input, call the hub, shape errors."""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from . import __version__
from .demo import SCENES, DemoClient
from .errors import ApiError

log = logging.getLogger(__name__)
bp = Blueprint("api", __name__, url_prefix="/api")

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_SNAPSHOT_PLACES = 12


def _hub():
    return current_app.extensions["weathervane"]


def _float_arg(name: str) -> float:
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        raise ApiError(f"Missing required parameter '{name}'.", 400, "missing_parameter")
    try:
        value = float(raw)
    except ValueError:
        raise ApiError(f"Parameter '{name}' must be a number.", 400, "invalid_parameter")
    if not math.isfinite(value):
        raise ApiError(f"Parameter '{name}' must be a finite number.", 400, "invalid_parameter")
    return value


def normalise_coords(lat: float, lon: float) -> tuple:
    if not -90 <= lat <= 90:
        raise ApiError("Latitude must be between -90 and 90.", 400, "invalid_coordinates")
    if not -720 <= lon <= 720:
        raise ApiError("Longitude must be between -180 and 180.", 400, "invalid_coordinates")
    lon = ((lon + 180) % 360) - 180  # a map panned across the date line can report 190
    return round(lat, 2), round(lon, 2)


def _coords() -> tuple:
    return normalise_coords(_float_arg("lat"), _float_arg("lon"))


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "version": __version__, "demo": current_app.config["WV_DEMO"]})


@bp.get("/search")
def search():
    query = _CONTROL.sub("", request.args.get("q", "")).strip()
    if len(query) < 2:
        raise ApiError("Type at least 2 characters to search.", 400, "query_too_short")
    if len(query) > 100:
        raise ApiError("That search is too long.", 400, "query_too_long")
    try:
        count = int(request.args.get("count", 8))
    except ValueError:
        raise ApiError("Parameter 'count' must be a whole number.", 400, "invalid_parameter")
    count = max(1, min(count, 15))
    language = request.args.get("lang", "en")
    if not re.fullmatch(r"[a-z]{2}", language):
        language = "en"
    return jsonify({"query": query, "results": _hub().search(query, count, language)})


@bp.get("/reverse")
def reverse():
    lat, lon = _coords()
    return jsonify({"place": _hub().reverse(lat, lon)})


@bp.get("/weather")
def weather():
    lat, lon = _coords()
    payload = _hub().weather(lat, lon)
    return jsonify({**payload, "meta": {**payload["meta"], "demo": current_app.config["WV_DEMO"]}})


@bp.get("/insights")
def insights():
    lat, lon = _coords()
    return jsonify(_hub().insights(lat, lon))


@bp.get("/snapshot")
def snapshot():
    raw = request.args.get("places", "")
    places = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(",")
        if len(parts) != 2:
            raise ApiError("Parameter 'places' must look like 'lat,lon;lat,lon'.", 400, "invalid_parameter")
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            raise ApiError("Parameter 'places' contains a value that is not a number.", 400, "invalid_parameter")
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ApiError("Parameter 'places' contains an invalid number.", 400, "invalid_parameter")
        places.append(normalise_coords(lat, lon))
    if not places:
        raise ApiError("Provide at least one place.", 400, "missing_parameter")
    if len(places) > MAX_SNAPSHOT_PLACES:
        raise ApiError(f"At most {MAX_SNAPSHOT_PLACES} places can be requested at once.", 400, "too_many_places")
    return jsonify({"items": _hub().snapshot(places)})


@bp.get("/_demo/scene")
def demo_scene():
    """Demo mode only: force the animated sky to a scene so every look can be previewed."""
    if not current_app.config["WV_DEMO"]:
        raise ApiError("Not found.", 404, "not_found")
    name = request.args.get("name", "")
    client = _hub().client
    if not isinstance(client, DemoClient):
        raise ApiError("Not found.", 404, "not_found")
    if name and name not in SCENES:
        raise ApiError("Scene must be one of: " + ", ".join(sorted(SCENES)), 400, "invalid_parameter")
    client.scene = name or None
    _hub().cache.clear()
    return jsonify({"scene": client.scene})


# ---- error handling ------------------------------------------------------------ #
@bp.errorhandler(ApiError)
def _api_error(exc: ApiError):
    return jsonify({"error": {"code": exc.code, "message": exc.message}}), exc.status


@bp.errorhandler(HTTPException)
def _http_error(exc: HTTPException):
    return jsonify({"error": {"code": exc.name.lower().replace(" ", "_"),
                              "message": exc.description or exc.name}}), exc.code or 500


@bp.errorhandler(Exception)
def _unexpected(exc: Exception):
    log.exception("unhandled error in %s", request.path)
    return jsonify({"error": {"code": "internal_error",
                              "message": "Something went wrong on our side. Please try again."}}), 500


@bp.app_errorhandler(404)
def _not_found(exc: Any):
    if request.path.startswith("/api/"):
        return jsonify({"error": {"code": "not_found", "message": "That API endpoint does not exist."}}), 404
    return exc, 404
