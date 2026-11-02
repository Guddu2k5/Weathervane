import copy, unittest
from datetime import date, datetime
import numpy as np

from weathervane.config import Config
from weathervane.demo import DemoClient
from weathervane.errors import UpstreamError
from weathervane.ml import anomaly, climate, confidence, history, insights
from weathervane.ml.history import History
from weathervane.services import forecast
from weathervane.utils.cache import DiskCache
from .helpers import NOW, demo_app

LAT, LON = 12.97, 77.59


def raw_forecast():
    return forecast.fetch_forecast(DemoClient(now=NOW), Config(demo=True), LAT, LON)


class ForecastBuildTests(unittest.TestCase):
    def test_structure(self):
        wx = forecast.build_forecast(raw_forecast(), LAT, LON)
        self.assertEqual(len(wx["hourly"]), 48)
        self.assertEqual(wx["hourly"][0]["time"][:13], "2026-10-10T15")  # 09:30 UTC is 15:00 in UTC+5:30
        self.assertEqual(wx["daily"][0]["date"], "2026-10-10")
        self.assertGreaterEqual(len(wx["daily"]), 9)
        self.assertEqual(wx["location"]["utc_offset_seconds"], 19800)
        for key in ("current", "sun", "moon", "alerts", "guidance", "meta"):
            self.assertIn(key, wx)
        c = wx["current"]
        self.assertIsNotNone(c["temp"]); self.assertIn(c["scene"], {"clear", "cloudy", "rain", "snow", "storm", "fog"})

    def test_survives_nulls_and_missing_columns(self):
        raw = raw_forecast()
        for col in ("visibility", "uv_index", "precipitation_probability", "wind_gusts_10m"):
            raw["hourly"][col] = [None] * len(raw["hourly"]["time"])
        del raw["hourly"]["dew_point_2m"]
        raw["daily"]["sunrise"] = [None] * len(raw["daily"]["time"])
        raw["current"].pop("wind_gusts_10m")
        wx = forecast.build_forecast(raw, LAT, LON)
        self.assertIsNone(wx["hourly"][0]["precip_prob"]); self.assertIsNone(wx["sun"]["sunrise"])

    def test_short_arrays_do_not_crash(self):
        raw = raw_forecast()
        raw["hourly"]["temperature_2m"] = raw["hourly"]["temperature_2m"][:5]
        forecast.build_forecast(raw, LAT, LON)

    def test_bad_payloads_raise_clean_error(self):
        for bad in ({}, {"current": {}, "hourly": {}, "daily": {}}, None, []):
            with self.assertRaises(UpstreamError): forecast.build_forecast(bad, LAT, LON)

    def test_current_time_not_in_hourly_falls_back(self):
        raw = raw_forecast(); raw["current"]["time"] = "2026-10-10T09:15"
        self.assertEqual(forecast.build_forecast(raw, LAT, LON)["hourly"][0]["time"], "2026-10-10T09:00")
        raw["current"]["time"] = "1999-01-01T00:00"
        forecast.build_forecast(raw, LAT, LON)

    def test_no_nan_in_json(self):
        import json
        wx = forecast.build_forecast(raw_forecast(), LAT, LON)
        json.dumps(wx, allow_nan=False)  # raises on NaN/Infinity

    def test_snapshot_handles_single_and_multi(self):
        c, cfg = DemoClient(now=NOW), Config(demo=True)
        one = forecast.get_snapshot(c, cfg, [(LAT, LON)]); many = forecast.get_snapshot(c, cfg, [(LAT, LON), (51.5, -0.12)])
        self.assertEqual(len(one), 1); self.assertEqual(len(many), 2); self.assertIsNotNone(many[1]["temp"])


def synthetic_history(slope_per_year=0.03, noise=0.8, seed=3):
    rng = np.random.default_rng(seed)
    dates = np.arange("1991-01-01", "2025-10-01", dtype="datetime64[D]")
    ys = dates.astype("datetime64[Y]"); years = ys.astype(int) + 1970
    doy = (dates - ys.astype("datetime64[D]")).astype(int) + 1
    mean = 20 + 8 * np.cos(2 * np.pi * (doy - 200) / 365) + slope_per_year * (years - 1991) + rng.normal(0, noise, len(dates)) * 2.5
    tmax, tmin = mean + 4, mean - 4
    return History(dates, years, doy, tmax, tmin, np.abs(rng.gamma(0.4, 6, len(dates))), np.abs(rng.normal(15, 5, len(dates))))


