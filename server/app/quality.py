"""Power quality for the site page (menu group "Power quality"), read from the day files (no database).

    hourly(store, engine, site, device, days)   one row per local hour: voltage of each phase (mean, lowest and
                                                highest 15 s sample), frequency, power factor, kW, kvar, kWh, kVArh,
                                                voltage and current unbalance, minutes inside and outside the voltage
                                                limits, dips and swells; with the limits and the power quality alarm
                                                lines of the period
    minutes(store, site, device, day)           the 1-minute voltage, frequency and power factor of one local day

The limits are read from the alarm register (docs/alarms/alarms.csv, the copy in use on the VPS), so the page
counts exactly what the alarms check:
    A05 undervoltage, A06 overvoltage   a phase's 1-minute mean below 207 V / above 242 V
    A26 dip, A27 swell, A04 phase lost  a 15 s sample below 207 V / above 253 V / below 100 V
    A28 voltage unbalance (2 %), A10 current imbalance (20 %, not below 5 A), A07 frequency (50 +- 0.5 Hz),
    A09 power factor (0.85, only while the load is 1 kW or more; the sign of the power factor is not used).
Unbalance = largest deviation of a phase from the mean of the three, in % of the mean (as alarms A10 and A28).
Energy: steps of the meter's counters EM01_e (kWh) and EM01_eq (kVArh) between records less than an hour apart,
given to the hour of the later record, as in history.py. Each day file is summarised once and kept in memory
until it changes or the limits change.
"""

import csv
import os
import threading
from datetime import datetime, timedelta, timezone

from alarms import _unbalance
from history import MAX_DAYS, MAX_GAP_S, _files, _num, _offset, _parse_ts, _read

PF_LOAD_KW = 1.0          # power factor ignored below this load (as A09)
I_FLOOR_A = 5.0           # current imbalance ignored below this mean current (as A10)
V_FLOOR_V = 100.0         # voltage unbalance ignored below this mean voltage (as A28)
MAX_EVENTS = 500
# alarm id -> (limit name, default when the register has no such line)
LIMITS = {"A05": ("low", 207.0), "A06": ("high", 242.0), "A26": ("dip", 207.0), "A27": ("swell", 253.0),
          "A04": ("lost", 100.0), "A28": ("vu", 2.0), "A10": ("iu", 20.0), "A07": ("f_dev", 0.5), "A09": ("pf", 0.85)}
COUNTS = ("vn", "vok", "vlow", "vhigh", "dips", "swells", "lost", "loaded", "pf_low")
DAY_COLS = ("t", "v1", "v1_min", "v1_max", "v2", "v2_min", "v2_max", "v3", "v3_min", "v3_max",
            "f", "f_min", "f_max", "pf", "p")

_cache = {}
_lock = threading.Lock()


def limits(engine, site):
    """{"low": {"id", "name", "v", "enabled"}, ...} from the alarm register (disabled lines included)."""
    out = {name: {"id": aid, "name": "", "v": dflt, "enabled": False} for aid, (name, dflt) in LIMITS.items()}
    try:
        reg = engine.register(site, include_disabled=True) if engine else []
    except OSError:
        reg = []
    for a in reg:
        if a.get("id") in LIMITS:
            name, _ = LIMITS[a["id"]]
            v = _num(a.get("threshold"))
            out[name] = {"id": a["id"], "name": a.get("name", ""), "v": out[name]["v"] if v is None else v,
                         "enabled": (a.get("enabled") or "").strip().lower() == "yes"}
    return out


def _abs(x):
    return None if x is None else abs(x)


def _acc(h, col, v, lo=None, hi=None):
    if v is None:
        return
    h["sums"][col] = h["sums"].get(col, 0.0) + v
    h["cnt"][col] = h["cnt"].get(col, 0) + 1
    lo = v if lo is None else min(lo, v)
    hi = v if hi is None else max(hi, v)
    h["min"][col] = min(h["min"].get(col, lo), lo)
    h["max"][col] = max(h["max"].get(col, hi), hi)


def _new_hour():
    h = {"n": 0, "kwh": 0.0, "kvarh": 0.0, "sums": {}, "cnt": {}, "min": {}, "max": {}}
    h.update({c: 0 for c in COUNTS})
    return h


def _phase(row, m, base):
    """[(mean, lowest, highest)] of the three phases; lowest/highest fall back to the mean."""
    out = []
    for k in (1, 2, 3):
        v = _num(row.get(f"{m}_{base}{k}"))
        lo, hi = _num(row.get(f"{m}_{base}{k}_min")), _num(row.get(f"{m}_{base}{k}_max"))
        out.append((v, v if lo is None else lo, v if hi is None else hi))
    return out


