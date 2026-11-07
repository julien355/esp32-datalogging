"""Alarm and warning engine: evaluates the alarm register on every 1-minute record, in time order.

Register: <DATA_DIR>/alarm-register.csv (copied from docs/alarms/alarms.csv by `manage.py init`,
editable in Excel), lines overridden per site by sites/<site>/alarm-register.csv.

Log (the alarm and warning register log), one file per site and year:
    sites/<site>/alarms/2026.csv
    ts_utc,local_time,device,id,name,severity,state,value,threshold,unit,duration_min,message
state: start | clear | event. Times are those of the records (the moment the condition began),
not the moment the data arrived: an outage's backlog gives the right times.

State per logger (open alarms, pending delays, previous record): sites/<site>/<device>/alarm-state.json.
The log is a function of the records and the register: `manage.py alarms <site> --rebuild` replays it.
"""

import csv
import io
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone

GAP_S = 300                       # a gap longer than this resets a pending (not yet confirmed) alarm
PLANNED_BOOTS = ("sw:daily", "sw:console", "sw:portal", "sw:remote_cfg", "sw:ota", "sw:import", "sw:ota_rollback")
POWER_BOOTS = ("poweron", "brownout")
CRASH_BOOTS = ("panic", "task_wdt", "int_wdt", "wdt")
LOG_HEADER = "ts_utc,local_time,device,id,name,severity,state,value,threshold,unit,duration_min,message"


def num(x):
    if x is None or x == "":
        return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except ValueError:
        return None


def boot_of(row):
    """The boot column is "reason@firmware" on the first record after a boot (logger 0.3.0+)."""
    reason, _, fw = (row.get("boot") or "").partition("@")
    return reason, fw


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def dew_point(t, rh):
    if t is None or rh is None or rh <= 0:
        return None
    a, b = 17.62, 243.12
    g = math.log(rh / 100.0) + a * t / (b + t)
    return b * g / (a - g)


# ---------------------------------------------------------------------- rule functions
# A level rule returns a number (or None = no data, no change). Its kind says how it is compared:
#   below: starts when value < threshold, clears when value > clear_at
#   above: starts when value > threshold, clears when value < clear_at
#   flag:  starts when value is true, clears when false
# An event rule returns a message (or None).

def _meter(a):
    return a["applies_to"].split(",")[0].strip()


def _phases(row, a, name):
    m = _meter(a)
    return [num(row.get(f"{m}_{name}{k}")) for k in (1, 2, 3)]


def _phase_q(row, a, base, suffix):
    """Phase values with a _min/_max suffix, falling back to the mean when the column is absent."""
    m = _meter(a)
    out = []
    for k in (1, 2, 3):
        v = num(row.get(f"{m}_{base}{k}_{suffix}"))
        out.append(v if v is not None else num(row.get(f"{m}_{base}{k}")))
    return [v for v in out if v is not None]


def r_v_min_phase(row, a, ctx):
    v = _phase_q(row, a, "v", "min")
    return min(v) if v else None


def r_v_max_phase(row, a, ctx):
    v = _phase_q(row, a, "v", "max")
    return max(v) if v else None


def r_v_mean_low(row, a, ctx):
    v = [x for x in _phases(row, a, "v") if x is not None]
    return min(v) if v else None


def r_v_mean_high(row, a, ctx):
    v = [x for x in _phases(row, a, "v") if x is not None]
    return max(v) if v else None


def _unbalance(values, floor):
    v = [x for x in values if x is not None]
    if len(v) < 3:
        return None
    avg = sum(v) / 3
    if avg < floor:
        return None
    return max(abs(x - avg) for x in v) / avg * 100


def r_v_unbalance_pct(row, a, ctx):
    return _unbalance(_phases(row, a, "v"), 100)


def r_i_imbalance_pct(row, a, ctx):
    return _unbalance(_phases(row, a, "i"), 5)


def r_f_dev(row, a, ctx):
    m = _meter(a)
    nominal = float(ctx["site"].get("nominal_hz") or 50)
    vals = [num(row.get(f"{m}_f_min")), num(row.get(f"{m}_f_max")), num(row.get(f"{m}_f"))]
    vals = [x for x in vals if x is not None]
    return max(abs(x - nominal) for x in vals) if vals else None