class ClimateTests(unittest.TestCase):
    def test_recovers_planted_trend_inside_confidence_interval(self):
        t = climate.climate_trend(synthetic_history(0.03), 2026)
        self.assertEqual(t["verdict"], "warming")
        self.assertLessEqual(t["ci_low_per_decade"], 0.30); self.assertGreaterEqual(t["ci_high_per_decade"], 0.30)
        self.assertLess(t["p_value"], 0.01); self.assertEqual(t["n_years"], 34)  # 1991..2024 complete

    def test_flat_series_is_inconclusive_not_a_fake_trend(self):
        verdicts = {climate.climate_trend(synthetic_history(0.0, seed=s), 2026)["verdict"] for s in range(8)}
        self.assertIn("inconclusive", verdicts)
        self.assertLessEqual(sum(v == "warming" for v in [climate.climate_trend(synthetic_history(0.0, seed=s), 2026)["verdict"] for s in range(20)]), 3)  # ~5% false positive rate

    def test_cooling_detected(self):
        self.assertEqual(climate.climate_trend(synthetic_history(-0.04), 2026)["verdict"], "cooling")

    def test_too_little_history_returns_none(self):
        h = synthetic_history(); keep = h.years >= 2015
        short = History(*(getattr(h, f)[keep] for f in ("dates", "years", "doy", "tmax", "tmin", "precip", "wind")))
        self.assertIsNone(climate.climate_trend(short, 2026))

    def test_incomplete_years_excluded(self):
        h = synthetic_history(); h.tmax[h.years == 2000] = np.nan
        t = climate.climate_trend(h, 2026); self.assertNotIn(2000, [s["year"] for s in t["series"]])


class AnomalyTests(unittest.TestCase):
    def setUp(self): self.h = synthetic_history()

    def day(self, **k):
        d = {"date": "2026-07-19", "high": 24 + 4 - 4, "low": 20, "precip": 1.0, "wind": 15.0}; d.update(k); return d

    def test_normal_day_is_typical(self):
        typical = anomaly.analyse_day(self.h, {"date": "2026-07-19", "high": 32.4, "low": 24.4, "precip": 1, "wind": 15})
        self.assertLess(abs(typical["z"]), 1.0); self.assertEqual(typical["label"], "Typical for the season")

    def test_heatwave_flagged(self):
        hot = anomaly.analyse_day(self.h, {"date": "2026-07-19", "high": 44, "low": 33, "precip": 0, "wind": 40})
        self.assertGreater(hot["z"], 2); self.assertEqual(hot["label"], "Much warmer than normal")
        self.assertGreaterEqual(hot["rarity"], 0.97); self.assertIn("unusual", hot["unusual"].lower())

    def test_cold_snap_flagged(self):
        cold = anomaly.analyse_day(self.h, {"date": "2026-07-19", "high": 12, "low": 3, "precip": 0, "wind": 10})
        self.assertLess(cold["z"], -2); self.assertEqual(cold["label"], "Much cooler than normal")

    def test_isolation_forest_sees_joint_oddness(self):
        # Each value is individually plausible but the combination (cool high with very warm low) is not.
        odd = anomaly.analyse_day(self.h, {"date": "2026-07-19", "high": 24, "low": 30, "precip": 0, "wind": 15})
        self.assertGreater(odd["rarity"], 0.9)

    def test_deterministic(self):
        d = {"date": "2026-07-19", "high": 31, "low": 22, "precip": 2, "wind": 20}
        self.assertEqual(anomaly.analyse_day(self.h, d), anomaly.analyse_day(self.h, d))

    def test_missing_inputs_skip_safely(self):
        self.assertIsNone(anomaly.analyse_day(self.h, {"date": "2026-07-19", "high": None, "low": 20}))
        self.assertIsNone(anomaly.analyse_day(self.h, {"date": "garbage", "high": 20, "low": 10}))
        r = anomaly.analyse_day(self.h, {"date": "2026-07-19", "high": 30, "low": 20, "precip": None, "wind": None})
        self.assertIsNotNone(r)  # still gives the temperature z-score without the forest

    def test_year_boundary_window(self):
        self.assertIsNotNone(anomaly.analyse_day(self.h, {"date": "2026-01-02", "high": 20, "low": 10, "precip": 0, "wind": 10}))
        self.assertIsNotNone(anomaly.analyse_day(self.h, {"date": "2026-12-30", "high": 20, "low": 10, "precip": 0, "wind": 10}))