def _minute(row, m, lim, h):
    """Adds one 1-minute record to an hour."""
    ph = _phase(row, m, "v")
    for k, (v, lo, hi) in enumerate(ph, 1):
        _acc(h, f"v{k}", v, lo, hi)
    means = [v for v, _, _ in ph if v is not None]
    lows = [lo for _, lo, _ in ph if lo is not None]
    highs = [hi for _, _, hi in ph if hi is not None]
    if len(means) == 3:
        h["vn"] += 1
        h["vok"] += lim["low"] <= min(means) and max(means) <= lim["high"]
    if means:
        h["vlow"] += min(means) < lim["low"]
        h["vhigh"] += max(means) > lim["high"]
    if lows:
        h["dips"] += min(lows) < lim["dip"]
        h["lost"] += min(lows) < lim["lost"]
    if highs:
        h["swells"] += max(highs) > lim["swell"]
    _acc(h, "vu", _unbalance([v for v, _, _ in ph], V_FLOOR_V))
    _acc(h, "iu", _unbalance([v for v, _, _ in _phase(row, m, "i")], I_FLOOR_A))
    _acc(h, "f", _num(row.get(f"{m}_f")), _num(row.get(f"{m}_f_min")), _num(row.get(f"{m}_f_max")))
    p, q = _num(row.get(f"{m}_p")), _num(row.get(f"{m}_q"))
    _acc(h, "p", p)
    _acc(h, "q", q)
    pf = _abs(_num(row.get(f"{m}_pf")))
    if pf is not None and p is not None and abs(p) >= PF_LOAD_KW:
        samples = [x for x in (pf, _abs(_num(row.get(f"{m}_pf_min"))), _abs(_num(row.get(f"{m}_pf_max")))) if x is not None]
        _acc(h, "pf", pf, min(samples))
        h["loaded"] += 1
        h["pf_low"] += pf < lim["pf"]


def _summarise(path, meter, off, lim):
    st = os.stat(path)
    key = (path, meter, off, tuple(sorted(lim.items())))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
    hours = {}
    ctr = {c: {"first": None, "last": None} for c in ("e", "eq")}
    for row in _read(path):
        t = _parse_ts(row.get("ts"))
        if t is None:
            continue
        h = hours.setdefault((t + off).strftime("%Y-%m-%d %H:00"), _new_hour())
        h["n"] += 1
        for c, out in (("e", "kwh"), ("eq", "kvarh")):
            e = _num(row.get(f"{meter}_{c}"))
            if e is None:
                continue
            k = ctr[c]
            if k["first"] is None:
                k["first"] = (t, e)
            if k["last"] is not None:
                t0, e0 = k["last"]
                if 0 < (t - t0).total_seconds() <= MAX_GAP_S and e >= e0:
                    h[out] += e - e0
            k["last"] = (t, e)
            h.setdefault("has_" + c, True)
        _minute(row, meter, lim, h)
    summary = {"hours": hours, "ctr": ctr}
    with _lock:
        _cache[key] = (st.st_mtime_ns, st.st_size, summary)
        if len(_cache) > 512:
            _cache.pop(next(iter(_cache)))
    return summary


def _r(x, d):
    return round(x, d) if x is not None else None


def _row(k, parts):
    n = sum(p["n"] for p in parts)
    r = {"t": k, "minutes": n}
    sums, cnt, mn, mx = {}, {}, {}, {}
    for p in parts:
        for c, v in p["sums"].items():
            sums[c] = sums.get(c, 0.0) + v
            cnt[c] = cnt.get(c, 0) + p["cnt"][c]
            mn[c] = min(mn.get(c, p["min"][c]), p["min"][c])
            mx[c] = max(mx.get(c, p["max"][c]), p["max"][c])
    mean = lambda c: sums[c] / cnt[c]
    for c in ("v1", "v2", "v3", "f"):
        if c in cnt:
            d = 3 if c == "f" else 2
            r[c], r[c + "_min"], r[c + "_max"] = _r(mean(c), d), _r(mn[c], d), _r(mx[c], d)
    if "pf" in cnt:
        r["pf"], r["pf_min"] = _r(mean("pf"), 3), _r(mn["pf"], 3)
    for c in ("p", "q"):
        if c in cnt:
            r[c] = _r(mean(c), 2)
    for c in ("vu", "iu"):
        if c in cnt:
            r[c], r[c + "_max"] = _r(mean(c), 2), _r(mx[c], 2)
    if any(p.get("has_e") for p in parts):
        r["kwh"] = _r(sum(p["kwh"] for p in parts), 3)
    if any(p.get("has_eq") for p in parts):
        r["kvarh"] = _r(sum(p["kvarh"] for p in parts), 3)
    for c in COUNTS:
        r[c] = sum(p[c] for p in parts)
    return r


