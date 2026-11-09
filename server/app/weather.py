"""Weather for the site page: Open-Meteo forecast (free, no key) fetched every hour, and two logs.

    sites/<site>/weather/forecast.json       the last forecast fetched: 2 days back to the day after tomorrow, per hour
    sites/<site>/weather/actual-YYYY.csv     the weather of every hotel hour that has passed (the "actual" log)
    sites/<site>/weather/dayahead-YYYY.csv   tomorrow's forecast, saved once a day at dayahead_hour (18:00 by default)

Turned on per site in site.json (manage.py weather <site> --lat .. --lon ..):
    "weather": {"lat": -8.5069, "lon": 115.2625, "dayahead_hour": 18, "model": "best_match"}

Rows are hotel hours, like the history pages: "t" = "YYYY-MM-DD HH:00" is the hour from HH:00 to HH+1:00.
Open-Meteo gives instant values at each full hour and sums over the hour before it, so for the hour HH:
  temperature, humidity, dew point, feels like, cloud, wind, gust = mean of the HH:00 and HH+1:00 values;
  rain, chance of rain, sun (shortwave radiation) = the HH+1:00 value (sum or mean over HH:00 to HH+1:00);
  weather code = the worse of the two (higher WMO code), wind direction = at HH:00.

"Actual" = Open-Meteo's value for an hour that has passed (its latest model run, corrected with the
observations it has), written one hour after the hour ends. It is not a measurement at the site: the
logger's outdoor sensor (TH2) is, and the page shows both side by side.

No database and nothing to install: urllib from the standard library, a few kB per site.
"""

import csv
import io
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from store import atomic_write, iso_now

API = os.environ.get("WEATHER_API", "https://api.open-meteo.com/v1/forecast")
SOURCE = "Open-Meteo (open-meteo.com, CC BY 4.0)"
EVERY_S = int(os.environ.get("WEATHER_EVERY_MIN", "60")) * 60
RETRY_S = 600
PAST_DAYS = 2              # the actual log can catch up after up to 2 days with the service down
FORECAST_DAYS = 3          # today, tomorrow, the day after
LOG_DELAY_H = 1            # an hour is logged as actual one hour after it ends
MAX_LOG_DAYS = 92
MODEL_RE = re.compile(r"^[a-z0-9_]{1,40}$")
TZ_RE = re.compile(r"^[A-Za-z0-9_+/-]{1,40}$")

HOURLY = ("temperature_2m", "relative_humidity_2m", "dew_point_2m", "apparent_temperature", "precipitation_probability",
          "precipitation", "weather_code", "cloud_cover", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
          "shortwave_radiation", "is_day")
DAILY = ("weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "precipitation_probability_max",
         "sunrise", "sunset", "uv_index_max", "shortwave_radiation_sum")
CURRENT = ("temperature_2m", "relative_humidity_2m", "apparent_temperature", "weather_code", "cloud_cover",
           "wind_speed_10m", "precipitation", "is_day")

ACTUAL_COLS = ("t", "temp_c", "rh_pct", "dew_c", "feels_c", "precip_mm", "cloud_pct", "wind_kmh", "gust_kmh",
               "wind_dir", "rad_wm2", "code", "condition", "fetched_utc")
DAYAHEAD_COLS = ("t", "issued_utc", "temp_c", "rh_pct", "feels_c", "precip_mm", "precip_prob_pct", "cloud_pct",
                 "wind_kmh", "rad_wm2", "code", "condition")
FC_KEYS = ("temp_c", "precip_mm", "precip_prob_pct", "code", "condition")   # day-ahead values joined to the log

# WMO weather interpretation codes (Open-Meteo's weather_code)
CONDITIONS = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
              51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
              61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
              71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers", 81: "Showers",
              82: "Violent showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorm",
              96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


def condition(code):
    return CONDITIONS.get(code, "") if code is not None else ""


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(v, nd=1):
    if v is None:
        return None
    return int(round(v)) if nd == 0 else round(v, nd)


