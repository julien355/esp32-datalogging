"""History for the site page's graphs, read from the day files (no database).

    hourly(store, site, device, days)   one row per local hour: kWh, mean and peak kW, sensor means, min and max
    minutes(store, site, device, day)   the 1-minute power of one local day
    open_records(store, site, device)   the original day files of a period, for the CSV download (csv_chunks)

A period is the last `days` local days (today included) or the local dates start to end (both included, at most
MAX_DAYS days): see period().

Local time = UTC + the site's utc_offset_h (WITA, UTC+8, at Adab). Energy comes from the meter's cumulative
counter (EM01_e): each step between two records less than MAX_GAP_S apart is given to the hour of the later
record; a counter that goes down is ignored (alarm A19 reports it). Each day file is summarised once and kept
in memory until it changes (one small dict per file, about 24 hours x 12 numbers).
"""

import csv
import os
import threading
from datetime import datetime, timedelta, timezone

MAX_GAP_S = 3600
MAX_DAYS = 92                 # longest period of the pages and of the CSV download (about 3 months)
SYS_COLS = ("ts", "rssi", "heap_kb", "up_s", "backlog_min", "sd", "boot")

_cache = {}          # path -> (mtime, size, summary)
_lock = threading.Lock()


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _offset(store, site):
    try:
        return timedelta(hours=float(store.site_profile(site).get("utc_offset_h", 8)))
    except (TypeError, ValueError):
        return timedelta(hours=8)


def period(off, days=7, start=None, end=None, now=None):
    """(first day 00:00, the day after the last 00:00), in local time, of the last `days` days up to today or of the
    dates start to end ("YYYY-MM-DD", both included; end alone is not allowed, start alone runs to today).
    ValueError: a bad date, an end before the start, or more than MAX_DAYS days."""
    now = now or datetime.now(timezone.utc)
    today = (now + off).replace(hour=0, minute=0, second=0, microsecond=0)
    if start or end:
        if not start:
            raise ValueError("to without from")
        d0 = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        d1 = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end else today
        if d1 < d0 or (d1 - d0).days >= MAX_DAYS:
            raise ValueError(f"from must be before to, at most {MAX_DAYS} days")
        return d0, d1 + timedelta(days=1)
    days = max(1, min(int(days), MAX_DAYS))
    return today - timedelta(days=days - 1), today + timedelta(days=1)


def first_day(store, site, device, off):
    """Local date of a logger's oldest record (None without records): the earliest date the pages can show."""
    for _, _, path in store.day_files(site, device):
        try:
            with open(path, encoding="utf-8") as f:
                f.readline()
                for ln in f:
                    t = _parse_ts(ln.split(",", 1)[0])
                    if t:
                        return (t + off).strftime("%Y-%m-%d")
        except OSError:
            continue
    return None


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _summarise(path, meter, off):
    """Per local hour of one day file. The first record's energy step is computed by the caller."""
    st = os.stat(path)
    key = (path, meter, off)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
    hours, first, last = {}, None, None
    e_col, p_col, pmax_col = f"{meter}_e", f"{meter}_p", f"{meter}_p_max"
    prev_t = prev_e = None
    for row in _read(path):
        t = _parse_ts(row.get("ts"))
        if t is None:
            continue
        lt = t + off
        h = hours.setdefault(lt.strftime("%Y-%m-%d %H:00"), {"n": 0, "kwh": 0.0, "sums": {}, "cnt": {}, "min": {}, "max": {}})
        h["n"] += 1
        e = _num(row.get(e_col))
        if e is not None:
            if first is None:
                first = (t, e)
            if prev_e is not None and 0 < (t - prev_t).total_seconds() <= MAX_GAP_S and e >= prev_e:
                h["kwh"] += e - prev_e
            prev_t, prev_e = t, e
            last = (t, e)
        for col, val in row.items():
            if col in SYS_COLS or col is None:
                continue
            if not (col in (p_col, pmax_col) or col.startswith("TH")):
                continue
            v = _num(val)
            if v is None:
                continue
            h["sums"][col] = h["sums"].get(col, 0.0) + v
            h["cnt"][col] = h["cnt"].get(col, 0) + 1
            h["min"][col] = min(h["min"].get(col, v), v)
            h["max"][col] = max(h["max"].get(col, v), v)
    summary = {"hours": hours, "first": first, "last": last}
    with _lock:
        _cache[key] = (st.st_mtime_ns, st.st_size, summary)
        if len(_cache) > 512:
            _cache.pop(next(iter(_cache)))
    return summary


def _files(store, site, device, utc_from, utc_to):
    d0, d1 = utc_from.strftime("%Y-%m-%d"), utc_to.strftime("%Y-%m-%d")
    return [(day, path) for day, _, path in store.day_files(site, device) if d0 <= day <= d1]