def r_s_pct_contract(row, a, ctx):
    kva = num(ctx["site"].get("contracted_kva"))
    m = _meter(a)
    s = num(row.get(f"{m}_s_max"))
    s = s if s is not None else num(row.get(f"{m}_s"))
    return s / kva * 100 if kva and s is not None else None


def r_pf_low(row, a, ctx):
    m = _meter(a)
    pf, p = num(row.get(f"{m}_pf")), num(row.get(f"{m}_p"))
    if pf is None or p is None or abs(p) < 1:
        return None
    return abs(pf)


def r_i_pct_contract(row, a, ctx):
    """Highest 15 s phase current against the PLN limiter of the contract (82.5 kVA = 3 x 125 A at 220 V)."""
    kva = num(ctx["site"].get("contracted_kva"))
    v_ln = num(ctx["site"].get("contract_v_ln")) or 220.0
    i = _phase_q(row, a, "i", "max")
    if not kva or not i:
        return None
    return max(i) / (kva * 1000 / (3 * v_ln)) * 100


def r_i_max_pct_rated(row, a, ctx):
    rated = num(ctx["site"].get("rated_a"))
    i = _phase_q(row, a, "i", "max")
    return max(i) / rated * 100 if rated and i else None


def r_p_phase_negative(row, a, ctx):
    p = [x for x in _phases(row, a, "p") if x is not None]
    return min(p) if p else None


def r_meter_no_answer(row, a, ctx):
    n = num(row.get(f"{_meter(a)}_n"))
    return None if n is None else n < 1


def r_e_frozen(row, a, ctx):
    m = _meter(a)
    prev = ctx.get("prev") or {}
    e, e0, p = num(row.get(f"{m}_e")), num(prev.get(f"{m}_e")), num(row.get(f"{m}_p"))
    if e is None or e0 is None or p is None:
        return None
    return p > float(a["threshold"] or 1) and abs(e - e0) < 1e-6


def _sensors(a):
    return [s.strip() for s in a["applies_to"].split(",") if s.strip()]


def r_temp_above(row, a, ctx):
    v = [num(row.get(f"{s}_t")) for s in _sensors(a)]
    v = [x for x in v if x is not None]
    return max(v) if v else None


def r_rh_above(row, a, ctx):
    v = [num(row.get(f"{s}_rh")) for s in _sensors(a)]
    v = [x for x in v if x is not None]
    return max(v) if v else None


def r_sensor_missing(row, a, ctx):
    """Sensors are recorded every 5 min: empty = not a sensor row, "err" = no valid reading in the window.
    (Before logger 0.3.0, every row had sensor values and an empty one meant a fault.)"""
    vals = [row.get(f"{s}_t") for s in _sensors(a) if f"{s}_t" in row]
    if not vals:
        return None
    if any(v == "err" for v in vals):
        return True
    if all(v == "" for v in vals):
        return None
    return False


def r_temp_diff(row, a, ctx):
    s = _sensors(a)
    t1, t2 = num(row.get(f"{s[0]}_t")), num(row.get(f"{s[1]}_t"))
    return None if t1 is None or t2 is None else t1 - t2


def r_temp_diff_abs(row, a, ctx):
    d = r_temp_diff(row, a, ctx)
    return None if d is None else abs(d)


def r_dewpoint_margin(row, a, ctx):
    s = _sensors(a)
    room = num(row.get(f"{s[0]}_t"))
    dp = dew_point(num(row.get(f"{s[1]}_t")), num(row.get(f"{s[1]}_rh")))
    return None if room is None or dp is None else room - dp


def r_sd_error(row, a, ctx):
    return None if row.get("sd") in (None, "") else row.get("sd") == "0"


def r_backlog(row, a, ctx):
    # Only while the WiFi is up (rssi present): a backlog during a WiFi outage is normal (A01 covers it).
    if num(row.get("rssi")) is None:
        return None
    return num(row.get("backlog_min"))


def r_wifi_weak(row, a, ctx):
    return num(row.get("rssi"))


# events --------------------------------------------------------------

