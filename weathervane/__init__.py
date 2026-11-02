"""Weathervane: a global weather and climate dashboard."""
from __future__ import annotations

import logging
from typing import Any, Optional

from flask import Flask, redirect, send_from_directory, url_for

from .config import Config

__version__ = "1.0.0"


def create_app(config: Optional[Config] = None, client: Any = None) -> Flask:
    """Application factory.

    ``client`` can be any object with a ``get_json(url, params, timeout)``
    method. Tests and demo mode inject ``DemoClient``; production uses ``HttpClient``.
    """
    from .api import bp as api_bp
    from .demo import DemoClient
    from .security import init_security
    from .services.hub import Hub
    from .services.http import HttpClient

    config = config or Config.from_env()
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["JSON_SORT_KEYS"] = False
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 300
    app.config["WV_DEMO"] = bool(config.demo or isinstance(client, DemoClient))
    app.json.sort_keys = False

    if client is None:
        client = DemoClient() if config.demo else HttpClient(config)
    app.extensions["weathervane"] = Hub(config, client)

    init_security(app, config.rate_limit_per_minute)
    app.register_blueprint(api_bp)

    @app.get("/")
    def index():
        response = send_from_directory(app.static_folder, "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="img/favicon.ico"), code=302)

    if not app.debug:
        logging.getLogger("weathervane").setLevel(logging.INFO)
    return app
