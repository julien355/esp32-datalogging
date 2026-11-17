"""Power quality for the site page (menu group "Power quality"), read from the day files (no database).

    hourly(store, engine, site, device, days)   one row per local hour: voltage of each phase (mean, lowest and
                                                highest 15 s sample), frequency, power factor, kW, kvar, kWh, kVArh,
                                                voltage and current unbalance, minutes inside and outside the voltage
                                                limits, dips and swells; with the limits and the power quality alarm
                                                lines of the period
    minutes(store, site, device, day)           the 1-minute voltage, frequency and power factor of one local day
    current_hourly(store, engine, site, device, days)
                                                page Current & balance: one row per local hour with each phase's current
                                                (mean, lowest and highest 15 s sample, highest 15-minute mean), power,
                                                kWh and power factor, the current imbalance, the minutes near the PLN
                                                phase limit and with a phase without current, and two sums that check
                                                the meter's registers; with the limits and the current alarm lines
    current_minutes(store, site, device, day)   the 1-minute currents, phase powers and imbalance of one local day

The limits are read from the alarm register (docs/alarms/alarms.csv, the copy in use on the VPS), so the page
counts exactly what the alarms check:
    A05 undervoltage, A06 overvoltage   a phase's 1-minute mean below 207 V / above 242 V
    A26 dip, A27 swell, A04 phase lost  a 15 s sample below 207 V / above 253 V / below 100 V
    A28 voltage unbalance (2 %), A10 current imbalance (20 %, not below 5 A of mean current), A41 the same counted
    apart, only with 25 A or more of mean current (site.json i_imbalance_loaded_a), A07 frequency (50 +- 0.5 Hz), A09 power factor (0.85, only while the load is 1 kW or more;
    the sign of the power factor is not used), A37 a 15 s phase current above 90 % of the PLN phase limit
    (contracted_kva / 3 / contract_v_ln), A29 the same against rated_a, A30 a phase's power below -0.5 kW,
    A40 a phase below 1 A while the two others carry 10 A or more.
Unbalance = largest deviation of a phase from the mean of the three, in % of the mean (as alarms A10 and A28).
Current page: the energy of a phase is its 1-minute power summed (the meter has no counter per phase); the power
factor of a phase is P / (V x I) of the minutes with 0.3 kW or more on it; the 15-minute mean is the mean of 15
one-minute means in a row (restarted by a gap), carried over from one day file to the next.
Energy: steps of the meter's counters EM01_e (kWh) and EM01_eq (kVArh) between records less than an hour apart,
given to the hour of the later record, as in history.py. Each day file is summarised once and kept in memory
until it changes or the limits change.
"""

import csv
import os
import threading
from datetime import datetime, timedelta, timezone

from alarms import I_IMBALANCE_FLOOR_A, I_LOADED_A, _unbalance, imbalance_loaded
from history import MAX_GAP_S, _files, _num, _offset, _parse_ts, _read, first_day, period

PF_LOAD_KW = 1.0          # power factor ignored below this load (as A09)
I_FLOOR_A = I_IMBALANCE_FLOOR_A   # current imbalance ignored below this mean current (as A10)
PH_LOAD_KW = 0.3          # power factor of a phase ignored below this power on it
V_FLOOR_V = 100.0         # voltage unbalance ignored below this mean voltage (as A28)
MAX_EVENTS = 500
# alarm id -> (limit name, default when the register has no such line)
LIMITS = {"A05": ("low", 207.0), "A06": ("high", 242.0), "A26": ("dip", 207.0), "A27": ("swell", 253.0),
          "A04": ("lost", 100.0), "A28": ("vu", 2.0), "A10": ("iu", 20.0), "A07": ("f_dev", 0.5), "A09": ("pf", 0.85),
          "A37": ("pln", 90.0), "A29": ("rated", 90.0), "A30": ("pneg", -0.5), "A40": ("izero", 1.0), "A41": ("iul", 20.0)}
COUNTS = ("vn", "vok", "vlow", "vhigh", "dips", "swells", "lost", "loaded", "pf_low")
CCOUNTS = ("in3", "ihi1", "ihi2", "ihi3", "iu_n", "iu_hi", "iu_n_ld", "iu_hi_ld", "izero")   # counts of the current page
CURRENT_RULES = ("i_imbalance_pct", "i_imbalance_loaded", "i_pct_contract", "i_max_pct_rated", "p_phase_negative", "i_phase_zero")
CDAY_COLS = ("t", "i1", "i1_min", "i1_max", "i2", "i2_min", "i2_max", "i3", "i3_min", "i3_max", "p1", "p2", "p3", "iu")
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
                         "enabled": (a.get("enabled") or "").strip().lower() == "yes", "delay": _num(a.get("delay_min"))}
    return out