def e_power_interruption(row, a, ctx):
    boot, _ = boot_of(row)
    if boot not in POWER_BOOTS:
        return None
    prev = ctx.get("prev_ts")
    if prev:
        gap = (parse_ts(row["ts"]) - parse_ts(prev)).total_seconds() / 60 - 1
        if gap >= 1:
            return f"logger restarted ({boot}); no records from {prev} for {gap:.0f} min: outage about {gap:.0f} min"
    return f"logger restarted ({boot})"


def e_logger_crash(row, a, ctx):
    boot, _ = boot_of(row)
    return f"logger restarted by {boot}" if boot in CRASH_BOOTS else None


def e_e_backwards(row, a, ctx):
    m = _meter(a)
    e, e0 = num(row.get(f"{m}_e")), num((ctx.get("prev") or {}).get(f"{m}_e"))
    tol = float(a["threshold"] or 0.01)
    if e is not None and e0 is not None and e < e0 - tol:
        return f"kWh counter {e0} -> {e}"
    return None


def e_frequent_restarts(row, a, ctx):
    boot, _ = boot_of(row)
    if not boot or boot in PLANNED_BOOTS:
        return None
    t = parse_ts(row["ts"]).timestamp()
    boots = [x for x in ctx["state"].setdefault("boots", []) if t - x < 86400] + [t]
    ctx["state"]["boots"] = boots
    limit = int(float(a["threshold"] or 3))
    if len(boots) >= limit:
        ctx["state"]["boots"] = []
        return f"{len(boots)} unplanned restarts within 24 h (last: {boot})"
    return None


def e_firmware_updated(row, a, ctx):
    boot, fw = boot_of(row)
    old = ctx.get("fw_prev")
    if not fw or not old or fw == old or boot == "sw:ota_rollback":
        return None
    how = "by remote update (OTA)" if boot == "sw:ota" else f"flashed by hand (boot {boot})"
    return f"firmware {old} -> {fw}, {how}"


def e_firmware_rollback(row, a, ctx):
    boot, fw = boot_of(row)
    if boot != "sw:ota_rollback":
        return None
    return f"new firmware kept restarting: back to {fw or 'the previous version'} (was {ctx.get('fw_prev') or '?'})"


LEVEL = {
    "v_min_phase": ("below", r_v_min_phase), "v_max_phase": ("above", r_v_max_phase),
    "v_mean_low": ("below", r_v_mean_low), "v_mean_high": ("above", r_v_mean_high),
    "v_unbalance_pct": ("above", r_v_unbalance_pct), "i_imbalance_pct": ("above", r_i_imbalance_pct),
    "f_dev": ("above", r_f_dev), "s_pct_contract": ("above", r_s_pct_contract), "pf_low": ("below", r_pf_low),
    "i_max_pct_rated": ("above", r_i_max_pct_rated), "i_pct_contract": ("above", r_i_pct_contract), "p_phase_negative": ("below", r_p_phase_negative),
    "meter_no_answer": ("flag", r_meter_no_answer), "e_frozen": ("flag", r_e_frozen),
    "temp_above": ("above", r_temp_above), "rh_above": ("above", r_rh_above),
    "sensor_missing": ("flag", r_sensor_missing), "temp_diff": ("above", r_temp_diff),
    "temp_diff_abs": ("above", r_temp_diff_abs), "dewpoint_margin": ("below", r_dewpoint_margin),
    "sd_error": ("flag", r_sd_error), "backlog": ("above", r_backlog), "wifi_weak": ("below", r_wifi_weak),
}
EVENT = {
    "power_interruption": e_power_interruption, "logger_crash": e_logger_crash,
    "e_backwards": e_e_backwards, "frequent_restarts": e_frequent_restarts,
    "firmware_updated": e_firmware_updated, "firmware_rollback": e_firmware_rollback,
}
# Rules not evaluated on records: offline and clock_skew (below), oed_push and grid_lost (not built).


# ---------------------------------------------------------------------- engine

