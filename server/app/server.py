"""Ingest service for the loggers (Python standard library only).

Device endpoints (token in "Authorization: Bearer <token>", no web login in Caddy):
  POST /api/v1/ingest          text/csv: header line + 1-minute rows, stored in the site's day files
  POST /api/v1/live            JSON snapshot every 15 s: last 60 min in memory, every snapshot saved (LIVE_KEEP_DAYS)
  GET  /api/v1/ota?fw=x.y.z    204 = up to date, 200 = {"version","url","md5","size"}
  GET  /api/v1/firmware/<file> firmware image for the OTA update
  GET  /api/v1/config          204 = nothing set, 200 = {"version", "settings"} (manage.py set-config)
  POST /api/v1/config/report   JSON: the logger's firmware, settings (no secrets), columns, register table
  GET  /api/v1/registers       204 = nothing set, 200 = {"version", "builtin", "csv"} (register table page)

People endpoints (behind the Caddy web login, never published without it):
  GET  /health                 {"ok": true}
  GET  /api/v1/status          every site and logger: last record, last live, firmware
  GET  /api/v1/live/<site>     live values, 60-minute history and open alarms of a site
  GET  /api/v1/live/<site>/day/<YYYY-MM-DD>?device=   every saved 15 s snapshot of that UTC day
  GET  /api/v1/alarms/<site>   open alarms and the last 200 lines of the alarm log
  GET  /api/v1/versions/<site> firmware of each logger: running, since, offer, every change and restart,
                               GitHub releases (asked once an hour), files on the server (read only, everyone)
  GET  /api/v1/history/<site>?days=15        one row per local hour: kWh, kW, sensors (from the day files)
  GET  /api/v1/history/<site>/day/<date>     the 1-minute power of one local day
  GET  /api/v1/quality/<site>?days=14        power quality per local hour: voltage per phase (mean, lowest, highest),
                                             frequency, power factor, kW, kvar, kWh, kVArh, unbalance, dips, swells,
                                             the limits of the alarm register and the power quality alarm lines
  GET  /api/v1/quality/<site>/day/<date>     the 1-minute voltage (mean, lowest, highest), frequency, power factor
  GET  /api/v1/weather/<site>                Open-Meteo forecast (fetched every hour): today and tomorrow per hour
  GET  /api/v1/weather/<site>/log?days=7     actual weather per hour with the day-ahead forecast (&format=csv)
  GET  /live/  /live/<site>/   site page: live now (refresh every 15 s) and the history graphs
  GET  /live/<site>/register   meter register table page of the site's logger (?device=LOG-0002 if several):
                               see, edit, import, send to the logger
  GET  /api/v1/admin/registers/<device>          table on the logger, table asked, history
  POST /api/v1/admin/registers/<device>/check    JSON {"csv"}: errors, warnings, normalised table
  POST /api/v1/admin/registers/<device>          JSON {"csv", "comment"} or {"builtin": true}: new version
  POST /api/v1/admin/meter-settings/<device>     JSON {meters, mb_baud, mb_format, ct_mult}: remote settings
  Admin POSTs must be JSON (Content-Type application/json) and same-origin: a page on another site
  cannot make a logged-in browser send them.

Firmware update from the site page (people in ADMIN_USERS only, see docs/OTA.md):
  GET  /api/v1/admin/me                     {"user", "admin", "github"}
  GET  /api/v1/admin/fw/<device>            running firmware, what is offered, stored files, recent events
  GET  /api/v1/admin/github/releases        logger-*.bin assets of the repository's releases
  POST /api/v1/admin/fw/<device>/upload     body: the .bin (application/octet-stream), ?force=1
  POST /api/v1/admin/fw/<device>/offer      {"file": "logger-0.3.1.bin", "force": false}
  POST /api/v1/admin/fw/<device>/github     {"asset_id": 123, "force": false}
  POST /api/v1/admin/fw/<device>/cancel     withdraw the offer made to that logger
  POST requests need the header "X-Requested-With: arkan" (a page on another site cannot send it).

Settings (environment): DATA_DIR (/data), PORT (8800), BIND (0.0.0.0 in the container),
MAX_BODY (262144 bytes), ADMIN_USERS (Caddy login names allowed to update firmware, comma separated,
"*" = everyone who can log in, empty = nobody), FW_GITHUB_REPO (owner/name), FW_GITHUB_TOKEN,
WEATHER (on; off = never fetch the forecast), WEATHER_EVERY_MIN (60), LIVE_KEEP_DAYS (7). Weather per site: site.json "weather"
(app/weather.py, manage.py weather).
"""