def pln_a(prof):
    """The PLN limiter of one phase in A: contracted_kva x 1000 / 3 / contract_v_ln (125 A for 82.5 kVA at 220 V)."""
    kva, v = _num(prof.get("contracted_kva")), _num(prof.get("contract_v_ln")) or 220.0
    return kva * 1000 / 3 / v if kva else None


def _lim(lim_full, prof):
    """The values the summaries count against (part of their cache key)."""
    lim = {k: v["v"] for k, v in lim_full.items()}
    pln = pln_a(prof)
    lim.update(i_floor=I_FLOOR_A, i_ld=imbalance_loaded(prof), near_a=pln * lim["pln"] / 100 if pln else None, loaded=I_LOADED_A)
    return lim


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
    h = {"n": 0, "kwh": 0.0, "kvarh": 0.0, "sums": {}, "cnt": {}, "min": {}, "max": {}, "d15": [None, None, None]}
    h.update({c: 0 for c in COUNTS + CCOUNTS})
    return h


def _phase(row, m, base):
    """[(mean, lowest, highest)] of the three phases; lowest/highest fall back to the mean."""
    out = []
    for k in (1, 2, 3):
        v = _num(row.get(f"{m}_{base}{k}"))
        lo, hi = _num(row.get(f"{m}_{base}{k}_min")), _num(row.get(f"{m}_{base}{k}_max"))
        out.append((v, v if lo is None else lo, v if hi is None else hi))
    return out


def _minute(row, m, lim, h, hhmm=""):
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
    _current(row, m, lim, h, [v for v, _, _ in ph], hhmm)
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


def _current(row, m, lim, h, volts, hhmm):
    """The current page's part of a 1-minute record: each phase's current and power, the imbalance (as A10 and A41),
    the minutes near the PLN limit (A37's threshold) and with a phase without current (as A40), the two sums."""
    ip = _phase(row, m, "i")
    cur = [v for v, _, _ in ip]
    for k, (v, lo, hi) in enumerate(ip, 1):
        _acc(h, f"i{k}", v, lo, hi)
        if hi is not None and lim["near_a"] and hi > lim["near_a"]:
            h[f"ihi{k}"] += 1
    pk = [_num(row.get(f"{m}_p{k}")) for k in (1, 2, 3)]
    for k in range(3):
        _acc(h, f"p{k + 1}", pk[k])
        if pk[k] is not None and pk[k] >= PH_LOAD_KW and (cur[k] or 0) >= 1 and volts[k]:
            _acc(h, f"pf{k + 1}", pk[k] * 1000 / (volts[k] * cur[k]))
    iu = _unbalance(cur, lim["i_floor"])
    _acc(h, "iu", iu)
    if iu is not None:
        h["iu_n"] += 1
        h["iu_hi"] += iu > lim["iu"]
        if sum(cur) / 3 >= lim["i_ld"]:   # A41: the same imbalance, under load
            h["iu_n_ld"] += 1
            h["iu_hi_ld"] += iu > lim["iul"]
    if None in cur:
        return
    h["in3"] += 1
    k = min(range(3), key=lambda n: cur[n])
    if cur[k] < lim["izero"] and min(cur[n] for n in range(3) if n != k) >= lim["loaded"]:
        h["izero"] += 1
        h.setdefault("izero_ph", f"L{k + 1}")
        h.setdefault("izero_at", hhmm)
    p, s = _num(row.get(f"{m}_p")), _num(row.get(f"{m}_s"))
    if p is not None and p >= PF_LOAD_KW:
        if None not in pk:
            _acc(h, "psum", sum(pk) / p * 100)
        if s and None not in volts:
            _acc(h, "sratio", sum(volts[n] * cur[n] for n in range(3)) / 1000 / s * 100)


def _d15(ring, t, cur):
    """Adds a minute's three currents to the last 15 minutes in a row; their mean once there are 15."""
    if None in cur:
        ring.clear()
        return None
    if ring and not 55 <= (t - ring[-1][0]).total_seconds() <= 65:
        ring.clear()
    ring.append((t, cur))
    if len(ring) > 15:
        ring.pop(0)
    return [sum(r[1][k] for r in ring) / 15 for k in range(3)] if len(ring) == 15 else None


def _d15_cross(tail, head):
    """The 15-minute means that start in one day file (its last minutes) and end in the next (its first ones)."""
    out, ring = [], []
    for n, (t, cur) in enumerate(tail + head):
        d = _d15(ring, t, cur)
        if d and n >= len(tail) and n - 14 < len(tail):
            out.append((t, d))
    return out


