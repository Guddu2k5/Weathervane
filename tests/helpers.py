from datetime import datetime
from weathervane import create_app
from weathervane.config import Config
from weathervane.demo import DemoClient

NOW = datetime(2026, 10, 10, 9, 30)


def demo_app(client=None, **cfg):
    cfg.setdefault("rate_limit_per_minute", 0)
    cfg.setdefault("cache_dir", "/tmp/wv-test-cache")
    client = client or DemoClient(now=NOW)
    return create_app(Config(demo=True, **cfg), client)