class ConfidenceTests(unittest.TestCase):
    @staticmethod
    def payload(highs_by_model, rain_by_model):
        d = {"time": ["2026-10-10"]}
        for m, h in highs_by_model.items():
            d[f"temperature_2m_max_{m}"] = [h]; d[f"precipitation_sum_{m}"] = [rain_by_model[m]]
        return {"daily": d}

    def test_agreement_high_vs_low(self):
        ids = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless"]
        agree = confidence.build_confidence(self.payload(dict(zip(ids, [28, 28.2, 27.9, 28.1])), dict.fromkeys(ids, 0.0)))
        split = confidence.build_confidence(self.payload(dict(zip(ids, [22, 30, 25, 33])), dict(zip(ids, [0, 8, 0, 9]))))
        self.assertEqual(agree["days"][0]["label"], "High"); self.assertEqual(split["days"][0]["label"], "Low")
        self.assertGreater(agree["days"][0]["score"], split["days"][0]["score"])

    def test_needs_two_models(self):
        self.assertIsNone(confidence.build_confidence(self.payload({"ecmwf_ifs025": 20}, {"ecmwf_ifs025": 0})))
        self.assertIsNone(confidence.build_confidence({})); self.assertIsNone(confidence.build_confidence({"daily": {"time": []}}))

    def test_nulls_ignored(self):
        p = self.payload({"ecmwf_ifs025": 20, "gfs_seamless": None, "icon_seamless": 21}, {"ecmwf_ifs025": 0, "gfs_seamless": None, "icon_seamless": 0})
        self.assertEqual(confidence.build_confidence(p)["days"][0]["models_used"], 2)


class InsightsPipelineTests(unittest.TestCase):
    def setUp(self):
        import tempfile; self.disk = DiskCache(tempfile.mkdtemp()); self.cfg = Config(demo=True)

    def test_end_to_end_demo(self):
        out = insights.compute_insights(DemoClient(now=NOW), self.cfg, self.disk, LAT, LON, raw_forecast())
        self.assertGreaterEqual(len(out["days"]), 6); self.assertEqual(out["notes"], [])
        self.assertEqual(out["trend"]["verdict"], "warming")
        self.assertTrue(0.2 <= out["trend"]["ci_low_per_decade"] <= 0.35 <= out["trend"]["ci_high_per_decade"] <= 0.5)  # demo plants 0.35/decade
        self.assertIn("agreement", out["days"][0])

    def test_history_is_cached_to_disk(self):
        calls = []
        class Counting(DemoClient):
            def get_json(s, url, params=None, timeout=None):
                if "archive" in url: calls.append(1)
                return super().get_json(url, params, timeout)
        c = Counting(now=NOW)
        history.load_history(c, self.cfg, self.disk, LAT, LON, date(2026, 10, 10)); history.load_history(c, self.cfg, self.disk, LAT, LON, date(2026, 10, 10))
        self.assertEqual(len(calls), 1)

    def test_fails_soft_when_providers_down(self):
        class Down(DemoClient):
            def get_json(s, url, params=None, timeout=None):
                if "archive" in url or "models" in (params or {}): raise UpstreamError("down")
                return super().get_json(url, params, timeout)
        out = insights.compute_insights(Down(now=NOW), self.cfg, self.disk, LAT, LON, raw_forecast())
        self.assertIsNone(out["trend"]); self.assertEqual(out["days"], []); self.assertEqual(len(out["notes"]), 2)

    def test_only_models_down_keeps_climate(self):
        class NoModels(DemoClient):
            def get_json(s, url, params=None, timeout=None):
                if "models" in (params or {}): raise UpstreamError("down")
                return super().get_json(url, params, timeout)
        out = insights.compute_insights(NoModels(now=NOW), self.cfg, self.disk, LAT, LON, raw_forecast())
        self.assertIsNotNone(out["trend"]); self.assertTrue(out["days"])


