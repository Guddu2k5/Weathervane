"""Offline demo data.

``DemoClient`` is a drop-in replacement for ``HttpClient`` that fabricates
responses in the same *shape* as Open-Meteo and Nominatim. It lets you explore
the interface with no internet, and it powers the automated tests.

The numbers are synthetic (a simple latitude/season climate model plus seeded
noise). They are **not** real weather. The UI shows a "Demo data" banner
whenever this client is active.
"""
from __future__ import annotations

import math
import random
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from .errors import UpstreamError

# name, admin1, country, cc, lat, lon, population, tz name, utc offset (h), feature code, elevation
_PLACES = [
    ("Bengaluru", "Karnataka", "India", "IN", 12.9719, 77.5937, 8443675, "Asia/Kolkata", 5.5, "PPLA", 920),
    ("Mumbai", "Maharashtra", "India", "IN", 19.0728, 72.8826, 12691836, "Asia/Kolkata", 5.5, "PPLA", 14),
    ("New Delhi", "Delhi", "India", "IN", 28.6358, 77.2245, 249998, "Asia/Kolkata", 5.5, "PPLC", 225),
    ("Chennai", "Tamil Nadu", "India", "IN", 13.0878, 80.2785, 4328063, "Asia/Kolkata", 5.5, "PPLA", 6),
    ("Mysuru", "Karnataka", "India", "IN", 12.2958, 76.6394, 920550, "Asia/Kolkata", 5.5, "PPL", 770),
    ("Karnataka", None, "India", "IN", 14.5204, 75.7224, None, "Asia/Kolkata", 5.5, "ADM1", None),
    ("India", None, "India", "IN", 22.0, 79.0, 1352617328, "Asia/Kolkata", 5.5, "PCLI", None),
    ("London", "England", "United Kingdom", "GB", 51.5085, -0.1257, 8961989, "Europe/London", 1, "PPLC", 25),
    ("Paris", "Ile-de-France", "France", "FR", 48.8534, 2.3488, 2138551, "Europe/Paris", 2, "PPLC", 42),
    ("Berlin", "Berlin", "Germany", "DE", 52.5244, 13.4105, 3426354, "Europe/Berlin", 2, "PPLC", 43),
    ("Reykjavik", "Capital Region", "Iceland", "IS", 64.1355, -21.8954, 118918, "Atlantic/Reykjavik", 0, "PPLC", 5),
    ("Cairo", "Cairo", "Egypt", "EG", 30.0626, 31.2497, 7734614, "Africa/Cairo", 3, "PPLC", 23),
    ("Nairobi", "Nairobi County", "Kenya", "KE", -1.2833, 36.8167, 4397073, "Africa/Nairobi", 3, "PPLC", 1661),
    ("Lagos", "Lagos", "Nigeria", "NG", 6.4541, 3.3947, 9000000, "Africa/Lagos", 1, "PPLA", 41),
    ("Cape Town", "Western Cape", "South Africa", "ZA", -33.9258, 18.4232, 3433441, "Africa/Johannesburg", 2, "PPLA", 25),
    ("Dubai", "Dubai", "United Arab Emirates", "AE", 25.0657, 55.1713, 3137000, "Asia/Dubai", 4, "PPLA", 5),
    ("Singapore", None, "Singapore", "SG", 1.2897, 103.8501, 5271000, "Asia/Singapore", 8, "PPLC", 16),
    ("Tokyo", "Tokyo", "Japan", "JP", 35.6895, 139.6917, 8336599, "Asia/Tokyo", 9, "PPLC", 40),
    ("Beijing", "Beijing", "China", "CN", 39.9075, 116.3972, 18960744, "Asia/Shanghai", 8, "PPLC", 49),
    ("Sydney", "New South Wales", "Australia", "AU", -33.8678, 151.2073, 4627345, "Australia/Sydney", 11, "PPLA", 58),
    ("Auckland", "Auckland", "New Zealand", "NZ", -36.8485, 174.7635, 1346091, "Pacific/Auckland", 13, "PPLA", 26),
    ("Moscow", "Moscow", "Russia", "RU", 55.7522, 37.6156, 10381222, "Europe/Moscow", 3, "PPLC", 144),
    ("Istanbul", "Istanbul", "Turkey", "TR", 41.0138, 28.9497, 14804116, "Europe/Istanbul", 3, "PPLA", 40),
    ("New York", "New York", "United States", "US", 40.7143, -74.006, 8804190, "America/New_York", -4, "PPL", 10),
    ("Los Angeles", "California", "United States", "US", 34.0522, -118.2437, 3898747, "America/Los_Angeles", -7, "PPL", 90),
    ("Chicago", "Illinois", "United States", "US", 41.8500, -87.65, 2746388, "America/Chicago", -5, "PPL", 180),
    ("Anchorage", "Alaska", "United States", "US", 61.2181, -149.9003, 291247, "America/Anchorage", -8, "PPL", 31),
    ("Toronto", "Ontario", "Canada", "CA", 43.7001, -79.4163, 2731571, "America/Toronto", -4, "PPLA", 76),
    ("Mexico City", "Mexico City", "Mexico", "MX", 19.4285, -99.1277, 9209944, "America/Mexico_City", -6, "PPLC", 2240),
    ("Lima", "Lima", "Peru", "PE", -12.0432, -77.0282, 8852000, "America/Lima", -5, "PPLC", 161),
    ("Sao Paulo", "Sao Paulo", "Brazil", "BR", -23.5475, -46.6361, 10021295, "America/Sao_Paulo", -3, "PPLA", 760),
    ("Buenos Aires", "Buenos Aires F.D.", "Argentina", "AR", -34.6131, -58.3772, 13076300, "America/Argentina/Buenos_Aires", -3, "PPLC", 25),
    ("Kathmandu", "Bagmati", "Nepal", "NP", 27.7172, 85.3240, 1442271, "Asia/Kathmandu", 5.75, "PPLC", 1317),
    ("Longyearbyen", "Svalbard", "Norway", "NO", 78.2232, 15.6469, 2417, "Arctic/Longyearbyen", 2, "PPLC", 10),
]