def _mean(*vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def fetch_open_meteo(cfg):
    """The raw Open-Meteo answer for a site's settings (lat, lon, timezone, model)."""
    q = {"latitude": cfg["lat"], "longitude": cfg["lon"], "hourly": ",".join(HOURLY), "daily": ",".join(DAILY),
         "current": ",".join(CURRENT), "timezone": cfg.get("timezone") or "auto", "past_days": PAST_DAYS,
         "forecast_days": FORECAST_DAYS, "wind_speed_unit": "kmh"}
    if cfg.get("model") and cfg["model"] != "best_match":
        q["models"] = cfg["model"]
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "arkan-monitoring"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read(4_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", "replace")
        raise RuntimeError(f"Open-Meteo HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Open-Meteo not reachable: {e}") from None


def _hm(t):
    """'2026-11-09T06:12' -> '06:12'."""
    return t[11:16] if isinstance(t, str) and len(t) >= 16 else None


def parse(j):
    """Open-Meteo JSON -> {"hours": [...], "days": [...], "current": {...}, "utc_offset_s", ...}."""
    h = j.get("hourly") or {}
    times = [str(t).replace("T", " ") for t in h.get("time") or []]

    def col(name, i):
        arr = h.get(name) or []
        return _num(arr[i]) if i < len(arr) else None

    hours = []
    for a in range(len(times) - 1):   # the last time has no hour after it
        b = a + 1
        ca, cb = col("weather_code", a), col("weather_code", b)
        code = int(max(x for x in (ca, cb) if x is not None)) if ca is not None or cb is not None else None
        hours.append({
            "t": times[a][:13] + ":00",
            "temp_c": _r(_mean(col("temperature_2m", a), col("temperature_2m", b))),
            "rh_pct": _r(_mean(col("relative_humidity_2m", a), col("relative_humidity_2m", b)), 0),
            "dew_c": _r(_mean(col("dew_point_2m", a), col("dew_point_2m", b))),
            "feels_c": _r(_mean(col("apparent_temperature", a), col("apparent_temperature", b))),
            "precip_mm": _r(col("precipitation", b), 2),
            "precip_prob_pct": _r(col("precipitation_probability", b), 0),
            "cloud_pct": _r(_mean(col("cloud_cover", a), col("cloud_cover", b)), 0),
            "wind_kmh": _r(_mean(col("wind_speed_10m", a), col("wind_speed_10m", b))),
            "gust_kmh": _r(_mean(col("wind_gusts_10m", a), col("wind_gusts_10m", b))),
            "wind_dir": _r(col("wind_direction_10m", a), 0),
            "rad_wm2": _r(col("shortwave_radiation", b), 0),
            "code": code,
            "condition": condition(code),
            "is_day": None if col("is_day", a) is None else int(col("is_day", a)),
        })
    d = j.get("daily") or {}

    def at(name, i):
        arr = d.get(name) or []
        return arr[i] if i < len(arr) else None

    days = []
    for i, day in enumerate(d.get("time") or []):
        code = _num(at("weather_code", i))
        code = None if code is None else int(code)
        mj = _num(at("shortwave_radiation_sum", i))   # MJ/m2 -> kWh/m2
        days.append({"date": day, "code": code, "condition": condition(code),
                     "tmin_c": _r(_num(at("temperature_2m_min", i))), "tmax_c": _r(_num(at("temperature_2m_max", i))),
                     "precip_mm": _r(_num(at("precipitation_sum", i))),
                     "precip_prob_pct": _r(_num(at("precipitation_probability_max", i)), 0),
                     "uv": _r(_num(at("uv_index_max", i))), "sun_kwh_m2": None if mj is None else round(mj / 3.6, 2),
                     "sunrise": _hm(at("sunrise", i)), "sunset": _hm(at("sunset", i))})
    c = j.get("current") or {}
    code = _num(c.get("weather_code"))
    code = None if code is None else int(code)
    current = {"t": str(c.get("time", "")).replace("T", " "), "temp_c": _r(_num(c.get("temperature_2m"))),
               "rh_pct": _r(_num(c.get("relative_humidity_2m")), 0), "feels_c": _r(_num(c.get("apparent_temperature"))),
               "code": code, "condition": condition(code), "cloud_pct": _r(_num(c.get("cloud_cover")), 0),
               "wind_kmh": _r(_num(c.get("wind_speed_10m"))), "precip_mm": _r(_num(c.get("precipitation")), 2),
               "is_day": None if _num(c.get("is_day")) is None else int(_num(c.get("is_day")))} if c else None
    return {"hours": hours, "days": days, "current": current, "utc_offset_s": int(_num(j.get("utc_offset_seconds")) or 0),
            "timezone": j.get("timezone"), "elevation_m": _num(j.get("elevation")),
            "grid_lat": _num(j.get("latitude")), "grid_lon": _num(j.get("longitude"))}


def _cell(v):
    if v is None:
        return ""
    return f"{v:g}" if isinstance(v, float) else str(v)


def _last_line(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 2048))
            lines = f.read().decode("utf-8", "replace").strip().split("\n")
    except FileNotFoundError:
        return None
    return lines[-1] if len(lines) > 1 else None   # the header alone: nothing logged


class Weather:
    def __init__(self, store, fetch=fetch_open_meteo):
        self.store = store
        self.fetch = fetch
        self.lock = threading.RLock()
        self.last_try = {}     # site -> time.time() of the last attempt (success or not)
        self.errors = {}       # site -> last error text, cleared on success
        self._cache = {}       # path -> (mtime_ns, size, rows)

    # ------------------------------------------------------------------ settings and paths
    def settings(self, site):
        """The site's weather settings, or None when weather is off or lat/lon are missing or wrong."""
        prof = self.store.site_profile(site)
        w = prof.get("weather")
        if not isinstance(w, dict) or w.get("enabled") is False:
            return None
        lat, lon = _num(w.get("lat")), _num(w.get("lon"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        try:
            hour = int(w.get("dayahead_hour", 18))
        except (TypeError, ValueError):
            hour = 18
        model = str(w.get("model") or "best_match")
        tz = prof.get("timezone") if TZ_RE.match(str(prof.get("timezone") or "")) else None
        return {"lat": lat, "lon": lon, "dayahead_hour": min(23, max(0, hour)),
                "model": model if MODEL_RE.match(model) else "best_match", "timezone": tz}

    def dir(self, site):
        return os.path.join(self.store.site_dir(site), "weather")

    def path(self, site, kind, year=None):
        return os.path.join(self.dir(site), f"{kind}-{year}.csv" if year else f"{kind}.json")

    def forecast(self, site):
        try:
            with open(self.path(site, "forecast"), encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return None

    # ------------------------------------------------------------------ fetching
    def tick(self):
        """Called every minute by the server: fetch the sites whose forecast is older than WEATHER_EVERY_MIN."""
        now = time.time()
        for site in self.store.sites():
            if not self.settings(site):
                continue
            fc = self.forecast(site)
            age = now - fc["fetched_unix"] if fc and fc.get("fetched_unix") else None
            if age is not None and age < EVERY_S:
                continue
            if now - self.last_try.get(site, 0) < RETRY_S:
                continue
            try:
                self.update(site)
            except Exception as e:   # keep going with the other sites; shown on the page
                sys.stderr.write(f"{iso_now()} weather {site}: {e}\n")

    def update(self, site, now=None):
        """Fetch, save forecast.json, append to the logs. Returns {"actual": n rows, "dayahead": n rows}."""
        cfg = self.settings(site)
        if not cfg:
            raise ValueError(f"weather is not set for {site}: lat and lon in site.json (manage.py weather)")
        self.last_try[site] = time.time()
        try:
            p = parse(self.fetch(cfg))
            if not p["hours"]:
                raise RuntimeError("Open-Meteo answer without hourly data")
        except Exception as e:
            self.errors[site] = str(e)[:300]
            raise
        now = now or datetime.now(timezone.utc)
        local_now = (now + timedelta(seconds=p["utc_offset_s"])).replace(tzinfo=None)
        fetched = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.lock:
            doc = dict(p, site=site, source=SOURCE, model=cfg["model"], lat=cfg["lat"], lon=cfg["lon"],
                       fetched=fetched, fetched_unix=int(now.timestamp()), dayahead_hour=cfg["dayahead_hour"])
            atomic_write(self.path(site, "forecast"), json.dumps(doc, separators=(",", ":")) + "\n")
            n_act = self._log_actual(site, p["hours"], local_now, fetched)
            n_da = self._log_dayahead(site, p["hours"], local_now, fetched, cfg["dayahead_hour"])
        self.errors.pop(site, None)
        return {"actual": n_act, "dayahead": n_da, "hours": len(p["hours"])}

    def _append(self, path, cols, rows):
        if not rows:
            return 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", encoding="utf-8", newline="") as f:
            if new:
                f.write(",".join(cols) + "\n")
            for r in rows:
                f.write(",".join(_cell(r.get(c)).replace(",", " ") for c in cols) + "\n")
        return len(rows)

    def _last_t(self, site, kind, year):
        for y in (year, year - 1):
            ln = _last_line(self.path(site, kind, y))
            if ln:
                return ln.split(",", 1)[0]
        return ""

    def _log_actual(self, site, hours, local_now, fetched):
        """Every hour that ended at least LOG_DELAY_H ago and is not logged yet (the logs only grow)."""
        limit = (local_now - timedelta(hours=1 + LOG_DELAY_H)).strftime("%Y-%m-%d %H:00")
        last = self._last_t(site, "actual", local_now.year)
        todo = [dict(r, fetched_utc=fetched) for r in hours if last < r["t"] <= limit and r["temp_c"] is not None]
        n = 0
        for year in sorted({r["t"][:4] for r in todo}):
            n += self._append(self.path(site, "actual", year), ACTUAL_COLS, [r for r in todo if r["t"][:4] == year])
        return n

    def _log_dayahead(self, site, hours, local_now, fetched, at_hour):
        """Tomorrow's 24 hours, once, on the first fetch at or after dayahead_hour (hotel time)."""
        if local_now.hour < at_hour:
            return 0
        tomorrow = (local_now + timedelta(days=1)).strftime("%Y-%m-%d")
        if self._last_t(site, "dayahead", local_now.year)[:10] >= tomorrow:
            return 0
        rows = [dict(r, issued_utc=fetched) for r in hours if r["t"].startswith(tomorrow)]
        return self._append(self.path(site, "dayahead", tomorrow[:4]), DAYAHEAD_COLS, rows)

    # ------------------------------------------------------------------ reading
    def _read(self, path):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return []
        with self.lock:   # several dashboards and pages read at the same time
            hit = self._cache.get(path)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                return hit[2]
            with open(path, encoding="utf-8", newline="") as f:
                rows = [r for r in csv.DictReader(f) if r.get("t") and len(r["t"]) == 16]
            self._cache[path] = (st.st_mtime_ns, st.st_size, rows)
            if len(self._cache) > 64:
                self._cache.pop(next(iter(self._cache)))
            return rows

    def local_now(self, site):
        fc = self.forecast(site)
        off = fc.get("utc_offset_s") if fc else None
        if off is None:
            try:
                off = float(self.store.site_profile(site).get("utc_offset_h", 8)) * 3600
            except (TypeError, ValueError):
                off = 8 * 3600
        return (datetime.now(timezone.utc) + timedelta(seconds=off)).replace(tzinfo=None)

    def view(self, site):
        """GET /api/v1/weather/<site>: the last forecast, hour by hour and per day."""
        cfg = self.settings(site)
        out = {"site": site, "enabled": bool(cfg), "source": SOURCE, "error": self.errors.get(site),
               "now": self.local_now(site).strftime("%Y-%m-%d %H:%M")}
        fc = self.forecast(site)
        if fc:
            out.update({k: fc.get(k) for k in ("fetched", "model", "lat", "lon", "timezone", "elevation_m", "current",
                                               "days", "dayahead_hour")})
            out["age_s"] = int(time.time() - fc.get("fetched_unix", 0))
            today = out["now"][:10]
            out["hours"] = [r for r in fc.get("hours", []) if r["t"][:10] >= today]
        return out

    def log(self, site, days=7):
        """GET /api/v1/weather/<site>/log: actual weather per hour with the day-ahead forecast of that hour."""
        days = max(1, min(int(days), MAX_LOG_DAYS))
        now = self.local_now(site)
        start = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00")
        years = range(int(start[:4]), now.year + 1)
        fc = {}
        for y in years:
            for r in self._read(self.path(site, "dayahead", y)):
                if r["t"] >= start:
                    fc[r["t"]] = r
        hours = []
        for y in years:
            for r in self._read(self.path(site, "actual", y)):
                if r["t"] < start:
                    continue
                o = {"t": r["t"]}
                for c in ACTUAL_COLS[1:]:
                    o[c] = r.get(c) if c in ("condition", "fetched_utc") else _num(r.get(c))
                f = fc.get(r["t"])
                for c in FC_KEYS:
                    o["fc_" + c] = (f.get(c) if c == "condition" else _num(f.get(c))) if f else None
                o["fc_issued_utc"] = f.get("issued_utc") if f else None
                hours.append(o)
        hours.sort(key=lambda r: r["t"])
        per = {}
        for r in hours:
            d = per.setdefault(r["t"][:10], {"date": r["t"][:10], "hours": 0, "t": [], "rain": 0.0, "sun": 0.0, "code": None,
                                              "fc_t": [], "fc_rain": 0.0, "fc_hours": 0, "fc_code": None})
            d["hours"] += 1
            if r["temp_c"] is not None:
                d["t"].append(r["temp_c"])
            d["rain"] += r["precip_mm"] or 0
            d["sun"] += r["rad_wm2"] or 0
            if r["code"] is not None:
                d["code"] = max(d["code"] or 0, int(r["code"]))
            if r["fc_temp_c"] is not None:
                d["fc_hours"] += 1
                d["fc_t"].append(r["fc_temp_c"])
                d["fc_rain"] += r["fc_precip_mm"] or 0
                if r["fc_code"] is not None:
                    d["fc_code"] = max(d["fc_code"] or 0, int(r["fc_code"]))
        out_days = []
        for k in sorted(per):
            d = per[k]
            out_days.append({"date": k, "hours": d["hours"], "tmin_c": min(d["t"], default=None), "tmax_c": max(d["t"], default=None),
                             "precip_mm": round(d["rain"], 1), "sun_kwh_m2": round(d["sun"] / 1000, 2), "code": d["code"],
                             "condition": condition(d["code"]), "fc_hours": d["fc_hours"],
                             "fc_tmin_c": min(d["fc_t"], default=None), "fc_tmax_c": max(d["fc_t"], default=None),
                             "fc_precip_mm": round(d["fc_rain"], 1) if d["fc_hours"] else None, "fc_code": d["fc_code"],
                             "fc_condition": condition(d["fc_code"])})
        return {"site": site, "from": start, "now": now.strftime("%Y-%m-%d %H:%M"), "source": SOURCE,
                "hours": hours, "days": out_days}

    def log_csv(self, site, days=7):
        j = self.log(site, days)
        cols = list(ACTUAL_COLS) + ["fc_" + c for c in FC_KEYS] + ["fc_issued_utc"]
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(cols)
        for r in j["hours"]:
            w.writerow([_cell(r.get(c)) for c in cols])
        return buf.getvalue()
