import json, os, tempfile, time, threading, unittest
from datetime import datetime
from weathervane.errors import UpstreamError, ApiError
from weathervane.utils.cache import TTLCache, DiskCache
from weathervane.services import meteo, wmo, astro, geocode, guidance, air
from weathervane.services.http import HttpClient
from weathervane.config import Config


class CacheTests(unittest.TestCase):
    def test_expiry(self):
        t = [0.0]
        c = TTLCache(clock=lambda: t[0])
        c.set("a", 1, ttl=10)
        self.assertEqual(c.get("a"), 1)
        t[0] = 11
        self.assertIsNone(c.get("a"))

    def test_lru_eviction(self):
        c = TTLCache(maxsize=2)
        c.set("a", 1, 60); c.set("b", 2, 60); c.get("a"); c.set("c", 3, 60)
        self.assertIsNone(c.get("b")); self.assertEqual(c.get("a"), 1)

    def test_single_flight(self):
        c, calls = TTLCache(), []
        def slow():
            calls.append(1); time.sleep(0.15); return "v"
        threads = [threading.Thread(target=lambda: c.get_or_set("k", 60, slow)) for _ in range(8)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(len(calls), 1)

    def test_errors_not_cached(self):
        c, n = TTLCache(), [0]
        def boom():
            n[0] += 1; raise RuntimeError("x")
        for _ in range(2):
            with self.assertRaises(RuntimeError): c.get_or_set("k", 60, boom)
        self.assertEqual(n[0], 2)

    def test_disk_cache_roundtrip_and_ttl(self):
        with tempfile.TemporaryDirectory() as d:
            dc = DiskCache(d)
            dc.set("k", {"a": [1, 2]})
            self.assertEqual(dc.get("k", 60), {"a": [1, 2]})
            self.assertIsNone(dc.get("k", -1))
            self.assertIsNone(dc.get("missing", 60))
            with open(dc._path("bad"), "w") as fh: fh.write("{not json")
            self.assertIsNone(dc.get("bad", 60))  # corrupt file is a miss, not a crash


class MeteoTests(unittest.TestCase):
    def test_beaufort_boundaries(self):
        for speed, force in [(0, 0), (0.9, 0), (1, 1), (5.9, 1), (6, 2), (19.9, 3), (20, 4), (117, 11), (118, 12), (300, 12)]:
            self.assertEqual(meteo.beaufort(speed)["force"], force, speed)
        self.assertIsNone(meteo.beaufort(None)); self.assertIsNone(meteo.beaufort(-3))

    def test_compass(self):
        for deg, name in [(0, "N"), (11, "N"), (12, "NNE"), (90, "E"), (180, "S"), (270, "W"), (348.8, "N"), (360, "N"), (-90, "W")]:
            self.assertEqual(meteo.compass(deg), name, deg)

    def test_num_rejects_junk(self):
        for bad in (None, "x", float("nan"), float("inf"), True, [], {}):
            self.assertIsNone(meteo.num(bad))
        self.assertEqual(meteo.num("2.5"), 2.5)

    def test_labels(self):
        self.assertEqual(meteo.uv_label(2.9), "Low"); self.assertEqual(meteo.uv_label(11), "Extreme")
        self.assertEqual(meteo.feels_label(-12), "Bitterly cold"); self.assertEqual(meteo.feels_label(22), "Comfortable")
        self.assertEqual(meteo.dew_point_comfort(22), "Muggy")
        self.assertEqual(meteo.pressure_trend([1000, 1000, 1000, 1004], 0), "Rising fast")
        self.assertIsNone(meteo.pressure_trend([1000], 0))


class WmoTests(unittest.TestCase):
    def test_day_night_icons(self):
        self.assertEqual(wmo.describe(0, True)["icon"], "clear-day")
        self.assertEqual(wmo.describe(0, False)["icon"], "clear-night")
        self.assertEqual(wmo.describe(63, False)["icon"], "rain")

    def test_unknown_and_garbage(self):
        for bad in (None, 123, "abc", -1):
            self.assertEqual(wmo.describe(bad)["label"], "Unknown")

    def test_all_codes_have_valid_scene(self):
        for code in (0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99):
            self.assertIn(wmo.describe(code)["scene"], {"clear", "cloudy", "rain", "snow", "storm", "fog"})


class AstroTests(unittest.TestCase):
    def test_moon_phases_match_real_astronomy(self):
        # Real events (UTC): full 2024-01-25 17:54, new 2024-01-11 11:57, first quarter 2024-01-18 03:53.
        for stamp, name in [("2024-01-25T18:00", "Full moon"), ("2024-01-11T12:00", "New moon"), ("2024-01-18T04:00", "First quarter")]:
            self.assertEqual(astro.moon_info(datetime.fromisoformat(stamp), 0, 40)["name"], name)

    def test_moon_hemisphere_flag_and_bounds(self):
        m = astro.moon_info(datetime(2026, 10, 10, 12), 0, -33)
        self.assertTrue(m["mirrored"]); self.assertTrue(0 <= m["illumination"] <= 1); self.assertTrue(0 <= m["phase"] < 1)

    def test_sun_progress(self):
        s = astro.sun_info("2026-10-10T06:00", "2026-10-10T18:00", 43200, datetime(2026, 10, 10, 12), 43100)
        self.assertEqual(s["progress"], 0.5); self.assertTrue(s["is_daytime"]); self.assertEqual(s["daylight_change_seconds"], -100)
        night = astro.sun_info("2026-10-10T06:00", "2026-10-10T18:00", 43200, datetime(2026, 10, 10, 22))
        self.assertFalse(night["is_daytime"])

    def test_polar_and_missing(self):
        self.assertEqual(astro.sun_info(None, None, 86400, None)["polar"], "day")
        self.assertEqual(astro.sun_info(None, None, 0, None)["polar"], "night")
        self.assertIsNone(astro.sun_info("garbage", "x", None, None)["sunrise"])


class GeocodeTests(unittest.TestCase):
    def test_coordinates(self):
        self.assertEqual(geocode.parse_coordinates("12.97, 77.59"), (12.97, 77.59))
        self.assertEqual(geocode.parse_coordinates("-33.86 151.21"), (-33.86, 151.21))
        for bad in ("91, 10", "10, 181", "Paris", "75001", "1,2,3", ""):
            self.assertIsNone(geocode.parse_coordinates(bad), bad)

    def test_labels_and_kinds(self):
        self.assertEqual(geocode.make_label("Delhi", "Delhi", "India"), "Delhi, India")
        self.assertEqual(geocode.make_label("Singapore", None, "Singapore"), "Singapore")
        self.assertEqual(geocode.kind_for("PCLI", 1), "country"); self.assertEqual(geocode.kind_for("ADM1", None), "region")
        self.assertEqual(geocode.kind_for("PPL", 5000), "town"); self.assertEqual(geocode.kind_for("PPL", 5_000_000), "city")

    def test_search_dedupes_and_skips_bad_rows(self):
        class C:
            def get_json(self, *a, **k):
                row = {"name": "Springfield", "latitude": 39.8, "longitude": -89.6, "feature_code": "PPL", "admin1": "Illinois", "country": "United States", "population": 100}
                return {"results": [row, dict(row), {"name": "NoCoords"}, "junk"]}
        out = geocode.search_places(C(), Config(), "Springfield")
        self.assertEqual(len(out), 1); self.assertEqual(out[0]["label"], "Springfield, Illinois, United States")

    def test_reverse_never_raises(self):
        class Fail:
            def get_json(self, *a, **k): raise UpstreamError("down")
        p = geocode.reverse_place(Fail(), Config(), 10.5, 20.25, use_gate=False)
        self.assertFalse(p["resolved"]); self.assertIn("10.50", p["label"])


class GuidanceTests(unittest.TestCase):
    @staticmethod
    def H(i, **k):
        base = {"time": f"2026-10-10T{i % 24:02d}:00", "temp": 20, "feels_like": 20, "precip": 0, "precip_prob": 0,
                "code": 0, "wind": 5, "gust": 8, "uv": 3, "is_day": 1, "visibility": 20000}
        base.update(k); return base

    def test_quiet_day_has_no_alerts(self):
        hrs = [self.H(i) for i in range(48)]
        self.assertEqual(guidance.build_alerts(hrs, [{"precip_sum": 0, "uv_max": 5}] * 3), [])

    def test_severe_conditions_alert_and_sort(self):
        hrs = [self.H(i, feels_like=42, gust=95, code=96, precip=12) for i in range(48)]
        alerts = guidance.build_alerts(hrs, [{"precip_sum": 120, "uv_max": 12}] * 3, {"us_aqi": 180, "advice": "x"})
        kinds = {a["kind"] for a in alerts}
        self.assertTrue({"heat", "wind", "rain", "storm", "uv", "air"} <= kinds)
        sev = [guidance.SEVERITY_ORDER[a["severity"]] for a in alerts]
        self.assertEqual(sev, sorted(sev, reverse=True))

    def test_cold_and_fog(self):
        hrs = [self.H(i, feels_like=-30, visibility=100, code=45) for i in range(48)]
        kinds = {a["kind"]: a["severity"] for a in guidance.build_alerts(hrs, [{}] * 2)}
        self.assertEqual(kinds["cold"], "warning"); self.assertEqual(kinds["fog"], "warning")

    def test_rain_outlook_states(self):
        dry = [self.H(i) for i in range(24)]
        self.assertEqual(guidance.rain_outlook(dry)["state"], "dry")
        later = [self.H(i) for i in range(24)]; later[3] = self.H(3, precip=1.0, code=61, precip_prob=90); later[4] = self.H(4, precip=1.0, code=61)
        r = guidance.rain_outlook(later); self.assertEqual((r["state"], r["start"], r["end"]), ("wet-later", "2026-10-10T03:00", "2026-10-10T05:00"))
        now = [self.H(i, precip=1, code=73) for i in range(24)]
        r = guidance.rain_outlook(now); self.assertEqual((r["state"], r["kind"], r["end"]), ("wet-now", "snow", None))
        self.assertEqual(guidance.rain_outlook([])["state"], "dry")

    def test_scores_monotonic(self):
        nice, wet, hot = self.H(1), self.H(1, precip_prob=95, precip=3), self.H(1, feels_like=41, temp=38)
        self.assertGreater(guidance.hour_score(nice), guidance.hour_score(wet))
        self.assertGreater(guidance.hour_score(nice), guidance.hour_score(hot))
        self.assertEqual(guidance.hour_score(self.H(1, feels_like=None, temp=None)), 0.0)
        self.assertLess(guidance.hour_score(nice, guidance.aqi_factor(250)), guidance.hour_score(nice))

    def test_best_window_daylight_only(self):
        hrs = [self.H(i, is_day=1 if 6 <= i < 20 else 0) for i in range(24)]
        w = guidance.best_outdoor_window(hrs)
        self.assertTrue(6 <= int(w["start"][11:13]) < 20)
        self.assertIsNone(guidance.best_outdoor_window([self.H(i, is_day=0) for i in range(24)]))

    def test_outfit(self):
        cold = guidance.outfit([self.H(i, feels_like=-12) for i in range(12)])
        self.assertIn("Insulated", cold[0])
        rainy = guidance.outfit([self.H(i, precip_prob=80, code=63) for i in range(12)])
        self.assertTrue(any("mbrella" in x for x in rainy))


class AirTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(air.us_category(50)["label"], "Good"); self.assertEqual(air.us_category(51)["label"], "Moderate")
        self.assertEqual(air.us_category(301)["label"], "Hazardous"); self.assertIsNone(air.us_category(None))
        self.assertEqual(air.eu_category(15), "Good"); self.assertEqual(air.eu_category(101), "Extremely poor")

    def test_no_data_returns_none(self):
        self.assertIsNone(air.build_air({})); self.assertIsNone(air.build_air({"current": {"us_aqi": None, "european_aqi": None}}))


class HttpClientTests(unittest.TestCase):
    class R:
        def __init__(self, status, body, bad_json=False): self.status_code, self._b, self._bad = status, body, bad_json
        def json(self):
            if self._bad: raise ValueError("bad")
            return self._b

    def client(self, resp=None, exc=None):
        c = HttpClient(Config())
        def get(*a, **k):
            if exc: raise exc
            return resp
        c._session.get = get
        return c

    def test_ok(self):
        self.assertEqual(self.client(self.R(200, {"a": 1})).get_json("u"), {"a": 1})

    def test_error_mapping(self):
        import requests
        cases = [(self.client(self.R(429, {})), 503, "upstream_rate_limited"),
                 (self.client(self.R(400, {"reason": "Latitude invalid"})), 502, "upstream_rejected"),
                 (self.client(self.R(404, {})), 404, "no_data"),
                 (self.client(self.R(200, None, bad_json=True)), 502, "upstream_invalid"),
                 (self.client(self.R(200, {"error": True, "reason": "x"})), 502, "upstream_rejected"),
                 (self.client(exc=requests.Timeout()), 504, "upstream_timeout"),
                 (self.client(exc=requests.ConnectionError()), 502, "upstream_unreachable")]
        for client, status, code in cases:
            with self.assertRaises(UpstreamError) as cm: client.get_json("u")
            self.assertEqual((cm.exception.status, cm.exception.code), (status, code))


if __name__ == "__main__":
    unittest.main()