class AlarmEngine:
    def __init__(self, store, default_register=None):
        self.store = store
        self.lock = threading.RLock()
        here = os.path.dirname(os.path.abspath(__file__))
        if not default_register:   # in the image: app/alarm-register.csv; in the repository: docs/alarms/alarms.csv
            for c in (os.path.join(here, "alarm-register.csv"),
                      os.path.join(here, "..", "..", "docs", "alarms", "alarms.csv")):
                if os.path.exists(c):
                    default_register = os.path.abspath(c)
                    break
        self.default_register = default_register or ""
        self._reg_cache = {}
        self.last_rx = {}            # (site, device) -> epoch of the last upload received

    # ---------------------------------------------------------------- register
    def _read_register(self, path):
        try:
            mt = os.path.getmtime(path)
        except FileNotFoundError:
            return []
        c = self._reg_cache.get(path)
        if c and c[0] == mt:
            return c[1]
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.DictReader(f) if (r.get("id") or "").strip()]
        self._reg_cache[path] = (mt, rows)
        return rows

    def register(self, site):
        base = os.path.join(self.store.root, "alarm-register.csv")
        rows = self._read_register(base if os.path.exists(base) else self.default_register)
        over = {r["id"]: r for r in self._read_register(os.path.join(self.store.site_dir(site), "alarm-register.csv"))}
        out = []
        for r in rows:
            r = dict(over.get(r["id"], r))
            if (r.get("enabled") or "").strip().lower() != "yes":
                continue
            out.append(r)
        return out

    # ---------------------------------------------------------------- state and log
    def _state_path(self, site, device):
        return os.path.join(self.store.device_dir(site, device), "alarm-state.json")

    def load_state(self, site, device):
        try:
            with open(self._state_path(site, device), encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {"last_ts": None, "prev": None, "alarms": {}, "boots": []}

    def save_state(self, site, device, state):
        from store import atomic_write
        atomic_write(self._state_path(site, device), json.dumps(state, sort_keys=True))

    def _tz(self, site):
        prof = self.store.site_profile(site)
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(prof.get("timezone") or "Asia/Makassar")
        except Exception:
            return timezone(timedelta(hours=float(prof.get("utc_offset_h", 8))))

    def write_log(self, site, lines):
        """lines: list of dicts (LOG_HEADER keys). Appended to the year files, in the given order."""
        if not lines:
            return
        tz = self._tz(site)
        by_year = {}
        for ln in lines:
            ln["local_time"] = parse_ts(ln["ts_utc"]).astimezone(tz).strftime("%Y-%m-%d %H:%M")
            by_year.setdefault(ln["ts_utc"][:4], []).append(ln)
        d = os.path.join(self.store.site_dir(site), "alarms")
        os.makedirs(d, exist_ok=True)
        keys = LOG_HEADER.split(",")
        for year, items in by_year.items():
            p = os.path.join(d, f"{year}.csv")
            new = not os.path.exists(p)
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            if new:
                buf.write(LOG_HEADER + "\n")
            for ln in items:
                w.writerow([ln.get(k, "") for k in keys])
            with open(p, "a", encoding="utf-8", newline="") as f:
                f.write(buf.getvalue())

    @staticmethod
    def _fmt(v):
        if v is None or v == "":
            return ""
        if isinstance(v, bool):
            return "1" if v else "0"
        return f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)

    def _line(self, ts, device, a, state, value="", message="", duration=""):
        return {"ts_utc": ts, "device": device, "id": a["id"], "name": a["name"], "severity": a["severity"],
                "state": state, "value": self._fmt(value), "threshold": a.get("threshold", ""),
                "unit": a.get("unit", ""), "duration_min": duration, "message": message}

    # ---------------------------------------------------------------- evaluation
    def evaluate(self, site, device, rows, state):
        """rows: list of dicts (one per record, oldest first, newer than state['last_ts']).
        Updates state, returns the log lines."""
        reg = self.register(site)
        prof = self.store.site_profile(site)
        out = []
        for row in rows:
            ts = row["ts"]
            t = parse_ts(ts).timestamp()
            prev_ts = state.get("last_ts")
            gap = prev_ts is not None and t - parse_ts(prev_ts).timestamp() > GAP_S
            ctx = {"site": prof, "prev": state.get("prev"), "prev_ts": prev_ts, "state": state,
                   "fw_prev": state.get("fw")}
            for a in reg:
                rule = (a.get("rule") or "").strip()
                if rule in EVENT:
                    try:
                        msg = EVENT[rule](row, a, ctx)
                    except (KeyError, ValueError, IndexError, TypeError):
                        msg = None
                    if msg:
                        out.append(self._line(ts, device, a, "event", message=msg))
                    continue
                if rule not in LEVEL:
                    continue
                kind, fn = LEVEL[rule]
                try:
                    v = fn(row, a, ctx)
                except (KeyError, ValueError, IndexError, TypeError, ZeroDivisionError):
                    v = None
                st = state["alarms"].setdefault(a["id"], {"active": False, "pending": None})
                if gap and not st["active"]:
                    st["pending"] = None
                if v is None:
                    continue
                thr = num(a.get("threshold"))
                clr = num(a.get("clear_at"))
                clr = thr if clr is None else clr
                if kind == "flag":
                    on, off = bool(v), not bool(v)
                elif kind == "above":
                    on, off = v > thr, v < clr
                else:
                    on, off = v < thr, v > clr
                if not st["active"]:
                    if not on:
                        st["pending"] = None
                        continue
                    if st["pending"] is None:
                        st["pending"] = ts
                        st["worst"] = v
                    else:
                        st["worst"] = self._worse(kind, st.get("worst"), v)
                    delay = num(a.get("delay_min")) or 0
                    if t - parse_ts(st["pending"]).timestamp() >= max(0, delay - 1) * 60:
                        st.update(active=True, since=st["pending"], pending=None)
                        out.append(self._line(st["since"], device, a, "start", st["worst"],
                                              f"{a['condition']}"))
                else:
                    st["worst"] = self._worse(kind, st.get("worst"), v)
                    if off:
                        dur = round((t - parse_ts(st["since"]).timestamp()) / 60)
                        out.append(self._line(ts, device, a, "clear", st["worst"],
                                              f"cleared after {dur} min; worst value {self._fmt(st['worst'])}",
                                              str(dur)))
                        st.update(active=False, since=None, worst=None)
            fw = boot_of(row)[1]
            if fw:
                state["fw"] = fw
            state["last_ts"] = ts
            state["prev"] = row
            state["prev_ts"] = ts
        return out

    @staticmethod
    def _worse(kind, old, new):
        if old is None:
            return new
        if kind == "below":
            return min(old, new)
        if kind == "above":
            return max(old, new)
        return bool(old) or bool(new)   # flag: it was on

    def process(self, site, device, header, lines):
        """Called after each upload with the rows just stored: evaluates those newer than the state."""
        with self.lock:
            self.last_rx[(site, device)] = time.time()
            state = self.load_state(site, device)
            cols = header.split(",")
            rows = []
            for ln in lines:
                row = dict(zip(cols, ln.split(",")))
                if state.get("last_ts") and row["ts"] <= state["last_ts"]:
                    continue    # older than what was evaluated: backfill (manage.py alarms --rebuild)
                rows.append(row)
            rows.sort(key=lambda r: r["ts"])
            log = self.evaluate(site, device, rows, state) if rows else []
            log += self._clear_offline(site, device, state)
            self.save_state(site, device, state)
            self.write_log(site, log)
            return log

    # ---------------------------------------------------------------- reception and clock
    def _alarm(self, site, rule):
        for a in self.register(site):
            if (a.get("rule") or "").strip() == rule:
                return a
        return None

    def _clear_offline(self, site, device, state):
        a = self._alarm(site, "offline")
        st = state["alarms"].get(a["id"]) if a else None
        if not st or not st.get("active"):
            return []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        dur = round((time.time() - parse_ts(st["since"]).timestamp()) / 60)
        st.update(active=False, since=None)
        return [self._line(now, device, a, "clear", message=f"records received again after {dur} min", duration=str(dur))]

    def check_offline(self):
        """Every minute: a logger that sent nothing for `threshold` minutes is offline."""
        with self.lock:
            for device, info in self.store.load_devices().get("devices", {}).items():
                site = info.get("site")
                if info.get("disabled") or not site:
                    continue
                a = self._alarm(site, "offline")
                if not a:
                    continue
                last = self.last_rx.get((site, device))
                if last is None:
                    lr = self.store.last_record(site, device)
                    if not lr:
                        continue          # never seen: not offline, just not installed
                    last = parse_ts(lr).timestamp() + 60
                    self.last_rx[(site, device)] = last
                if time.time() - last < float(a["threshold"] or 15) * 60:
                    continue
                state = self.load_state(site, device)
                st = state["alarms"].setdefault(a["id"], {"active": False})
                if st.get("active"):
                    continue
                since = datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                st.update(active=True, since=since)
                self.save_state(site, device, state)
                self.write_log(site, [self._line(since, device, a, "start",
                                                 message=f"nothing received since {since}")])

    def check_clock(self, site, device, snapshot_ts):
        """On each live snapshot: compares the logger's clock with the server's."""
        a = self._alarm(site, "clock_skew")
        if not a or not snapshot_ts:
            return
        try:
            skew = abs(time.time() - parse_ts(snapshot_ts).timestamp()) / 60
        except ValueError:
            return
        with self.lock:
            state = self.load_state(site, device)
            st = state["alarms"].setdefault(a["id"], {"active": False})
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            line = None
            if not st.get("active") and skew > float(a["threshold"] or 2):
                st.update(active=True, since=now, worst=skew)
                line = self._line(now, device, a, "start", skew, f"logger clock {skew:.1f} min off")
            elif st.get("active") and skew < float(a.get("clear_at") or 1):
                st.update(active=False, since=None)
                line = self._line(now, device, a, "clear", skew, "logger clock corrected")
            else:
                return
            self.save_state(site, device, state)
            self.write_log(site, [line])

    # ---------------------------------------------------------------- reading
    def _devices(self, site):
        """Registered loggers of the site, plus any folder that has alarm state (a removed logger's last alarms)."""
        devs = set(self.store.site_devices(site))
        d = self.store.site_dir(site)
        if os.path.isdir(d):
            devs |= {x for x in os.listdir(d) if os.path.exists(os.path.join(d, x, "alarm-state.json"))
                     or os.path.isdir(os.path.join(d, x, "raw"))}
        return sorted(devs)

    def open_alarms(self, site):
        reg = {a["id"]: a for a in self.register(site)}
        out = []
        for device in self._devices(site):
            for aid, st in self.load_state(site, device).get("alarms", {}).items():
                if st.get("active") and aid in reg:
                    a = reg[aid]
                    out.append({"device": device, "id": aid, "name": a["name"], "severity": a["severity"],
                                "since": st.get("since"), "worst": self._fmt(st.get("worst")), "unit": a.get("unit", "")})
        order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(out, key=lambda x: (order.get(x["severity"], 3), x["since"] or ""))

    def rebuild(self, site, read_rows):
        """Replays every record of the site. read_rows(device) yields row dicts oldest first.
        Lines that do not come from the records (A01 offline: reception; A18 clock: live snapshots) cannot be
        replayed: they are kept from the old log, with their open state. Stop the service while it runs
        (docker compose stop ingest), so no upload is evaluated at the same time."""
        with self.lock:
            keep_ids = {a["id"] for a in self.register(site)
                        if (a.get("rule") or "").strip() in ("offline", "clock_skew")}
            d = os.path.join(self.store.site_dir(site), "alarms")
            kept = []
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if not fn.endswith(".csv"):
                        continue
                    with open(os.path.join(d, fn), encoding="utf-8", newline="") as f:
                        kept += [r for r in csv.DictReader(f) if r.get("id") in keep_ids]
                    os.unlink(os.path.join(d, fn))
            lines = []
            for device in self._devices(site):
                old = self.load_state(site, device).get("alarms", {})
                state = {"last_ts": None, "prev": None, "alarms": {}, "boots": []}
                lines += self.evaluate(site, device, list(read_rows(device)), state)
                for aid in keep_ids:            # open offline/clock alarms stay open
                    if aid in old:
                        state["alarms"][aid] = old[aid]
                self.save_state(site, device, state)
            lines += kept
            lines.sort(key=lambda x: x["ts_utc"])
            self.write_log(site, lines)
            return lines
