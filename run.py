#!/usr/bin/env python3
"""Start Weathervane.

    python run.py                 # live data from Open-Meteo
    python run.py --demo          # offline demo with synthetic data
    python run.py --port 8080 --host 0.0.0.0
"""
from __future__ import annotations

import argparse
import dataclasses
import logging

from weathervane import create_app
from weathervane.config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Weathervane weather dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="port (default: 5000)")
    parser.add_argument("--demo", action="store_true", help="serve synthetic data, no internet needed")
    parser.add_argument("--debug", action="store_true", help="enable Flask debug mode and auto-reload")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    if args.demo:
        config = dataclasses.replace(config, demo=True)

    app = create_app(config)
    mode = "DEMO (synthetic data)" if config.demo else "live data"
    print(f"\n  Weathervane running with {mode}\n  Open http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
