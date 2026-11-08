"""Ingest service for the loggers (Python standard library only).

Device endpoints (token in "Authorization: Bearer <token>", no web login in Caddy):
  POST /api/v1/ingest          text/csv: header line + 1-minute rows, stored in the site's day files
  POST /api/v1/live            JSON snapshot every 15 s, kept in memory only (last 60 min)
  GET  /api/v1/ota?fw=x.y.z    204 = up to date, 200 = {"version","url","md5","size"}
  GET  /api/v1/firmware/<file> firmware image for the OTA update
  GET  /api/v1/config          204 = nothing set, 200 = {"version", "settings"} (manage.py set-config)
  POST /api/v1/config/report   JSON: the logger's firmware, settings (no secrets), columns, after each boot

People endpoints (behind the Caddy web login, never published without it):
  GET  /health                 {"ok": true}
  GET  /api/v1/status          every site and logger: last record, last live, firmware
  GET  /api/v1/live/<site>     live values, 60-minute history and open alarms of a site
  GET  /api/v1/alarms/<site>   open alarms and the last 200 lines of the alarm log
  GET  /live/  /live/<site>/   live page (refresh every 15 s)

Firmware update from the live page (people in ADMIN_USERS only, see docs/OTA.md):
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
"*" = everyone who can log in, empty = nobody), FW_GITHUB_REPO (owner/name), FW_GITHUB_TOKEN.
"""

import json
import os
import re
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alarms import AlarmEngine  # noqa: E402
from firmware import MAX_IMAGE, Firmware, FirmwareError, GitHub  # noqa: E402
from store import CODE_RE, DEVICE_RE, DataStore, IngestError, iso_now  # noqa: E402

VERSION = "0.2.0"
DATA_DIR = os.environ.get("DATA_DIR", "/data")
MAX_BODY = int(os.environ.get("MAX_BODY", "262144"))
LIVE_POINTS = 240                      # 60 minutes at 15 s
HERE = os.path.dirname(os.path.abspath(__file__))


class Live:
    """Last snapshots per site and device, in memory only (a restart empties it)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}   # site -> device -> deque of (received_epoch, snapshot dict)

    def add(self, site, device, snap):
        with self.lock:
            q = self.data.setdefault(site, {}).setdefault(device, deque(maxlen=LIVE_POINTS))
            q.append((time.time(), snap))

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
        if path.startswith("/api/v1/admin/"):
            return self.admin_post(path)
        body = self.read_body()
        if body is None:
            return self.send_json(413, {"ok": False, "error": "body too large"})
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
        m = re.match(r"^/api/v1/alarms/([a-z0-9-]+)$", path)
        if m and CODE_RE.match(m.group(1)):
            return self.send_json(200, self.alarm_view(m.group(1)))
        if path in ("/live", "/live/") or re.match(r"^/live/[a-z0-9-]+/?$", path):
            with open(os.path.join(HERE, "live.html"), "rb") as f:
                page = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            return self.wfile.write(page)
        if path.startswith("/api/v1/admin/"):
            return self.admin_get(path)
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

    # ------------------------------------------------------------------ pieces
    def public_profile(self, site):
        p = self.store.site_profile(site)
        return {k: p.get(k) for k in ("name", "timezone", "utc_offset_h", "labels", "live") if k in p}

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
    Handler.live = Live()
    Handler.fw = Firmware(store)
    store.on_rollback = Handler.fw.note_rollback
    Handler.github = GitHub()
    Handler.admin_users = os.environ.get("ADMIN_USERS", "")
    srv = ThreadingHTTPServer((bind, port), Handler)
    srv.daemon_threads = True
    return srv


def main():
    bind = os.environ.get("BIND", "0.0.0.0")
    port = int(os.environ.get("PORT", "8800"))
    srv = make_server(DATA_DIR, bind, port)

    def offline_watch():   # A01: a logger that sends nothing
        while True:
            time.sleep(60)
            try:
                Handler.store.alarms.check_offline()
            except Exception as e:   # never let the watcher die
                sys.stderr.write(f"{iso_now()} offline check failed: {e!r}\n")

    threading.Thread(target=offline_watch, daemon=True).start()
    sys.stderr.write(f"{iso_now()} arkan-ingest {VERSION} on {bind}:{port}, data in {DATA_DIR}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