import json
import os
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402
import quality  # noqa: E402
import registers  # noqa: E402
import weather  # noqa: E402
from alarms import AlarmEngine  # noqa: E402
from firmware import MAX_IMAGE, Firmware, FirmwareError, GitHub  # noqa: E402
from store import CODE_RE, DEVICE_RE, DataStore, IngestError, atomic_write, iso_now  # noqa: E402

VERSION = "0.7.0"
DATA_DIR = os.environ.get("DATA_DIR", "/data")
MAX_BODY = int(os.environ.get("MAX_BODY", "262144"))
LIVE_POINTS = 240                      # 60 minutes at 15 s
LIVE_KEEP_DAYS = int(os.environ.get("LIVE_KEEP_DAYS", "7"))   # days of saved 15 s snapshots, 0 = memory only
HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = {"live": "live.html"}
# The Arkan UI kit the page loads (server/app/arkan-ui/, a copy of the CMMS's kit): /live/_ui/<file>
UI_FILES = {"arkan-ui.css": "text/css; charset=utf-8", "arkan-ui.js": "text/javascript; charset=utf-8"}
# Meter link settings the register page may change remotely (firmware/src/settings.cpp).
METER_KEYS = ("meters", "mb_baud", "mb_format", "ct_mult")
BAUDS = ("1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200")
FORMATS = ("8N1", "8E1", "8O1", "8N2")
METERS_RE = re.compile(r"^[A-Za-z0-9]{1,7}:\d{1,3}(,[A-Za-z0-9]{1,7}:\d{1,3}){0,3}$")
# Register page endpoints (JSON, same origin); every other /api/v1/admin/ POST is a firmware update.
REGISTERS_ADMIN_RE = re.compile(r"^/api/v1/admin/(registers|meter-settings)/")