def events(store, engine, site, device, utc_from):
    """Power quality lines of the alarm log since utc_from (register group "power quality"), oldest first."""
    try:
        ids = {a["id"] for a in engine.register(site, include_disabled=True)
               if (a.get("group") or "").strip().lower() == "power quality"} if engine else set()
    except OSError:
        ids = set()
    ids |= set(LIMITS)
    d = os.path.join(store.site_dir(site), "alarms")
    since = utc_from.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for year in range(utc_from.year, datetime.now(timezone.utc).year + 1):
        p = os.path.join(d, f"{year}.csv")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("id") in ids and r.get("device") == device and (r.get("ts_utc") or "") >= since:
                    out.append({k: r.get(k, "") for k in ("ts_utc", "local_time", "id", "name", "severity", "state",
                                                          "value", "unit", "duration_min", "message")})
    out.sort(key=lambda x: x["ts_utc"])
    return out[-MAX_EVENTS:]


def hourly(store, engine, site, device, days=14, meter="EM01"):
    days = max(1, min(int(days), MAX_DAYS))
    off = _offset(store, site)
    lim_full = limits(engine, site)
    lim = {k: v["v"] for k, v in lim_full.items()}
    now = datetime.now(timezone.utc)
    local_start = (now + off).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    utc_from = local_start - off
    out, prev = {}, {"e": None, "eq": None}
    for _, path in _files(store, site, device, utc_from - timedelta(days=1), now):
        s = _summarise(path, meter, off, lim)
        for c, col in (("e", "kwh"), ("eq", "kvarh")):   # the step from the previous file's last record
            first, last = s["ctr"][c]["first"], s["ctr"][c]["last"]
            if prev[c] and first:
                (t0, e0), (t1, e1) = prev[c], first
                if 0 < (t1 - t0).total_seconds() <= MAX_GAP_S and e1 >= e0:
                    k = (t1 + off).strftime("%Y-%m-%d %H:00")
                    out.setdefault(k, []).append(dict(_new_hour(), **{col: e1 - e0, "has_" + c: True}))
            if last:
                prev[c] = last
        for k, h in s["hours"].items():
            out.setdefault(k, []).append(h)
    first_key = local_start.strftime("%Y-%m-%d %H:00")
    rows = [_row(k, out[k]) for k in sorted(out) if k >= first_key]
    prof = store.site_profile(site)
    return {"site": site, "device": device, "meter": meter, "utc_offset_h": off.total_seconds() / 3600,
            "from": first_key, "now": (now + off).strftime("%Y-%m-%d %H:%M"),
            "nominal_v": _num(prof.get("nominal_v")) or 230.0, "nominal_hz": _num(prof.get("nominal_hz")) or 50.0,
            "pf_load_kw": PF_LOAD_KW, "i_floor_a": I_FLOOR_A, "limits": lim_full, "hours": rows,
            "events": events(store, engine, site, device, utc_from)}


def minutes(store, site, device, day, meter="EM01"):
    """{"cols": [...], "rows": [["HH:MM", v1, v1_min, v1_max, ..., f, f_min, f_max, pf, p]]} for one local day.
    pf is the absolute value, and empty below PF_LOAD_KW of load."""
    off = _offset(store, site)
    local0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    utc_from, utc_to = local0 - off, local0 - off + timedelta(days=1)
    rows = []
    for _, path in _files(store, site, device, utc_from, utc_to):
        for row in _read(path):
            t = _parse_ts(row.get("ts"))
            if t is None or not (utc_from <= t < utc_to):
                continue
            vals = {c: _num(row.get(f"{meter}_{c}")) for c in DAY_COLS[1:]}
            if all(vals[f"v{k}"] is None for k in (1, 2, 3)):
                continue
            p = vals["p"]
            pf = _abs(vals["pf"])
            vals["pf"] = pf if pf is not None and p is not None and abs(p) >= PF_LOAD_KW else None
            rows.append([(t + off).strftime("%H:%M")] + [vals[c] for c in DAY_COLS[1:]])
    rows.sort(key=lambda r: r[0])
    return {"site": site, "device": device, "meter": meter, "day": day, "cols": list(DAY_COLS), "rows": rows}