MODEL_BIAS = {"ecmwf_ifs025": 0.0, "gfs_seamless": 0.4, "icon_seamless": -0.3, "gem_seamless": 0.7}

# Set to "clear", "cloudy", "rain", "snow", "storm" or "fog" to force the first
# two days to that scene (used for screenshots and the demo scene switcher).
SCENES = {
    "clear": 0, "cloudy": 3, "rain": 63, "snow": 73, "storm": 95, "fog": 45,
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _offset_hours(lat: float, lon: float) -> float:
    best = min(_PLACES, key=lambda p: _haversine_km(lat, lon, p[4], p[5]))
    if _haversine_km(lat, lon, best[4], best[5]) < 1500:
        return float(best[8])
    return float(round(lon / 15))


def _timezone_name(lat: float, lon: float) -> str:
    best = min(_PLACES, key=lambda p: _haversine_km(lat, lon, p[4], p[5]))
    if _haversine_km(lat, lon, best[4], best[5]) < 1500:
        return best[7]
    return "GMT" if abs(lon) < 7.5 else f"Etc/GMT{-round(lon / 15):+d}"


def _climate_mean(lat: float, lon: float, d: date) -> float:
    """Typical daily mean temperature (degC), with a gentle warming trend."""
    annual = 28 - 0.0075 * lat * lat
    amplitude = 1 + 0.18 * abs(lat)
    peak = 200 if lat >= 0 else 17
    seasonal = amplitude * math.cos(2 * math.pi * (d.timetuple().tm_yday - peak) / 365)
    return annual + seasonal + 0.035 * (d.year - 2005)


def _seed(lat: float, lon: float, *extra: Any) -> int:
    # zlib.crc32 is stable across runs (the built-in hash() is salted for strings).
    return zlib.crc32(repr((round(lat, 1), round(lon, 1)) + extra).encode("utf-8"))


def _solar(lat: float, lon: float, d: date, tz_h: float) -> tuple:
    """(declination_rad, sunrise_h, sunset_h, noon_h) in local clock hours."""
    doy = d.timetuple().tm_yday
    decl = math.radians(23.44) * math.sin(2 * math.pi * (doy - 81) / 365)
    phi = math.radians(max(-89.5, min(89.5, lat)))
    cos_h = -math.tan(phi) * math.tan(decl)
    noon = 12 - (lon - tz_h * 15) / 15
    if cos_h >= 1:
        return decl, None, None, noon        # polar night
    if cos_h <= -1:
        return decl, -99.0, 99.0, noon       # polar day
    half = math.degrees(math.acos(cos_h)) / 15
    return decl, noon - half, noon + half, noon


def _pm25_to_us_aqi(pm: float) -> float:
    bands = [(12.0, 0, 50), (35.4, 51, 100), (55.4, 101, 150), (150.4, 151, 200),
             (250.4, 201, 300), (500.4, 301, 500)]
    lo = 0.0
    for hi, a_lo, a_hi in bands:
        if pm <= hi:
            return a_lo + (a_hi - a_lo) * (pm - lo) / (hi - lo)
        lo = hi
    return 500.0


class DemoClient:
    def __init__(self, now: Optional[datetime] = None, scene: Optional[str] = None):
        self._fixed_now = now
        self.scene = scene

    # -- public interface (matches HttpClient) ------------------------------ #
    def get_json(self, url: str, params: Optional[dict] = None, timeout: Any = None) -> Any:
        params = dict(params or {})
        if "geocoding-api" in url:
            return self._geocode(params)
        if "air-quality-api" in url:
            return self._air(params)
        if "archive-api" in url:
            return self._archive(params)
        if "nominatim" in url:
            return self._reverse(params)
        if "open-meteo.com" in url:
            return self._forecast(params)
        raise UpstreamError("Demo client does not know that endpoint.", 502, "demo_unknown")

    def _now_utc(self) -> datetime:
        return self._fixed_now or datetime.now(timezone.utc).replace(tzinfo=None)

    # -- geocoding ----------------------------------------------------------- #
    def _geocode(self, p: dict) -> dict:
        name = str(p.get("name", "")).strip().lower()
        count = int(p.get("count", 10))
        if len(name) < 2:
            return {}
        hits = []
        for i, (n, a1, c, cc, lat, lon, pop, tz, off, fc, elev) in enumerate(_PLACES):
            hay = n.lower()
            if hay.startswith(name) or name in hay or (a1 and a1.lower().startswith(name)):
                hits.append({
                    "id": 1000 + i, "name": n, "latitude": lat, "longitude": lon, "elevation": elev,
                    "feature_code": fc, "country_code": cc, "admin1": a1, "country": c,
                    "timezone": tz, "population": pop,
                })
        hits.sort(key=lambda h: (not h["name"].lower().startswith(name), -(h["population"] or 0)))
        return {"results": hits[:count]} if hits else {"generationtime_ms": 0.5}

    def _reverse(self, p: dict) -> dict:
        lat, lon = float(p["lat"]), float(p["lon"])
        best = min(_PLACES, key=lambda pl: _haversine_km(lat, lon, pl[4], pl[5]))
        if _haversine_km(lat, lon, best[4], best[5]) > 150 or best[9] in {"PCLI", "ADM1"}:
            return {"error": "Unable to geocode"}
        return {"address": {"city": best[0], "state": best[1], "country": best[2],
                            "country_code": best[3].lower()}}

    # -- weather model -------------------------------------------------------- #
    def _day_state(self, lat: float, lon: float, d: date, lead: int) -> dict:
        rng = random.Random(_seed(lat, lon, d.toordinal()))
        cloud = rng.betavariate(1.6, 1.6)
        humid = max(0.0, min(1.0, 0.25 + 0.5 * math.exp(-abs(lat) / 35) + rng.uniform(-0.15, 0.15)))
        wet = rng.random() < 0.18 + 0.35 * humid * cloud
        anomaly = rng.gauss(0, 2.2)
        mean = _climate_mean(lat, lon, d) + anomaly - (1.8 if wet else 0)
        rain = 0.0
        code = 0 if cloud < 0.25 else 1 if cloud < 0.45 else 2 if cloud < 0.75 else 3
        if wet:
            cloud = max(cloud, 0.8)
            if mean <= 0.5:
                code = rng.choice([71, 73, 75]); rain = rng.uniform(0.5, 6)
            else:
                code = rng.choice([61, 63, 63, 65, 80, 81, 51, 53])
                rain = {61: 1.5, 63: 5, 65: 14, 80: 3, 81: 7, 51: 0.6, 53: 1.0}[code] * rng.uniform(0.6, 1.4)
                if mean > 22 and rng.random() < 0.18:
                    code = 95; rain *= 1.5
        elif cloud > 0.85 and rng.random() < 0.06 and abs(lat) > 20:
            code = 45
        state = {"cloud": cloud, "mean": mean, "code": code, "rain": rain, "wet": wet or code in (51, 53),
                 "wind": rng.uniform(5, 24) + (20 if code in (95, 65) else 0), "wdir": rng.uniform(0, 360),
                 "humid": humid, "seed": rng.randrange(1_000_000)}
        forced = SCENES.get(self.scene or "")
        if forced is not None and lead <= 1:
            state["code"] = forced
            state["cloud"] = {0: 0.05, 3: 0.95}.get(forced, 0.9)
            if forced in (63, 95):
                state.update(rain=9.0 if forced == 63 else 14.0, wet=True)
                state["wind"] = 14 if forced == 63 else 48
            elif forced == 73:
                state.update(rain=4.0, wet=True, mean=-3.0 + (0 if lead == 0 else 1))
            elif forced == 45:
                state.update(rain=0.0, wet=False, wind=3)
            else:
                state.update(rain=0.0, wet=False)
        return state

    def _hourly_block(self, lat: float, lon: float, start: date, days: int, tz_h: float) -> dict:
        cols = {k: [] for k in (
            "time", "temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature",
            "precipitation_probability", "precipitation", "weather_code", "pressure_msl", "cloud_cover",
            "visibility", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "uv_index", "is_day")}
        today = (self._now_utc() + timedelta(hours=tz_h)).date()
        for di in range(days):
            d = start + timedelta(days=di)
            lead = max(0, (d - today).days)
            st = self._day_state(lat, lon, d, lead)
            decl, rise, sett, noon = _solar(lat, lon, d, tz_h)
            rng = random.Random(st["seed"])
            span = 5 + (1 - st["cloud"]) * 6
            wet_peak = 14 + rng.randint(-4, 5)
            for h in range(24):
                hour_rng = random.Random(st["seed"] * 31 + h)
                diurnal = math.cos(2 * math.pi * (h - 15) / 24)
                temp = st["mean"] + (span / 2) * diurnal + hour_rng.gauss(0, 0.25)
                wet_now = st["wet"] and abs(h - wet_peak) <= (3 if st["code"] in (80, 81, 95) else 7)
                code = st["code"] if (wet_now or not st["wet"]) else (2 if st["cloud"] > 0.5 else 1)
                if st["code"] == 45 and not (4 <= h <= 10):
                    code = 3
                precip = (st["rain"] / 4.0) * (1.0 - abs(h - wet_peak) / 8) if wet_now else 0.0
                precip = max(0.0, precip * hour_rng.uniform(0.6, 1.3))
                if self.scene in ("rain", "snow", "storm") and lead <= 1:
                    wet_now = True
                    code = st["code"]
                    precip = max(precip, st["rain"] / 6 * hour_rng.uniform(0.7, 1.2))
                if code == 0 and st["cloud"] > 0.6:
                    code = 3
                if rise is None:
                    is_day, sin_el = 0, -1.0
                elif rise < -90:
                    is_day, sin_el = 1, 0.3
                else:
                    is_day = 1 if rise <= h + 0.5 <= sett else 0
                    phi = math.radians(max(-89.5, min(89.5, lat)))
                    sin_el = (math.sin(phi) * math.sin(decl)
                              + math.cos(phi) * math.cos(decl) * math.cos(math.radians(15 * (h + 0.5 - noon))))
                uv = max(0.0, sin_el) * 11.5 * (1 - 0.75 * st["cloud"]) if is_day else 0.0
                humidity = max(25, min(100, 100 - (temp - (temp - 6 - 14 * (1 - st["humid"]))) * 4 - 22 * (1 - st["humid"]) * (1 + diurnal) / 1.2 + (12 if wet_now else 0)))
                dew = temp - (100 - humidity) / 5
                wind = max(0.0, st["wind"] * (0.8 + 0.4 * hour_rng.random()) * (0.8 + 0.3 * max(0, diurnal)))
                feels = temp + (humidity - 50) * 0.05 * max(0, temp - 22) / 4 - max(0, wind - 8) * 0.12 * max(0, 14 - temp) / 6
                pressure = 1013 + (-6 if st["wet"] else 3) + 4 * math.sin(2 * math.pi * (d.toordinal() + h / 24) / 5.5)
                vis = 800 if code in (45, 48) else 8000 if wet_now else 24000 * (1 - 0.3 * st["humid"])
                prob = None
                if wet_now:
                    prob = min(100, int(60 + 40 * hour_rng.random()))
                else:
                    prob = int(max(0, min(60, 25 * st["humid"] * st["cloud"] * hour_rng.uniform(0.2, 1.4) + (20 if st["wet"] else 0))))
                cols["time"].append(f"{d.isoformat()}T{h:02d}:00")
                cols["temperature_2m"].append(round(temp, 1))
                cols["relative_humidity_2m"].append(int(round(humidity)))
                cols["dew_point_2m"].append(round(dew, 1))
                cols["apparent_temperature"].append(round(feels, 1))
                cols["precipitation_probability"].append(prob)
                cols["precipitation"].append(round(precip, 2))
                cols["weather_code"].append(code)
                cols["pressure_msl"].append(round(pressure, 1))
                cols["cloud_cover"].append(int(round(st["cloud"] * 100)))
                cols["visibility"].append(round(vis))
                cols["wind_speed_10m"].append(round(wind, 1))
                cols["wind_direction_10m"].append(int(round((st["wdir"] + 10 * math.sin(h / 4)) % 360)))
                cols["wind_gusts_10m"].append(round(wind * (1.35 + 0.3 * hour_rng.random()), 1))
                cols["uv_index"].append(round(uv, 2))
                cols["is_day"].append(is_day)
        return cols

    def _daily_block(self, lat: float, lon: float, hourly: dict, tz_h: float) -> dict:
        times = hourly["time"]
        days = sorted({t[:10] for t in times})
        out = {k: [] for k in (
            "time", "weather_code", "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
            "apparent_temperature_min", "sunrise", "sunset", "daylight_duration", "sunshine_duration",
            "uv_index_max", "precipitation_sum", "precipitation_probability_max", "precipitation_hours",
            "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant")}
        for day in days:
            idx = [i for i, t in enumerate(times) if t.startswith(day)]
            pick = lambda k: [hourly[k][i] for i in idx]
            d = date.fromisoformat(day)
            _, rise, sett, noon = _solar(lat, lon, d, tz_h)
            codes = pick("weather_code")
            worst = max(codes, key=lambda c: (c in (95, 96, 99), c in (75, 86), c in (65, 82), c in (71, 73, 63, 61, 80, 81, 51, 53), c))
            midday = codes[12]
            wet_codes = {51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95}
            code = worst if worst in wet_codes else midday
            def clock(h):
                return None if h is None else f"{day}T{int(h) % 24:02d}:{int((h % 1) * 60):02d}"
            if rise is None:
                daylight = 0
            elif rise < -90:
                daylight = 86400
            else:
                daylight = (sett - rise) * 3600
            out["time"].append(day)
            out["weather_code"].append(code)
            out["temperature_2m_max"].append(max(pick("temperature_2m")))
            out["temperature_2m_min"].append(min(pick("temperature_2m")))
            out["apparent_temperature_max"].append(max(pick("apparent_temperature")))
            out["apparent_temperature_min"].append(min(pick("apparent_temperature")))
            out["sunrise"].append(clock(rise) if rise and rise > -90 else None)
            out["sunset"].append(clock(sett) if sett and sett < 90 else None)
            out["daylight_duration"].append(round(daylight))
            out["sunshine_duration"].append(round(daylight * (1 - hourly["cloud_cover"][idx[12]] / 130)))
            out["uv_index_max"].append(round(max(pick("uv_index")), 2))
            out["precipitation_sum"].append(round(sum(pick("precipitation")), 1))
            out["precipitation_probability_max"].append(max(pick("precipitation_probability")))
            out["precipitation_hours"].append(sum(1 for v in pick("precipitation") if v >= 0.1))
            out["wind_speed_10m_max"].append(max(pick("wind_speed_10m")))
            out["wind_gusts_10m_max"].append(max(pick("wind_gusts_10m")))
            out["wind_direction_10m_dominant"].append(hourly["wind_direction_10m"][idx[12]])
        return out

    def _one_forecast(self, lat: float, lon: float, p: dict) -> dict:
        tz_h = _offset_hours(lat, lon)
        local_now = self._now_utc() + timedelta(hours=tz_h)
        n_days = int(p.get("forecast_days", 7))
        hourly = self._hourly_block(lat, lon, local_now.date(), n_days, tz_h)
        daily = self._daily_block(lat, lon, hourly, tz_h)
        i = local_now.hour
        out: dict = {
            "latitude": round(lat, 4), "longitude": round(lon, 4), "generationtime_ms": 0.4,
            "utc_offset_seconds": int(tz_h * 3600), "timezone": _timezone_name(lat, lon),
            "timezone_abbreviation": "GMT", "elevation": 0.0,
        }
        wanted_current = [v for v in str(p.get("current", "")).split(",") if v]
        if wanted_current:
            cur = {"time": local_now.strftime("%Y-%m-%dT%H:%M"), "interval": 900}
            mapping = {"wind_speed_10m": "wind_speed_10m", "wind_direction_10m": "wind_direction_10m",
                       "wind_gusts_10m": "wind_gusts_10m", "temperature_2m": "temperature_2m",
                       "relative_humidity_2m": "relative_humidity_2m", "apparent_temperature": "apparent_temperature",
                       "is_day": "is_day", "precipitation": "precipitation", "weather_code": "weather_code",
                       "cloud_cover": "cloud_cover", "pressure_msl": "pressure_msl"}
            for v in wanted_current:
                if v in mapping:
                    cur[v] = hourly[mapping[v]][i]
            out["current"] = cur
        if p.get("hourly"):
            keep = [v for v in str(p["hourly"]).split(",") if v in hourly]
            out["hourly"] = {"time": hourly["time"], **{k: hourly[k] for k in keep}}
        if p.get("daily"):
            if p.get("models"):
                models = [m for m in str(p["models"]).split(",") if m in MODEL_BIAS]
                block = {"time": daily["time"]}
                for m in models:
                    for var in str(p["daily"]).split(","):
                        if var not in daily:
                            continue
                        vals = []
                        for lead, v in enumerate(daily[var]):
                            r = random.Random(_seed(lat, lon, m, var, lead, local_now.date().toordinal()))
                            if var == "temperature_2m_max":
                                vals.append(round(v + MODEL_BIAS[m] * (0.4 + 0.5 * lead) + r.gauss(0, 0.2 + 0.5 * lead), 1))
                            elif var == "precipitation_sum":
                                flip = r.random() < 0.05 * lead
                                vals.append(round(max(0.0, (0.0 if (v > 1 and flip) else v) * r.uniform(0.7, 1.3) + (2.0 if flip and v < 1 else 0)), 1))
                            else:
                                vals.append(v)
                        block[f"{var}_{m}"] = vals
                out["daily"] = block
            else:
                keep = [v for v in str(p["daily"]).split(",") if v in daily]
                out["daily"] = {"time": daily["time"], **{k: daily[k] for k in keep}}
        return out

    def _forecast(self, p: dict) -> Any:
        lats = [float(x) for x in str(p["latitude"]).split(",")]
        lons = [float(x) for x in str(p["longitude"]).split(",")]
        results = [self._one_forecast(la, lo, p) for la, lo in zip(lats, lons)]
        return results if len(results) > 1 else results[0]

    # -- air quality ----------------------------------------------------------- #
    def _air(self, p: dict) -> dict:
        lat, lon = float(p["latitude"]), float(p["longitude"])
        tz_h = _offset_hours(lat, lon)
        local_now = self._now_utc() + timedelta(hours=tz_h)
        base_rng = random.Random(_seed(lat, lon, "air"))
        base_pm = 6 + 55 * base_rng.random() ** 2 + (40 if 8 < lat < 32 and 68 < lon < 125 else 0)
        n_days = int(p.get("forecast_days", 2))
        times, aqi = [], []
        for di in range(n_days):
            d = local_now.date() + timedelta(days=di)
            for h in range(24):
                pm = base_pm * (1 + 0.35 * math.cos(2 * math.pi * (h - 8) / 24)) * random.Random(_seed(lat, lon, d.toordinal(), h)).uniform(0.9, 1.1)
                times.append(f"{d.isoformat()}T{h:02d}:00")
                aqi.append(round(_pm25_to_us_aqi(pm)))
        i = local_now.hour
        pm25 = round(base_pm * (1 + 0.35 * math.cos(2 * math.pi * (i - 8) / 24)), 1)
        eu = round(min(150, pm25 * 2.2))
        return {
            "latitude": lat, "longitude": lon, "timezone": _timezone_name(lat, lon),
            "current": {
                "time": local_now.strftime("%Y-%m-%dT%H:%M"), "interval": 3600,
                "us_aqi": aqi[i], "european_aqi": eu, "pm10": round(pm25 * 1.6, 1), "pm2_5": pm25,
                "carbon_monoxide": round(180 + pm25 * 4), "nitrogen_dioxide": round(6 + pm25 * 0.4, 1),
                "sulphur_dioxide": round(3 + pm25 * 0.15, 1), "ozone": round(40 + 35 * math.sin(math.pi * max(0, i - 6) / 12), 1),
                "dust": round(pm25 * 0.3, 1),
            },
            "hourly": {"time": times, "us_aqi": aqi},
        }

    # -- 35 years of history ---------------------------------------------------- #
    def _archive(self, p: dict) -> dict:
        lat, lon = float(p["latitude"]), float(p["longitude"])
        start = date.fromisoformat(p["start_date"])
        end = date.fromisoformat(p["end_date"])
        times, tmax, tmin, precip, wind = [], [], [], [], []
        d = start
        humid = max(0.0, min(1.0, 0.25 + 0.5 * math.exp(-abs(lat) / 35)))
        while d <= end:
            rng = random.Random(_seed(lat, lon, "arc", d.toordinal()))
            mean = _climate_mean(lat, lon, d) + rng.gauss(0, 2.2)
            span = 5 + 6 * rng.random()
            wet = rng.random() < 0.12 + 0.3 * humid
            amount = rng.expovariate(1 / 7.0) if wet else 0.0
            if wet:
                mean -= 1.5
            times.append(d.isoformat())
            tmax.append(round(mean + span / 2, 1))
            tmin.append(round(mean - span / 2, 1))
            precip.append(round(amount, 1))
            wind.append(round(rng.gammavariate(4, 3.2) + (6 if wet else 0), 1))
            d += timedelta(days=1)
        return {"latitude": lat, "longitude": lon, "daily": {
            "time": times, "temperature_2m_max": tmax, "temperature_2m_min": tmin,
            "precipitation_sum": precip, "wind_speed_10m_max": wind}}