def _summarise(path, meter, off, lim):
    st = os.stat(path)
    key = (path, meter, off, tuple(sorted(lim.items())))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
    hours, ring, seq = {}, [], []
    ctr = {c: {"first": None, "last": None} for c in ("e", "eq")}
    for row in _read(path):
        t = _parse_ts(row.get("ts"))
        if t is None:
            continue
        h = hours.setdefault((t + off).strftime("%Y-%m-%d %H:00"), _new_hour())
        cur = [_num(row.get(f"{meter}_i{k}")) for k in (1, 2, 3)]
        d = _d15(ring, t, cur)
        if d:
            h["d15"] = [x if y is None else max(x, y) for x, y in zip(d, h["d15"])]
        if None not in cur:
            seq.append((t, cur))
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
        _minute(row, meter, lim, h, (t + off).strftime("%H:%M"))
    summary = {"hours": hours, "ctr": ctr, "head": seq[:14], "tail": seq[-14:]}
    with _lock:
        _cache[key] = (st.st_mtime_ns, st.st_size, summary)
        if len(_cache) > 512:
            _cache.pop(next(iter(_cache)))
    return summary


def _r(x, d):
    return round(x, d) if x is not None else None


def _merge(parts):
    sums, cnt, mn, mx = {}, {}, {}, {}
    for p in parts:
        for c, v in p.get("sums", {}).items():
            sums[c] = sums.get(c, 0.0) + v
            cnt[c] = cnt.get(c, 0) + p["cnt"][c]
            mn[c] = min(mn.get(c, p["min"][c]), p["min"][c])
            mx[c] = max(mx.get(c, p["max"][c]), p["max"][c])
    return sums, cnt, mn, mx


def _row(k, parts):
    n = sum(p["n"] for p in parts)
    r = {"t": k, "minutes": n}
    sums, cnt, mn, mx = _merge(parts)
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


def _crow(k, parts):
    """One hour of the current page."""
    sums, cnt, mn, mx = _merge(parts)
    mean = lambda c: sums[c] / cnt[c]
    tot = lambda c: sum(p.get(c, 0) for p in parts)
    r = {"t": k, "minutes": tot("n"), "n": tot("in3")}
    for k in (1, 2, 3):
        c = f"i{k}"
        if c in cnt:
            r[c], r[c + "_min"], r[c + "_max"] = _r(mean(c), 2), _r(mn[c], 2), _r(mx[c], 2)
        d = [p["d15"][k - 1] for p in parts if p.get("d15") and p["d15"][k - 1] is not None]
        if d:
            r[c + "_d15"] = _r(max(d), 2)
        c = f"p{k}"
        if c in cnt:
            r[c], r[f"e{k}"], r[c + "_min"] = _r(mean(c), 3), _r(sums[c] / 60, 3), _r(mn[c], 3)
        if f"pf{k}" in cnt:
            r[f"pf{k}"] = _r(mean(f"pf{k}"), 3)
        r[f"i{k}_hi"] = tot(f"ihi{k}")
    if "iu" in cnt:
        r["iu"], r["iu_max"] = _r(mean("iu"), 2), _r(mx["iu"], 2)
    r["iu_n"], r["iu_hi"], r["iu_n_ld"], r["iu_hi_ld"], r["i_zero"] = (tot("iu_n"), tot("iu_hi"), tot("iu_n_ld"), tot("iu_hi_ld"),
                                                                      tot("izero"))
    if r["i_zero"]:
        first = next(p for p in parts if p.get("izero"))
        r["i_zero_ph"], r["i_zero_at"] = first["izero_ph"], first["izero_at"]
    for c in ("psum", "sratio"):
        if c in cnt:
            r[c] = _r(mean(c), 1)
    return r