def hourly(store, site, device, days=15, meter="EM01", start=None, end=None):
    off = _offset(store, site)
    now = datetime.now(timezone.utc)
    local_start, local_end = period(off, days, start, end, now)
    utc_from, utc_to = local_start - off, min(local_end - off, now)
    out, prev_last = {}, None
    for _, path in _files(store, site, device, utc_from - timedelta(days=1), utc_to):
        s = _summarise(path, meter, off)
        # the energy step from the previous file's last record to this file's first one
        if prev_last and s["first"]:
            (t0, e0), (t1, e1) = prev_last, s["first"]
            if 0 < (t1 - t0).total_seconds() <= MAX_GAP_S and e1 >= e0:
                k = (t1 + off).strftime("%Y-%m-%d %H:00")
                out.setdefault(k, {"kwh": 0.0, "parts": []})["kwh"] += e1 - e0
        if s["last"]:
            prev_last = s["last"]
        for k, h in s["hours"].items():
            o = out.setdefault(k, {"kwh": 0.0, "parts": []})
            o["kwh"] += h["kwh"]
            o["parts"].append(h)
    first_key, end_key = local_start.strftime("%Y-%m-%d %H:00"), local_end.strftime("%Y-%m-%d %H:00")
    rows = []
    for k in sorted(out):
        if not first_key <= k < end_key:
            continue
        o = out[k]
        n = sum(p["n"] for p in o["parts"])
        r = {"t": k, "minutes": n, "kwh": round(o["kwh"], 3)}
        sums, cnt, mn, mx = {}, {}, {}, {}
        for p in o["parts"]:
            for c, v in p["sums"].items():
                sums[c] = sums.get(c, 0.0) + v
                cnt[c] = cnt.get(c, 0) + p["cnt"][c]
                mn[c] = min(mn.get(c, p["min"][c]), p["min"][c])
                mx[c] = max(mx.get(c, p["max"][c]), p["max"][c])
        p_col, pmax_col = f"{meter}_p", f"{meter}_p_max"
        if p_col in cnt:
            r["p"] = round(sums[p_col] / cnt[p_col], 3)
            r["p_max"] = round(mx.get(pmax_col, mx[p_col]), 3)
        for c in sorted(cnt):
            if c.startswith("TH") and not c.endswith(("_min", "_max")):
                r[c] = round(sums[c] / cnt[c], 2)
                r[c + "_min"], r[c + "_max"] = round(mn[c], 2), round(mx[c], 2)
        rows.append(r)
    return {"site": site, "device": device, "meter": meter, "utc_offset_h": off.total_seconds() / 3600,
            "from": first_key, "to": (local_end - timedelta(days=1)).strftime("%Y-%m-%d"),
            "now": (now + off).strftime("%Y-%m-%d %H:%M"), "first_day": first_day(store, site, device, off), "hours": rows}


def minutes(store, site, device, day, meter="EM01"):
    """[["HH:MM", p, p_min, p_max], ...] for one local day (YYYY-MM-DD)."""
    off = _offset(store, site)
    local0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    utc_from, utc_to = local0 - off, local0 - off + timedelta(days=1)
    pts = []
    for _, path in _files(store, site, device, utc_from, utc_to):
        for row in _read(path):
            t = _parse_ts(row.get("ts"))
            if t is None or not (utc_from <= t < utc_to):
                continue
            p = _num(row.get(f"{meter}_p"))
            if p is None:
                continue
            pts.append([(t + off).strftime("%H:%M"), p, _num(row.get(f"{meter}_p_min")), _num(row.get(f"{meter}_p_max"))])
    pts.sort()
    return {"site": site, "device": device, "meter": meter, "day": day, "minutes": pts}


def open_records(store, site, device, days=7, start=None, end=None):
    """The original day files that hold the records of a period of local days, for the CSV download.

    The files are UTC days, so the first and the last one reach a few hours outside the period (no row is removed).
    Returns (first date, last date, [(header, open file, bytes after the header)]). The files are opened and measured
    under the store's lock, so a row being written is never cut and a file rewritten by a backfill is read whole.
    The caller streams them with csv_chunks() and closes them."""
    off = _offset(store, site)
    local_start, local_end = period(off, days, start, end)
    files = _files(store, site, device, local_start - off, local_end - off - timedelta(seconds=1))
    out = []
    with store.lock:
        try:
            for _, path in files:
                f = open(path, "rb")
                header = f.readline()
                out.append((header.rstrip(b"\r\n"), f, os.fstat(f.fileno()).st_size - len(header)))
        except OSError:
            for _, f, _ in out:
                f.close()
            raise
    return local_start.strftime("%Y-%m-%d"), (local_end - timedelta(days=1)).strftime("%Y-%m-%d"), out


def csv_chunks(files, size=1 << 16):
    """One CSV from open_records(): the header once, then the rows of every file in order, as they are in the files.
    When the columns changed during the period (a _2 file, docs/DATA-FORMAT.md), the header has every column in the
    order first seen and each row its values under its own columns (empty under the others)."""
    cols = []
    for header, _, _ in files:
        cols += [c for c in header.split(b",") if c not in cols]
    yield b",".join(cols) + b"\n"
    for header, f, n in files:
        if header.split(b",") == cols:          # the usual case: the bytes of the file, unchanged
            last = b"\n"
            while n > 0:
                b = f.read(min(size, n))
                if not b:
                    break
                n -= len(b)
                last = b[-1:]
                yield b
            if last != b"\n":
                yield b"\n"
            continue
        at = [cols.index(c) for c in header.split(b",")]
        out = []
        for ln in f.read(n).splitlines():       # one day file, under 1 MB
            if not ln.strip():
                continue
            cells = [b""] * len(cols)
            for i, v in zip(at, ln.split(b",")):
                cells[i] = v
            out.append(b",".join(cells) + b"\n")
        yield b"".join(out)