class Live:
    """15-second snapshots per site and device.

    The last 60 minutes are kept in memory for the live page, and every snapshot is also saved in the data
    folder, so another dashboard can read the same live data and a restart does not empty the page:
        sites/<site>/<device>/live.json                   the last snapshot (rewritten whole, never half written)
        sites/<site>/<device>/live/YYYY-MM-DD.jsonl       every snapshot of that UTC day, one JSON per line
    "recv" = when the server received it (UTC), "ts" = the logger's clock. Day files older than
    LIVE_KEEP_DAYS (7) are deleted; LIVE_KEEP_DAYS=0 = memory only, nothing saved (before 0.5.0).
    """

    def __init__(self, store=None, keep_days=None):
        self.lock = threading.Lock()
        self.wlock = threading.Lock()
        self.data = {}   # site -> device -> deque of (received_epoch, snapshot dict)
        self.store = store
        self.keep_days = LIVE_KEEP_DAYS if keep_days is None else keep_days
        if self.store and self.keep_days > 0:
            self.restore()

    def dir(self, site, device):
        return self.store.device_dir(site, device)

    def add(self, site, device, snap):
        now = time.time()
        with self.lock:
            q = self.data.setdefault(site, {}).setdefault(device, deque(maxlen=LIVE_POINTS))
            q.append((now, snap))
        if self.store and self.keep_days > 0:
            self.save(site, device, now, snap)

    def save(self, site, device, now, snap):
        recv = datetime.fromtimestamp(now, timezone.utc)
        doc = dict(snap, recv=recv.strftime("%Y-%m-%dT%H:%M:%SZ"))
        line = json.dumps(doc, separators=(",", ":"), sort_keys=True)
        d = self.dir(site, device)
        try:
            with self.wlock:
                os.makedirs(os.path.join(d, "live"), exist_ok=True)
                with open(os.path.join(d, "live", recv.strftime("%Y-%m-%d") + ".jsonl"), "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                atomic_write(os.path.join(d, "live.json"), line + "\n")
        except OSError as e:   # a full disk must not stop the live page
            sys.stderr.write(f"{iso_now()} live snapshot not saved for {device}: {e}\n")

    def read_day(self, site, device, day):
        """Every saved snapshot of a UTC day, oldest first. A last line still being written is skipped."""
        p = os.path.join(self.dir(site, device), "live", day + ".jsonl")
        out = []
        try:
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    if not ln.endswith("\n"):
                        break
                    try:
                        out.append(json.loads(ln))
                    except ValueError:
                        continue
        except FileNotFoundError:
            pass
        return out

    def restore(self):
        """Refill the last 60 minutes from the saved snapshots (after a restart or an update)."""
        now = datetime.now(timezone.utc)
        since = now.timestamp() - LIVE_POINTS * 15 - 60
        days = [(now - timedelta(days=1)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")]
        for site in self.store.sites():
            for device in self.store.site_devices(site):
                for day in days:
                    for doc in self.read_day(site, device, day):
                        try:
                            t = datetime.strptime(doc.pop("recv"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                        except (KeyError, TypeError, ValueError):
                            continue
                        if t >= since:
                            with self.lock:
                                self.data.setdefault(site, {}).setdefault(device, deque(maxlen=LIVE_POINTS)).append((t, doc))

    def prune(self):
        """Delete the day files older than LIVE_KEEP_DAYS."""
        if not self.store or self.keep_days <= 0:
            return
        oldest = (datetime.now(timezone.utc) - timedelta(days=self.keep_days)).strftime("%Y-%m-%d")
        for site in self.store.sites():
            for device in self.store.site_devices(site):
                d = os.path.join(self.dir(site, device), "live")
                if not os.path.isdir(d):
                    continue
                for fn in os.listdir(d):
                    if fn.endswith(".jsonl") and fn[:10] < oldest:
                        os.unlink(os.path.join(d, fn))

    def site(self, site):
        with self.lock:
            devs = self.data.get(site, {})
            out = {}
            for dev, q in devs.items():
                if not q:
                    continue
                recv, last = q[-1]
                out[dev] = {
                    "last": last,
                    "age_s": round(time.time() - recv),
                    "history": [{"ts": s.get("ts"), "values": s.get("values", {})} for _, s in q],
                }
            return out

    def last_seen(self, site, device):
        with self.lock:
            q = self.data.get(site, {}).get(device)
            return q[-1][0] if q else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # keep-alive: the logger reuses its TLS connection
    server_version = "arkan-ingest/" + VERSION
    store: DataStore = None
    live: Live = None
    fw: Firmware = None
    github: GitHub = None
    admin_users = ""

    # ------------------------------------------------------------------ helpers
    def log_message(self, fmt, *args):   # one short line per request, no tokens
        sys.stderr.write("%s %s %s\n" % (iso_now(), self.address_string(), fmt % args))

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_empty(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            # Drain is not attempted: close the connection instead.
            self.close_connection = True
            return None
        return self.rfile.read(n) if n else b""

    def device(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        return self.store.authenticate(token)

    # ------------------------------------------------------------------ routes
    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/v1/admin/") and not REGISTERS_ADMIN_RE.match(path):
            return self.admin_post(path)       # firmware update (reads its own body, larger limit)
        body = self.read_body()
        if body is None:
            return self.send_json(413, {"ok": False, "error": "body too large"})
        if path.startswith("/api/v1/admin/"):
            return self.registers_post(path, body)
        who = self.device()
        if not who:
            return self.send_json(401, {"ok": False, "error": "unknown or missing device token"})
        device, site = who
        claimed = self.headers.get("X-Device")
        if claimed and claimed != device:
            return self.send_json(403, {"ok": False, "error": "token belongs to another device"})
        self.store.note_firmware(site, device, self.headers.get("X-Fw"))
        if path == "/api/v1/ingest":
            try:
                res = self.store.ingest(site, device, body.decode("utf-8", "replace"))
            except IngestError as e:
                return self.send_json(400, {"ok": False, "error": str(e)})
            return self.send_json(200, res)
        if path == "/api/v1/live":
            try:
                snap = json.loads(body or b"{}")
                if not isinstance(snap, dict) or len(body) > 8192:
                    raise ValueError
            except ValueError:
                return self.send_json(400, {"ok": False, "error": "bad JSON"})
            snap["device"] = device
            self.live.add(site, device, snap)
            self.store.alarms.check_clock(site, device, snap.get("ts"))
            # A firmware is waiting for this logger: tell it to check now rather than in up to 6 h.
            if self.fw.offer_for(device, self.headers.get("X-Fw")):
                return self.send_json(200, {"ota": 1})
            return self.send_empty(204)
        if path == "/api/v1/config/report":
            try:
                rep = json.loads(body or b"{}")
                if not isinstance(rep, dict):
                    raise ValueError
            except ValueError:
                return self.send_json(400, {"ok": False, "error": "bad JSON"})
            self.store.save_report(site, device, rep)
            if str(rep.get("boot", "")).startswith("sw:ota_rollback"):
                self.fw.note_rollback(site, device)
            return self.send_empty(204)
        return self.send_json(404, {"ok": False, "error": "not found"})

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/health":
            return self.send_json(200, {"ok": True, "version": VERSION, "time": iso_now()})
        if path == "/api/v1/status":
            return self.send_json(200, self.status())
        m = re.match(r"^/api/v1/live/([a-z0-9-]+)$", path)
        if m and CODE_RE.match(m.group(1)):
            site = m.group(1)
            return self.send_json(200, {"site": site, "profile": self.public_profile(site),
                                        "devices": self.live.site(site),
                                        "alarms": self.store.alarms.open_alarms(site), "time": iso_now()})
        m = re.match(r"^/api/v1/live/([a-z0-9-]+)/day/(\d{4}-\d{2}-\d{2})$", path)
        if m and CODE_RE.match(m.group(1)) and m.group(1) in self.store.sites():
            devs = self.store.site_devices(m.group(1))
            dev = parse_qs(u.query).get("device", [devs[0] if devs else ""])[0]
            if dev not in devs:
                return self.send_json(404, {"ok": False, "error": "no such logger on this site"})
            return self.send_json(200, {"site": m.group(1), "device": dev, "day_utc": m.group(2),
                                        "snapshots": self.live.read_day(m.group(1), dev, m.group(2))})
        m = re.match(r"^/api/v1/versions/([a-z0-9-]+)$", path)
        if m and CODE_RE.match(m.group(1)) and m.group(1) in self.store.sites():
            rel, err = self.cached_releases()
            return self.send_json(200, self.fw.site_view(m.group(1), rel, err))
        m = re.match(r"^/api/v1/alarms/([a-z0-9-]+)$", path)
        if m and CODE_RE.match(m.group(1)):
            return self.send_json(200, self.alarm_view(m.group(1)))
        m = re.match(r"^/api/v1/(history|quality)/([a-z0-9-]+)(?:/day/(\d{4}-\d{2}-\d{2}))?$", path)
        if m and CODE_RE.match(m.group(2)) and m.group(2) in self.store.sites():
            return self.history(m.group(2), m.group(3), parse_qs(u.query), m.group(1))
        m = re.match(r"^/api/v1/weather/([a-z0-9-]+)(/log)?$", path)
        if m and CODE_RE.match(m.group(1)) and m.group(1) in self.store.sites():
            return self.weather_view(m.group(1), bool(m.group(2)), parse_qs(u.query))
        if path in ("/live", "/live/") or re.match(r"^/live/[a-z0-9-]+/?$", path):
            return self.page("live")
        if path.startswith("/live/_ui/") and path[10:] in UI_FILES:
            return self.page(path[10:], UI_FILES[path[10:]])
        m = re.match(r"^/live/([a-z0-9-]+)/register/?$", path)
        if m:                                   # the register page is now a page of the site: old links keep working
            self.send_response(302)
            self.send_header("Location", f"/live/{m.group(1)}/#register")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        m = re.match(r"^/api/v1/admin/registers/([A-Za-z0-9_-]+)$", path)
        if m:
            return self.registers_view(m.group(1))
        if path.startswith("/api/v1/admin/"):
            return self.admin_get(path)
        if path == "/api/v1/registers":
            return self.device_registers()
        if path == "/api/v1/ota":
            return self.ota(parse_qs(u.query).get("fw", [""])[0])
        if path == "/api/v1/config":
            who = self.device()
            if not who:
                return self.send_json(401, {"ok": False, "error": "unknown or missing device token"})
            cfg = self.store.get_config(who[1], who[0])
            if not cfg or not cfg.get("settings"):
                return self.send_empty(204)
            return self.send_json(200, {"version": cfg["version"], "settings": cfg["settings"]})
        m = re.match(r"^/api/v1/firmware/([A-Za-z0-9._-]+\.bin)$", path)
        if m:
            return self.firmware(m.group(1))
        return self.send_json(404, {"ok": False, "error": "not found"})

    def page(self, name, ctype=None):
        """The site page, or with ctype a file of the UI kit (the browser may keep it 5 minutes)."""
        with open(os.path.join(HERE, "arkan-ui", name) if ctype else os.path.join(HERE, PAGES[name]), "rb") as f:
            page = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "max-age=300" if ctype else "no-store")
        self.end_headers()
        return self.wfile.write(page)

    # ------------------------------------------------------------------ register table
    def device_site(self, device):
        if not DEVICE_RE.match(device):
            return None
        info = self.store.load_devices().get("devices", {}).get(device)
        return info.get("site") if info else None

    def auth_user(self):
        """Login name passed by Caddy (header_up X-Auth-User), for the history. Empty when run locally."""
        return re.sub(r"[^A-Za-z0-9_.@-]", "", self.headers.get("X-Auth-User", ""))[:40]

    def device_registers(self):
        who = self.device()
        if not who:
            return self.send_json(401, {"ok": False, "error": "unknown or missing device token"})
        device, site = who
        cur = self.store.get_registers(site, device)
        if not cur or not cur.get("version"):
            return self.send_empty(204)
        csv = None
        if not cur.get("builtin"):
            by = re.sub(r"[^A-Za-z0-9_.@ -]", "", cur.get("by") or "")
            csv = f"# register table version {cur['version']} from the platform, {cur.get('updated', '')}" \
                  f"{', by ' + by if by else ''}\n" + cur["csv"]
        return self.send_json(200, {"version": cur["version"], "builtin": bool(cur.get("builtin")), "csv": csv})

    def registers_view(self, device):
        site = self.device_site(device)
        if not site:
            return self.send_json(404, {"ok": False, "error": "no such logger"})
        want = self.store.get_registers(site, device)
        rep = self.store.get_report(site, device)
        reported = None
        state = "none"
        if rep:
            rows, errs, _ = registers.parse(rep.get("registers") or "")
            sett = rep.get("settings") or {}
            reported = {k: rep.get(k) for k in ("received", "fw", "boot", "reg_version", "reg_source", "reg_error",
                                                 "reg_refused", "registers", "header")}
            reported["rows"] = rows if not errs else []
            reported["settings"] = {k: sett.get(k) for k in METER_KEYS + ("rcfg_on", "rcfg_check_m")}
        if want:
            if not rep:
                state = "waiting"
            elif "reg_version" not in rep:
                state = "unsupported"      # firmware before 0.4.0: no remote register table
            elif rep.get("reg_refused") == want["version"]:
                state = "refused"
            elif int(rep.get("reg_version") or 0) >= want["version"]:
                if want.get("builtin"):
                    state = "applied" if rep.get("reg_source") == "builtin" else "differs"
                else:
                    wrows, _, _ = registers.parse(want.get("csv") or "")
                    state = "applied" if registers.same(wrows, reported["rows"]) else "differs"
            else:
                state = "waiting"
        hist = list(reversed(self.store.registers_history(site, device)))[:50]
        return self.send_json(200, {
            "device": device, "site": site, "time": iso_now(), "state": state, "platform": want,
            "reported": reported, "history": hist, "config": self.store.get_config(site, device),
            "types": registers.TYPES, "aggs": registers.AGGS, "standard": registers.STANDARD,
            "max_regs": registers.MAX_REGS})

    def registers_post(self, path, body):
        # Behind the Caddy web login. A form on another site cannot send JSON, a cross-site fetch with
        # JSON needs a CORS preflight that this service never answers, and the Origin must be this host.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self.send_json(415, {"ok": False, "error": "JSON only"})
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host", ""):
            return self.send_json(403, {"ok": False, "error": "cross-site request refused"})
        try:
            req = json.loads(body or b"{}")
            if not isinstance(req, dict):
                raise ValueError
        except ValueError:
            return self.send_json(400, {"ok": False, "error": "bad JSON"})
        m = re.match(r"^/api/v1/admin/(registers|meter-settings)/([A-Za-z0-9_-]+)(/check)?$", path)
        site = self.device_site(m.group(2)) if m else None
        if not site:
            return self.send_json(404, {"ok": False, "error": "not found"})
        device = m.group(2)
        if m.group(1) == "meter-settings" and not m.group(3):
            return self.save_meter_settings(site, device, req)
        if m.group(1) != "registers":
            return self.send_json(404, {"ok": False, "error": "not found"})
        if req.get("builtin") and not m.group(3):
            ver = self.store.set_registers(site, device, builtin=True, by=self.auth_user(),
                                           comment=str(req.get("comment") or ""))
            return self.send_json(200, {"ok": True, "version": ver})
        text = req.get("csv")
        if not isinstance(text, str):
            return self.send_json(400, {"ok": False, "error": "csv missing"})
        rows, errors, warnings = registers.parse(text)
        res = {"ok": not errors, "errors": errors, "warnings": warnings, "rows": rows,
               "csv": registers.to_csv(rows) if not errors else None}
        if m.group(3) or errors:
            return self.send_json(200 if m.group(3) else 400, res)
        res["version"] = self.store.set_registers(site, device, res["csv"], by=self.auth_user(),
                                                  comment=str(req.get("comment") or ""))
        return self.send_json(200, res)

    def save_meter_settings(self, site, device, req):
        changes, errors = {}, []
        for k in METER_KEYS:
            v = str(req.get(k) or "").strip()
            if not v:
                continue
            if k == "meters":
                ok = bool(METERS_RE.match(v)) and all(1 <= int(x.split(":")[1]) <= 247 for x in v.split(","))
                ids = [x.split(":")[0] for x in v.split(",")] if ok else []
                ok = ok and len(set(ids)) == len(ids)
            elif k == "mb_baud":
                ok = v in BAUDS
            elif k == "mb_format":
                v = v.upper()
                ok = v in FORMATS
            else:
                try:
                    ok = 0 < float(v) <= 100000
                except ValueError:
                    ok = False
            if not ok:
                errors.append(f"{k}: '{v}' is not valid")
            changes[k] = v
        if errors or not changes:
            return self.send_json(400, {"ok": False, "errors": errors or ["nothing to change"]})
        ver = self.store.set_config(site, device, changes)
        return self.send_json(200, {"ok": True, "version": ver, "settings": changes})

    # ------------------------------------------------------------------ pieces
    def public_profile(self, site):
        p = self.store.site_profile(site)
        keys = ("name", "timezone", "utc_offset_h", "labels", "live", "sensors", "contracted_kva", "contract_v_ln", "rated_a",
                "nominal_v")
        return {k: p.get(k) for k in keys if k in p}

    def history(self, site, day, q, kind="history"):
        devs = self.store.site_devices(site)
        dev = q.get("device", [devs[0] if devs else ""])[0]
        if dev not in devs:
            return self.send_json(404, {"ok": False, "error": "no such logger on this site"})
        meter = q.get("meter", ["EM01"])[0]
        if not re.match(r"^[A-Z]{2}\d{2}$", meter):
            return self.send_json(400, {"ok": False, "error": "bad meter"})
        try:
            if kind == "quality":
                if day:
                    return self.send_json(200, quality.minutes(self.store, site, dev, day, meter))
                return self.send_json(200, quality.hourly(self.store, self.store.alarms, site, dev,
                                                          int(q.get("days", ["14"])[0]), meter))
            if day:
                return self.send_json(200, history.minutes(self.store, site, dev, day, meter))
            return self.send_json(200, history.hourly(self.store, site, dev, int(q.get("days", ["15"])[0]), meter))
        except ValueError:
            return self.send_json(400, {"ok": False, "error": "bad date or days"})

    _releases = {"at": 0, "rel": None, "err": None}

    def cached_releases(self):
        """GitHub releases for the versions page, asked at most once an hour (GitHub limits anonymous calls)."""
        c = Handler._releases
        if not self.github or not self.github.configured():
            return None, "FW_GITHUB_REPO is not set on the server"
        if time.time() - c["at"] > (3600 if c["rel"] is not None else 600):
            try:
                c["rel"], c["err"] = self.github.releases(20), None
            except FirmwareError as e:
                c["err"] = str(e)
            c["at"] = time.time()
        return c["rel"], c["err"]

    def weather_view(self, site, log, q):
        if not log:
            return self.send_json(200, self.weather.view(site))
        try:
            days = int(q.get("days", ["7"])[0])
        except ValueError:
            return self.send_json(400, {"ok": False, "error": "bad days"})
        if q.get("format", [""])[0] != "csv":
            return self.send_json(200, self.weather.log(site, days))
        body = self.weather.log_csv(site, days).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="weather-{site}-{days}d.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return self.wfile.write(body)

    def status(self):
        out = {"time": iso_now(), "sites": {}}
        for site in self.store.sites():
            devs = {}
            for dev in self.store.site_devices(site):
                info = self.store.load_devices()["devices"][dev]
                seen = self.live.last_seen(site, dev)
                devs[dev] = {
                    "last_record": self.store.last_record(site, dev),
                    "live_age_s": round(time.time() - seen) if seen else None,
                    "fw": info.get("fw"),
                }
            out["sites"][site] = devs
        return out

    def alarm_view(self, site):
        d = os.path.join(self.store.site_dir(site), "alarms")
        lines = []
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d), reverse=True):
                if fn.endswith(".csv"):
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        lines = f.read().splitlines()[1:] + lines
                if len(lines) >= 200:
                    break
        return {"site": site, "open": self.store.alarms.open_alarms(site), "log_header": "ts_utc,local_time,device,id,"
                "name,severity,state,value,threshold,unit,duration_min,message", "log": lines[-200:]}

    def ota(self, fw):
        who = self.device()
        if not who:
            return self.send_json(401, {"ok": False, "error": "unknown or missing device token"})
        device, _ = who
        # Never a downgrade of a logger flashed by hand with a newer version unless the entry is marked
        # force (a deliberate step back), never a version this logger already rolled back.
        entry = self.fw.offer_for(device, fw)
        if not entry:
            return self.send_empty(204)
        return self.send_json(200, {"version": entry["version"], "md5": entry.get("md5", ""),
                                    "size": entry.get("size"), "url": "/api/v1/firmware/" + entry["file"]})

    def firmware(self, name):
        if not self.device():
            return self.send_json(401, {"ok": False, "error": "unknown or missing device token"})
        p = os.path.join(self.store.root, "firmware", name)
        if not os.path.isfile(p):
            return self.send_json(404, {"ok": False, "error": "no such firmware"})
        size = os.path.getsize(p)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(p, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)


    # ------------------------------------------------------------------ firmware update (people)
    def admin_user(self):
        """The Caddy login name if it may update firmware, else None. Caddy sets X-Auth-User on every
        request that passed its login; the service only listens on the loopback."""
        user = self.headers.get("X-Auth-User", "").strip()
        allowed = [u.strip() for u in (self.admin_users or "").split(",") if u.strip()]
        if user and ("*" in allowed or user in allowed):
            return user
        return None

    def admin_refused(self):
        if not self.admin_users:
            return self.send_json(403, {"ok": False, "error": "firmware updates from the web page are off: "
                                        "set ADMIN_USERS on the server (docs/OTA.md)"})
        return self.send_json(403, {"ok": False, "error": "your login may not update firmware (ADMIN_USERS)"})

    def admin_get(self, path):
        if path == "/api/v1/admin/me":
            user = self.headers.get("X-Auth-User", "")
            return self.send_json(200, {"user": user, "admin": bool(self.admin_user()),
                                        "github": self.github.configured()})
        if not self.admin_user():
            return self.admin_refused()
        m = re.match(r"^/api/v1/admin/fw/([A-Za-z0-9_-]+)$", path)
        if m and DEVICE_RE.match(m.group(1)):
            view = self.fw.view(m.group(1))
            if view is None:
                return self.send_json(404, {"ok": False, "error": "no such logger"})
            view["files"] = self.fw.files()
            view["github"] = self.github.configured()
            return self.send_json(200, view)
        if path == "/api/v1/admin/github/releases":
            try:
                return self.send_json(200, {"repo": self.github.repo, "releases": self.github.releases()})
            except FirmwareError as e:
                return self.send_json(502, {"ok": False, "error": str(e)})
        return self.send_json(404, {"ok": False, "error": "not found"})

    def admin_post(self, path):
        u = urlparse(self.path)
        m = re.match(r"^/api/v1/admin/fw/([A-Za-z0-9_-]+)/(upload|offer|github|cancel)$", path)
        limit = MAX_IMAGE + 1024 if m and m.group(2) == "upload" else 8192
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            self.close_connection = True
            return self.send_json(413, {"ok": False, "error": "file too large"})
        body = self.rfile.read(n) if n else b""
        # Cross-site protection: a form or script on another site cannot add this header without
        # a CORS preflight, which never gets through the login.
        if self.headers.get("X-Requested-With") != "arkan":
            return self.send_json(403, {"ok": False, "error": "missing X-Requested-With header"})
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.send_json(403, {"ok": False, "error": "request from another site"})
        user = self.admin_user()
        if not user:
            return self.admin_refused()
        if not m or not DEVICE_RE.match(m.group(1)):
            return self.send_json(404, {"ok": False, "error": "not found"})
        device, action = m.group(1), m.group(2)
        if device not in self.store.load_devices().get("devices", {}):
            return self.send_json(404, {"ok": False, "error": "no such logger"})
        try:
            if action == "cancel":
                gone = self.fw.cancel(device, by=user)
                return self.send_json(200, {"ok": True, "cancelled": bool(gone), "view": self.fw.view(device)})
            if action == "upload":
                force = parse_qs(u.query).get("force", ["0"])[0] == "1"
                fname = re.sub(r"[^A-Za-z0-9._-]", "_", parse_qs(u.query).get("name", ["upload.bin"])[0])[:60]
                _, name = self.fw.store_image(body)
                source = "upload " + fname
            else:
                try:
                    req = json.loads(body or b"{}")
                    if not isinstance(req, dict):
                        raise ValueError
                except ValueError:
                    return self.send_json(400, {"ok": False, "error": "bad JSON"})
                force = bool(req.get("force"))
                if action == "offer":
                    name, source = str(req.get("file", "")), "stored file"
                else:
                    asset = int(req.get("asset_id") or 0)
                    data = self.github.download(asset)
                    _, name = self.fw.store_image(data)
                    source = self.github.asset_label(asset)
            entry = self.fw.offer(device, name, force=force, by=user, source=source)
        except (FirmwareError, ValueError) as e:
            return self.send_json(400, {"ok": False, "error": str(e)})
        sys.stderr.write(f"{iso_now()} firmware {entry['version']} offered to {device} by {user} ({source})\n")
        return self.send_json(200, {"ok": True, "offer": entry, "view": self.fw.view(device)})


def make_server(data_dir, bind="127.0.0.1", port=8800):
    os.makedirs(os.path.join(data_dir, "sites"), exist_ok=True)
    store = DataStore(data_dir)
    store.alarms = AlarmEngine(store)
    Handler.store = store
    Handler.live = Live(store)
    Handler.fw = Firmware(store)
    store.on_rollback = Handler.fw.note_rollback
    Handler.github = GitHub()
    Handler.weather = weather.Weather(store)
    Handler.admin_users = os.environ.get("ADMIN_USERS", "")
    srv = ThreadingHTTPServer((bind, port), Handler)
    srv.daemon_threads = True
    return srv


def main():
    bind = os.environ.get("BIND", "0.0.0.0")
    port = int(os.environ.get("PORT", "8800"))
    srv = make_server(DATA_DIR, bind, port)

    def offline_watch():   # A01: a logger that sends nothing; once an hour, old live day files deleted
        n = 0
        while True:
            time.sleep(60)
            try:
                Handler.store.alarms.check_offline()
                if n % 60 == 0:
                    Handler.live.prune()
            except Exception as e:   # never let the watcher die
                sys.stderr.write(f"{iso_now()} offline check failed: {e!r}\n")
            n += 1

    def weather_watch():   # Open-Meteo forecast and the weather logs of the sites that have lat/lon
        while True:
            try:
                Handler.weather.tick()
            except Exception as e:
                sys.stderr.write(f"{iso_now()} weather check failed: {e!r}\n")
            time.sleep(60)

    threading.Thread(target=offline_watch, daemon=True).start()
    if os.environ.get("WEATHER", "on").lower() not in ("off", "0", "no"):
        threading.Thread(target=weather_watch, daemon=True).start()
    sys.stderr.write(f"{iso_now()} arkan-ingest {VERSION} on {bind}:{port}, data in {DATA_DIR}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