def events(store, engine, site, device, utc_from, utc_to=None, rules=None):
    """Lines of the alarm log from utc_from to utc_to, oldest first: power quality (register group "power quality"),
    or the alarms of the given rules (the current page)."""
    try:
        reg = engine.register(site, include_disabled=True) if engine else []
    except OSError:
        reg = []
    if rules:
        ids = {a["id"] for a in reg if (a.get("rule") or "").strip() in rules} or {"A10", "A29", "A30", "A37", "A40"}
    else:
        ids = {a["id"] for a in reg if (a.get("group") or "").strip().lower() == "power quality"} | set(LIMITS) - {"A29", "A30", "A37", "A40"}
    d = os.path.join(store.site_dir(site), "alarms")
    since = utc_from.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (utc_to or datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for year in range(utc_from.year, (utc_to or datetime.now(timezone.utc)).year + 1):
        p = os.path.join(d, f"{year}.csv")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("id") in ids and r.get("device") == device and since <= (r.get("ts_utc") or "") < until:
                    out.append({k: r.get(k, "") for k in ("ts_utc", "local_time", "id", "name", "severity", "state",
                                                          "value", "unit", "duration_min", "message")})
    out.sort(key=lambda x: x["ts_utc"])
    return out[-MAX_EVENTS:]


def hourly(store, engine, site, device, days=14, meter="EM01", start=None, end=None):
    off = _offset(store, site)
    prof = store.site_profile(site)
    lim_full = limits(engine, site)
    lim = _lim(lim_full, prof)
    now = datetime.now(timezone.utc)
    local_start, local_end = period(off, days, start, end, now)
    utc_from, utc_to = local_start - off, min(local_end - off, now)
    out, prev = {}, {"e": None, "eq": None}
    for _, path in _files(store, site, device, utc_from - timedelta(days=1), utc_to):
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
    first_key, end_key = local_start.strftime("%Y-%m-%d %H:00"), local_end.strftime("%Y-%m-%d %H:00")
    rows = [_row(k, out[k]) for k in sorted(out) if first_key <= k < end_key]
    return {"site": site, "device": device, "meter": meter, "utc_offset_h": off.total_seconds() / 3600,
            "from": first_key, "to": (local_end - timedelta(days=1)).strftime("%Y-%m-%d"),
            "now": (now + off).strftime("%Y-%m-%d %H:%M"), "first_day": first_day(store, site, device, off),
            "nominal_v": _num(prof.get("nominal_v")) or 230.0, "nominal_hz": _num(prof.get("nominal_hz")) or 50.0,
            "pf_load_kw": PF_LOAD_KW, "i_floor_a": lim["i_floor"], "limits": lim_full, "hours": rows,
            "events": events(store, engine, site, device, utc_from, local_end - off)}


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


def current_hourly(store, engine, site, device, days=14, meter="EM01", start=None, end=None):
    """Page Current & balance: one row per local hour (_crow), from the same summaries as hourly()."""
    off = _offset(store, site)
    prof = store.site_profile(site)
    lim_full = limits(engine, site)
    lim = _lim(lim_full, prof)
    now = datetime.now(timezone.utc)
    local_start, local_end = period(off, days, start, end, now)
    utc_from, utc_to = local_start - off, min(local_end - off, now)
    out, tail = {}, []
    for _, path in _files(store, site, device, utc_from - timedelta(days=1), utc_to):
        s = _summarise(path, meter, off, lim)
        for t, d in _d15_cross(tail, s["head"]):   # the 15-minute means across the change of day file
            out.setdefault((t + off).strftime("%Y-%m-%d %H:00"), []).append({"n": 0, "d15": d})
        tail = s["tail"]
        for k, h in s["hours"].items():
            out.setdefault(k, []).append(h)
    first_key, end_key = local_start.strftime("%Y-%m-%d %H:00"), local_end.strftime("%Y-%m-%d %H:00")
    rows = [_crow(k, out[k]) for k in sorted(out) if first_key <= k < end_key]
    pln = pln_a(prof)
    return {"site": site, "device": device, "meter": meter, "utc_offset_h": off.total_seconds() / 3600,
            "from": first_key, "to": (local_end - timedelta(days=1)).strftime("%Y-%m-%d"),
            "now": (now + off).strftime("%Y-%m-%d %H:%M"), "first_day": first_day(store, site, device, off),
            "nominal_v": _num(prof.get("nominal_v")) or 230.0, "pln_a": _r(pln, 1), "rated_a": _num(prof.get("rated_a")),
            "i_floor_a": lim["i_floor"], "i_imb_loaded_a": lim["i_ld"], "i_loaded_a": I_LOADED_A, "pf_load_kw": PH_LOAD_KW,
            "limits": lim_full, "hours": rows,
            "events": events(store, engine, site, device, utc_from, local_end - off, CURRENT_RULES)}


def current_minutes(store, site, device, day, meter="EM01"):
    """{"cols": [...], "rows": [["HH:MM", i1, i1_min, i1_max, ..., p1, p2, p3, iu]]} for one local day; iu is
    empty below 5 A of mean current (as A10)."""
    off = _offset(store, site)
    floor = I_FLOOR_A
    local0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    utc_from, utc_to = local0 - off, local0 - off + timedelta(days=1)
    rows = []
    for _, path in _files(store, site, device, utc_from, utc_to):
        for row in _read(path):
            t = _parse_ts(row.get("ts"))
            if t is None or not (utc_from <= t < utc_to):
                continue
            vals = {c: _num(row.get(f"{meter}_{c}")) for c in CDAY_COLS[1:-1]}
            cur = [vals[f"i{k}"] for k in (1, 2, 3)]
            if all(v is None for v in cur):
                continue
            iu = _unbalance(cur, floor)
            rows.append([(t + off).strftime("%H:%M")] + [vals[c] for c in CDAY_COLS[1:-1]] + [_r(iu, 2)])
    rows.sort(key=lambda r: r[0])
    return {"site": site, "device": device, "meter": meter, "day": day, "cols": list(CDAY_COLS), "rows": rows}