class ApiTests(unittest.TestCase):
    def setUp(self): self.c = demo_app().test_client()

    def test_health_and_headers(self):
        r = self.c.get("/api/health"); self.assertEqual(r.get_json()["status"], "ok")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff"); self.assertEqual(r.headers["X-Frame-Options"], "DENY")

    def test_index_served(self):
        r = self.c.get("/"); self.assertEqual(r.status_code, 200); self.assertIn(b"Weathervane", r.data)

    def test_weather_ok(self):
        r = self.c.get("/api/weather?lat=12.97&lon=77.59"); d = r.get_json()
        self.assertEqual(r.status_code, 200); self.assertTrue(d["meta"]["demo"]); self.assertEqual(len(d["hourly"]), 48)

    def test_validation_errors(self):
        for url, code in [("/api/weather", "missing_parameter"), ("/api/weather?lat=abc&lon=1", "invalid_parameter"),
                          ("/api/weather?lat=95&lon=1", "invalid_coordinates"), ("/api/weather?lat=nan&lon=1", "invalid_parameter"),
                          ("/api/weather?lat=1&lon=9999", "invalid_coordinates"), ("/api/search?q=a", "query_too_short"),
                          ("/api/search?q=" + "x" * 101, "query_too_long"), ("/api/search?q=ab&count=x", "invalid_parameter"),
                          ("/api/snapshot", "missing_parameter"), ("/api/snapshot?places=1,2,3", "invalid_parameter"),
                          ("/api/snapshot?places=" + ";".join(["1,1"] * 13), "too_many_places")]:
            r = self.c.get(url); self.assertEqual(r.status_code, 400, url); self.assertEqual(r.get_json()["error"]["code"], code, url)

    def test_longitude_wraps(self):
        self.assertEqual(self.c.get("/api/weather?lat=10&lon=190").status_code, 200)

    def test_unknown_api_route_is_json_404(self):
        r = self.c.get("/api/nope"); self.assertEqual(r.status_code, 404); self.assertEqual(r.get_json()["error"]["code"], "not_found")

    def test_search_and_reverse(self):
        self.assertTrue(self.c.get("/api/search?q=tokyo").get_json()["results"])
        self.assertEqual(self.c.get("/api/search?q=zzzzzz").get_json()["results"], [])
        self.assertTrue(self.c.get("/api/reverse?lat=35.7&lon=139.7").get_json()["place"]["resolved"])
        self.assertFalse(self.c.get("/api/reverse?lat=0&lon=-140").get_json()["place"]["resolved"])

    def test_upstream_failures_become_clean_json(self):
        class Down:
            def get_json(self, *a, **k): raise UpstreamError("nope", 503, "upstream_rate_limited")
        c = demo_app(client=Down()).test_client()
        r = c.get("/api/weather?lat=1&lon=1"); self.assertEqual(r.status_code, 503); self.assertEqual(r.get_json()["error"]["code"], "upstream_rate_limited")

    def test_unexpected_exception_hides_internals(self):
        class Boom:
            def get_json(self, *a, **k): raise ZeroDivisionError("secret internal detail")
        c = demo_app(client=Boom()).test_client()
        r = c.get("/api/weather?lat=1&lon=1"); self.assertEqual(r.status_code, 500)
        self.assertNotIn("secret", r.get_data(as_text=True))

    def test_air_outage_does_not_break_forecast(self):
        class NoAir(DemoClient):
            def get_json(s, url, params=None, timeout=None):
                if "air-quality" in url: raise UpstreamError("air down")
                return super().get_json(url, params, timeout)
        r = demo_app(client=NoAir(now=NOW)).test_client().get("/api/weather?lat=12.97&lon=77.59")
        self.assertEqual(r.status_code, 200); self.assertIsNone(r.get_json()["air"])

    def test_rate_limit(self):
        c = demo_app(rate_limit_per_minute=5).test_client()
        codes = [c.get("/api/search?q=lon").status_code for _ in range(8)]
        self.assertEqual(codes[:5], [200] * 5); self.assertEqual(codes[5:], [429] * 3)
        self.assertEqual(c.get("/api/health").status_code, 200)  # health is exempt
        self.assertIn("Retry-After", c.get("/api/search?q=lon").headers)

    def test_demo_scene_endpoint_only_in_demo(self):
        self.assertEqual(self.c.get("/api/_demo/scene?name=rain").status_code, 200)
        self.assertEqual(self.c.get("/api/_demo/scene?name=bogus").status_code, 400)
        from weathervane import create_app
        live = create_app(Config(demo=False, rate_limit_per_minute=0), client=type("X", (), {"get_json": lambda *a, **k: {}})())
        self.assertEqual(live.test_client().get("/api/_demo/scene?name=rain").status_code, 404)

    def test_insights_endpoint(self):
        d = self.c.get("/api/insights?lat=12.97&lon=77.59").get_json(); self.assertIn("trend", d); self.assertIn("method", d)


if __name__ == "__main__":
    unittest.main()
