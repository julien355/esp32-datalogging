"""The data folder: plain CSV and JSON files, one subfolder per site.

    <DATA_DIR>/
      devices.json                         device -> site, token hash, firmware (no token in clear)
      firmware/manifest.json, *.bin        OTA files (tools/manage.py publish-fw)
      sites/<site>/site.json               site profile: name, timezone, devices, notes
      sites/<site>/<device>/raw/YYYY/MM/YYYY-MM-DD.csv   1-minute records of that UTC day
      sites/<site>/<device>/raw/YYYY/MM/YYYY-MM-DD_2.csv  same day, if the columns changed
      sites/<site>/<device>/events.jsonl   boots, firmware changes, column changes
      sites/<site>/daily.csv               one row per local day (tools/manage.py daily)

The day files have exactly the columns of the logger's SD card files, so an SD card copy can
be merged in (tools/manage.py backfill). Rows are unique per timestamp: a row already stored
is dropped, so the logger can resend safely.
"""

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")          # site code: adab
DEVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")  # device code: LOG-0001
TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):00Z$")
FIELD_RE = re.compile(r"^[A-Za-z0-9_.:+-]{0,32}$")
MAX_COLUMNS = 300
FUTURE_SLACK_S = 600
OLDEST_YEAR = 2025


def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def atomic_write(path, text):
    """Write through a temporary file then swap it in: a reader never sees half a file."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class IngestError(ValueError):
    pass


class DataStore:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.lock = threading.RLock()
        self._ts_cache = OrderedDict()   # (site, device, day) -> {part: (header, set of ts)}
        self._devices = None
        self._devices_mtime = None
        self.alarms = None   # AlarmEngine, set by the server (evaluates each upload)

    # ------------------------------------------------------------------ paths
    def site_dir(self, site):
        return os.path.join(self.root, "sites", site)

    def device_dir(self, site, device):
        return os.path.join(self.site_dir(site), device)

    def day_path(self, site, device, day, part=1):
        y, m = day[:4], day[5:7]
        name = f"{day}.csv" if part <= 1 else f"{day}_{part}.csv"
        return os.path.join(self.device_dir(site, device), "raw", y, m, name)

    # ------------------------------------------------------------------ devices
    def devices_path(self):
        return os.path.join(self.root, "devices.json")

    def load_devices(self):
        """devices.json, re-read when the file changes (tools edit it while the service runs)."""
        p = self.devices_path()
        try:
            mt = os.path.getmtime(p)
        except FileNotFoundError:
            return {"devices": {}}
        if self._devices is None or mt != self._devices_mtime:
            with open(p, encoding="utf-8") as f:
                self._devices = json.load(f)
            self._devices_mtime = mt
        return self._devices

    def save_devices(self, data):
        atomic_write(self.devices_path(), json.dumps(data, indent=2, sort_keys=True) + "\n")
        self._devices = None

    def authenticate(self, token):
        """Returns (device, site) for a valid token, else None."""
        if not token:
            return None
        h = token_hash(token)
        with self.lock:
            for dev, info in self.load_devices().get("devices", {}).items():
                if info.get("token_sha256") == h and not info.get("disabled"):
                    return dev, info["site"]
        return None

    def note_firmware(self, site, device, fw):
        if not fw or not re.match(r"^[0-9A-Za-z._-]{1,20}$", fw):
            return
        with self.lock:
            data = self.load_devices()
            info = data.get("devices", {}).get(device)
            if info is None or info.get("fw") == fw:
                return
            old = info.get("fw")
            info["fw"] = fw
            self.save_devices(data)
        self.event(site, device, "firmware", {"from": old, "to": fw})

    # ------------------------------------------------------------------ events
    def event(self, site, device, kind, detail=None):
        line = {"ts": iso_now(), "kind": kind}
        if detail:
            line.update(detail)
        p = os.path.join(self.device_dir(site, device), "events.jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with self.lock, open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")

    # ------------------------------------------------------------------ day files
    def _day_index(self, site, device, day):
        """{part: [header, set(ts)]} for one day, cached for the recent days."""
        key = (site, device, day)
        idx = self._ts_cache.get(key)
        if idx is not None:
            self._ts_cache.move_to_end(key)
            return idx
        idx = {}
        part = 1
        while True:
            p = self.day_path(site, device, day, part)
            if not os.path.exists(p):
                break
            with open(p, encoding="utf-8") as f:
                header = f.readline().rstrip("\r\n")
                tss = set()
                for line in f:
                    ts = line.split(",", 1)[0].strip()
                    if ts:
                        tss.add(ts)
            idx[part] = [header, tss]
            part += 1
        self._ts_cache[key] = idx
        while len(self._ts_cache) > 64:
            self._ts_cache.popitem(last=False)
        return idx

    @staticmethod
    def parse_csv(text):
        """Checks the upload. Returns (header, columns, good rows, bad row count)."""
        lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
        if not lines:
            raise IngestError("empty body")
        header = lines[0].strip()
        cols = header.split(",")
        if cols[0] != "ts":
            raise IngestError("first column must be ts")
        if len(cols) > MAX_COLUMNS or len(set(cols)) != len(cols):
            raise IngestError("too many or repeated columns")
        for c in cols:
            if not NAME_RE.match(c):
                raise IngestError(f"bad column name {c[:40]!r}")
        now = time.time()
        good, bad = [], 0
        for ln in lines[1:]:
            fields = ln.strip().split(",")
            m = TS_RE.match(fields[0])
            if len(fields) != len(cols) or not m or not all(FIELD_RE.match(x) for x in fields):
                bad += 1
                continue
            try:
                t = datetime(*map(int, m.groups()), tzinfo=timezone.utc).timestamp()
            except ValueError:
                bad += 1
                continue
            if t > now + FUTURE_SLACK_S or int(m.group(1)) < OLDEST_YEAR:
                bad += 1
                continue
            good.append((fields[0], ",".join(fields)))
        return header, cols, good, bad

    def store_rows(self, site, device, header, rows):
        """rows: [(ts, line)]. Appends new rows to the right day file. Returns (stored, dup, new lines)."""
        new_lines = []
        by_day = {}
        for ts, line in rows:
            by_day.setdefault(ts[:10], []).append((ts, line))
        stored = dup = 0
        with self.lock:
            for day, items in sorted(by_day.items()):
                idx = self._day_index(site, device, day)
                seen = set()
                for part in idx.values():
                    seen |= part[1]
                fresh = []
                for ts, line in sorted(items):
                    if ts in seen:
                        dup += 1
                        continue
                    seen.add(ts)
                    fresh.append((ts, line))
                if not fresh:
                    continue
                part = next((p for p, v in idx.items() if v[0] == header), None)
                if part is None:
                    part = len(idx) + 1
                    idx[part] = [header, set()]
                    if part > 1:
                        self.event(site, device, "columns_changed", {"day": day, "part": part})
                path = self.day_path(site, device, day, part)
                tss = idx[part][1]
                newest = max(tss) if tss else ""
                if fresh[0][0] > newest:   # the usual case: append
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    new_file = not os.path.exists(path)
                    with open(path, "a", encoding="utf-8", newline="") as f:
                        if new_file:
                            f.write(header + "\n")
                        f.write("".join(line + "\n" for _, line in fresh))
                        f.flush()
                        os.fsync(f.fileno())
                else:                      # older rows (backfill): rewrite the file in time order
                    existing = []
                    if os.path.exists(path):
                        with open(path, encoding="utf-8") as f:
                            f.readline()
                            existing = [ln.rstrip("\r\n") for ln in f if ln.strip()]
                    merged = sorted(existing + [line for _, line in fresh], key=lambda x: x.split(",", 1)[0])
                    atomic_write(path, header + "\n" + "".join(x + "\n" for x in merged))
                tss.update(ts for ts, _ in fresh)
                stored += len(fresh)
                new_lines += [line for _, line in fresh]
                boot_col = header.split(",").index("boot") if "boot" in header.split(",") else None
                if boot_col is not None:
                    for ts, line in fresh:
                        reason = line.split(",")[boot_col]
                        if reason:
                            self.event(site, device, "boot", {"record": ts, "reason": reason})
        return stored, dup, new_lines

    def ingest(self, site, device, text):
        header, cols, good, bad = self.parse_csv(text)
        stored, dup, new_lines = self.store_rows(site, device, header, good)
        last = max((ts for ts, _ in good), default=None)
        res = {"ok": True, "stored": stored, "duplicates": dup, "rejected_rows": bad, "last_ts": last}
        if self.alarms is not None:
            res["alarms"] = len(self.alarms.process(site, device, header, new_lines))
        return res

    # ------------------------------------------------------------------ remote settings
    def config_path(self, site, device):
        return os.path.join(self.device_dir(site, device), "config.json")

    def get_config(self, site, device):
        """Settings the platform wants on the logger: {"version": n, "settings": {key: value}}."""
        try:
            with open(self.config_path(site, device), encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return None

    def set_config(self, site, device, changes):
        """changes: {key: value}; value "@default" puts the logger's default back. Returns the new version."""
        with self.lock:
            cur = self.get_config(site, device) or {"version": 0, "settings": {}}
            cur["settings"].update({k: str(v) for k, v in changes.items()})
            cur["version"] = int(cur.get("version", 0)) + 1
            cur["updated"] = iso_now()
            atomic_write(self.config_path(site, device), json.dumps(cur, indent=2, sort_keys=True) + "\n")
        self.event(site, device, "config_set", {"version": cur["version"], "keys": sorted(changes)})
        return cur["version"]

    def save_report(self, site, device, report):
        report["received"] = iso_now()
        p = os.path.join(self.device_dir(site, device), "settings-reported.json")
        old = None
        try:
            with open(p, encoding="utf-8") as f:
                old = json.load(f).get("cfg_version")
        except (FileNotFoundError, ValueError):
            pass
        atomic_write(p, json.dumps(report, indent=2, sort_keys=True) + "\n")
        if old != report.get("cfg_version"):
            self.event(site, device, "config_applied", {"version": report.get("cfg_version")})

    # ------------------------------------------------------------------ reading
    def sites(self):
        d = os.path.join(self.root, "sites")
        if not os.path.isdir(d):
            return []
        return sorted(x for x in os.listdir(d) if CODE_RE.match(x) and os.path.isdir(os.path.join(d, x)))

    def site_profile(self, site):
        p = os.path.join(self.site_dir(site), "site.json")
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def site_devices(self, site):
        return sorted(dev for dev, info in self.load_devices().get("devices", {}).items() if info.get("site") == site)

    def day_files(self, site, device):
        """Every day file of a device, oldest first: [(day, part, path)]."""
        base = os.path.join(self.device_dir(site, device), "raw")
        out = []
        for dirpath, _, files in os.walk(base):
            for fn in files:
                m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:_(\d+))?\.csv$", fn)
                if m:
                    out.append((m.group(1), int(m.group(2) or 1), os.path.join(dirpath, fn)))
        return sorted(out)

    def last_record(self, site, device):
        files = self.day_files(site, device)
        for day, part, path in reversed(files):
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", "replace").strip().split("\n")
            if len(tail) >= 1 and TS_RE.match(tail[-1].split(",", 1)[0]):
                return tail[-1].split(",", 1)[0]
        return None
