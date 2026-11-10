"""Tests of the weather forecast and logs (app/weather.py), with a fake Open-Meteo. Run: python3 -m unittest discover -s server/tests"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import server as server_mod  # noqa: E402
import weather  # noqa: E402
from server import make_server  # noqa: E402
from store import DataStore, atomic_write  # noqa: E402

server_mod.Handler.log_message = lambda *a: None
OFF = 8 * 3600   # WITA


def fake_open_meteo(now_utc, temp_shift=0.0):
    """An answer shaped like Open-Meteo's: 2 days back to 2 days ahead, hotel time, hour by hour."""
    def fetch(cfg):
        local = now_utc + timedelta(seconds=OFF)
        d0 = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=weather.PAST_DAYS)
        times = [d0 + timedelta(hours=i) for i in range(24 * (weather.PAST_DAYS + weather.FORECAST_DAYS))]
        n = len(times)
        days = sorted({t.strftime("%Y-%m-%d") for t in times})
        return {
            "utc_offset_seconds": OFF, "timezone": "Asia/Makassar", "latitude": cfg["lat"], "longitude": cfg["lon"],
            "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
                       "temperature_2m": [20 + t.hour + temp_shift for t in times],
                       "relative_humidity_2m": [80] * n, "dew_point_2m": [22] * n, "apparent_temperature": [30] * n,
                       "precipitation_probability": [50] * n, "precipitation": [0.5 if t.hour == 15 else 0 for t in times],
                       "weather_code": [61 if t.hour == 15 else 2 for t in times], "cloud_cover": [40] * n,
                       "wind_speed_10m": [5] * n, "wind_direction_10m": [90] * n, "wind_gusts_10m": [12] * n,
                       "shortwave_radiation": [500 if 7 <= t.hour <= 17 else 0 for t in times],
                       "is_day": [1 if 6 <= t.hour <= 18 else 0 for t in times]},
            "daily": {"time": days, "weather_code": [61] * len(days), "temperature_2m_max": [43] * len(days),
                      "temperature_2m_min": [20] * len(days), "precipitation_sum": [0.5] * len(days),
                      "precipitation_probability_max": [50] * len(days), "sunrise": [f"{d}T05:48" for d in days],
                      "sunset": [f"{d}T18:16" for d in days], "uv_index_max": [9] * len(days),
                      "shortwave_radiation_sum": [18] * len(days)},
            "current": {"time": local.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 29.5, "relative_humidity_2m": 70,
                        "apparent_temperature": 33, "weather_code": 2, "cloud_cover": 40, "wind_speed_10m": 6,
                        "precipitation": 0, "is_day": 1},
        }
    return fetch


class WeatherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = DataStore(self.tmp.name)
        self.profile({"weather": {"lat": -8.5, "lon": 115.26, "dayahead_hour": 18}})

    def tearDown(self):
        self.tmp.cleanup()

    def profile(self, extra):
        prof = {"code": "adab", "timezone": "Asia/Makassar", "utc_offset_h": 8}
        prof.update(extra)
        atomic_write(os.path.join(self.s.site_dir("adab"), "site.json"), json.dumps(prof))

    def lines(self, kind, year):
        with open(weather.Weather(self.s).path("adab", kind, year)) as f:
            return f.read().splitlines()

    def test_parse_hours_are_hotel_hours(self):
        now = datetime(2026, 11, 9, 2, 30, tzinfo=timezone.utc)   # 10:30 WITA
        p = weather.parse(fake_open_meteo(now)({"lat": 1, "lon": 2}))
        r = next(x for x in p["hours"] if x["t"] == "2026-11-09 14:00")
        self.assertEqual(r["temp_c"], 34.5)        # mean of 14:00 (34) and 15:00 (35)
        self.assertEqual(r["precip_mm"], 0.5)      # rain given at 15:00 = the hour 14:00-15:00
        self.assertEqual((r["code"], r["condition"]), (61, "Light rain"))   # the worse of the two
        self.assertEqual(p["days"][0]["sun_kwh_m2"], 5.0)   # 18 MJ/m2
        self.assertEqual(p["days"][0]["sunrise"], "05:48")
        self.assertEqual(p["current"]["temp_c"], 29.5)

    def test_actual_and_dayahead_logs(self):
        now = datetime(2026, 11, 9, 11, 30, tzinfo=timezone.utc)   # 19:30 WITA, after dayahead_hour 18
        wx = weather.Weather(self.s, fetch=fake_open_meteo(now))
        r = wx.update("adab", now)
        # the actual log: 2 days back up to the hour 17:00-18:00 (ended over an hour ago)
        act = self.lines("actual", 2026)
        self.assertEqual(act[0], ",".join(weather.ACTUAL_COLS))
        self.assertEqual(act[1].split(",")[0], "2026-11-07 00:00")
        self.assertEqual(act[-1].split(",")[0], "2026-11-09 17:00")
        self.assertEqual(r["actual"], 48 + 18)
        # tomorrow's forecast, once
        da = self.lines("dayahead", 2026)
        self.assertEqual(len(da), 25)
        self.assertEqual(da[1].split(",")[0], "2026-11-10 00:00")
        # an hour later: one more actual hour, nothing twice
        later = now + timedelta(hours=1)
        wx.fetch = fake_open_meteo(later)
        r = wx.update("adab", later)
        self.assertEqual((r["actual"], r["dayahead"]), (1, 0))
        self.assertEqual(self.lines("actual", 2026)[-1].split(",")[0], "2026-11-09 18:00")

    def test_dayahead_waits_for_its_hour_and_joins_the_log(self):
        day1 = datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc)    # 14:00 WITA: too early
        wx = weather.Weather(self.s, fetch=fake_open_meteo(day1))
        self.assertEqual(wx.update("adab", day1)["dayahead"], 0)
        eve = datetime(2026, 11, 8, 10, 5, tzinfo=timezone.utc)    # 18:05 WITA
        wx.fetch = fake_open_meteo(eve, temp_shift=1.0)            # the forecast is 1 degree too warm
        self.assertEqual(wx.update("adab", eve)["dayahead"], 24)
        nxt = datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)     # next day 12:00 WITA
        wx.fetch = fake_open_meteo(nxt)
        wx.update("adab", nxt)
        lg = wx.log("adab", 3)
        h = next(x for x in lg["hours"] if x["t"] == "2026-11-09 08:00")
        self.assertEqual(h["temp_c"], 28.5)
        self.assertEqual(h["fc_temp_c"], 29.5)
        self.assertIsNone(next(x for x in lg["hours"] if x["t"] == "2026-11-08 08:00")["fc_temp_c"])
        day = next(d for d in lg["days"] if d["date"] == "2026-11-09")
        self.assertEqual(day["fc_hours"], day["hours"])
        csv_text = wx.log_csv("adab", 3)
        self.assertIn("fc_temp_c", csv_text.splitlines()[0])
        # chosen dates, both included
        lg = wx.log("adab", start="2026-11-08", end="2026-11-08")
        self.assertEqual({x["t"][:10] for x in lg["hours"]}, {"2026-11-08"})
        self.assertEqual(([d["date"] for d in lg["days"]], lg["to"]), (["2026-11-08"], "2026-11-08"))
        two = wx.log("adab", start="2026-11-08", end="2026-11-09")["hours"]
        self.assertGreater(len(two), len(lg["hours"]))
        self.assertEqual(len(wx.log_csv("adab", start="2026-11-08", end="2026-11-09").splitlines()), 1 + len(two))
        for bad in (("2026-11-09", "2026-11-08"), ("2026-01-01", "2026-11-08"), ("2026-11-31", None)):
            with self.assertRaises(ValueError):
                wx.log("adab", start=bad[0], end=bad[1])

    def test_off_without_position(self):
        self.profile({"weather": {"lat": 200, "lon": 1}})
        self.assertIsNone(weather.Weather(self.s).settings("adab"))
        self.profile({})
        wx = weather.Weather(self.s, fetch=lambda cfg: self.fail("must not fetch"))
        wx.tick()
        self.assertFalse(wx.view("adab")["enabled"])

    def test_fetch_error_is_kept_and_shown(self):
        def boom(cfg):
            raise RuntimeError("Open-Meteo not reachable: test")
        wx = weather.Weather(self.s, fetch=boom)
        wx.tick()   # never raises
        self.assertIn("not reachable", wx.view("adab")["error"])
        self.assertFalse(os.path.exists(wx.path("adab", "forecast")))

    def test_http(self):
        srv = make_server(self.tmp.name, "127.0.0.1", 0)
        now = datetime.now(timezone.utc)
        server_mod.Handler.weather.fetch = fake_open_meteo(now)
        server_mod.Handler.weather.update("adab", now)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            j = json.load(urllib.request.urlopen(base + "/api/v1/weather/adab", timeout=5))
            self.assertTrue(j["enabled"])
            self.assertEqual(j["hours"][0]["t"], j["now"][:10] + " 00:00")   # from today 00:00
            self.assertGreaterEqual(len(j["hours"]), 48)
            j = json.load(urllib.request.urlopen(base + "/api/v1/weather/adab/log?days=2", timeout=5))
            self.assertTrue(j["hours"])
            with urllib.request.urlopen(base + "/api/v1/weather/adab/log?days=2&format=csv", timeout=5) as r:
                self.assertIn("text/csv", r.headers["Content-Type"])
                self.assertTrue(r.read().decode().startswith("t,temp_c,"))
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/api/v1/weather/nosite", timeout=5)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
