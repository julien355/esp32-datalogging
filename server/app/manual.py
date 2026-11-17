"""Meters read by hand: a water meter, a power meter the logger does not read. Someone reads the meter's total on site
and types it in on the site page (#readings) with the time; the use of each hotel day is worked out from the readings.

    site.json "manual_meters": the meters, one dict each (meters(); set with manage.py manual-meter):
        {"id": "water", "name": "Water", "long": "Water, PDAM main meter", "kind": "water", "unit": "m³",
         "decimals": 3, "due_h": 26, "where": "street side", "compare": "EM01"}
    sites/<site>/manual/<id>.csv    every entry, correction and deletion of that meter, one line each, never rewritten:
        seq,at,user,action,id,time,value,note,reset,old,reason
        action add (a new reading, id = "r<seq>"), correct (new time, value, note of reading id), delete (reading id);
        at and time in UTC; value as typed, normalised ("20096.870"); reset 1 = the meter was replaced or reset, the
        reading starts a new count, old = the old meter's last figure if known; reason: why it was corrected or deleted.
        The readings are the file read from the top: the first figure and every change stay in it.

How a day's use is worked out (the same rules as the page, docs/mockup/readings/README.md):
- between two readings the use is taken as even: the meter's total at each local midnight is on the straight line
  between the readings just before and after it; a day's use = the total at the next midnight - the total at its own;
- "measured": every interval that covers the day is at most SPREAD_H hours long; "spread": at least one is longer
  (Saturday morning to Monday morning), its use is shared evenly over the days between;
- no figure ("none"): an interval longer than GAP_D days, a reset without the old meter's last figure, before the first
  reading, or after the last one; today: "so_far", from 00:00 to the last reading;
- "usual" = 10th to 90th percentile of the measured days of the last 28 days (at least 5 of them).
"""

import csv
import io
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import history

SPREAD_H = 30          # readings more than 30 h apart: their use is spread evenly over the days between them
GAP_D = 7              # more than 7 days apart: no figure per day
BACK_DAYS = 31         # the page may enter a reading up to 31 days back; older ones: manage.py import-readings
USUAL_DAYS = 28
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
# Page names of the site page (live.html VIEWS): a meter cannot take one, its page is /live/<site>/#<id>
RESERVED = {"now", "power", "day", "energy", "week", "temperature", "humidity", "quality", "voltage", "pf", "wtoday",
            "wtomorrow", "wlog", "register", "versions", "firmware", "sites", "prefs", "readings", "main", "content"}
KINDS = ("water", "power", "gas", "other")
COLS = ["seq", "at", "user", "action", "id", "time", "value", "note", "reset", "old", "reason"]
MAX_TEXT = 200
_lock = threading.Lock()


class ReadingError(ValueError):
    pass


# ---------------------------------------------------------------------- meters, values, times
def meters(prof):
    """The site's meters read by hand, checked and completed with defaults. A bad entry is left out."""
    out, seen = [], set()
    for m in prof.get("manual_meters") or []:
        if not isinstance(m, dict) or not ID_RE.match(str(m.get("id", ""))) or m["id"] in RESERVED or m["id"] in seen:
            continue
        seen.add(m["id"])
        kind = m.get("kind") if m.get("kind") in KINDS else "other"
        try:
            dec = max(0, min(4, int(m.get("decimals", 3 if kind == "water" else 1))))
        except (TypeError, ValueError):
            dec = 3
        try:
            due = float(m.get("due_h", 26))
        except (TypeError, ValueError):
            due = 26.0
        o = {"id": m["id"], "name": str(m.get("name") or m["id"]), "long": str(m.get("long") or m.get("name") or m["id"]),
             "kind": kind, "unit": str(m.get("unit") or ("m³" if kind == "water" else "kWh")), "decimals": dec, "due_h": due}
        for k in ("where", "compare", "short"):
            if m.get(k):
                o[k] = str(m[k])
        out.append(o)
    return out


def meter(prof, mid):
    return next((m for m in meters(prof) if m["id"] == mid), None)


def parse_value(s):
    """What was typed -> (value, decimals typed, normalised text), None when empty. "18921.334", "18921,334",
    "18 921,334" and "18.921,334" (Indonesian) all read 18921.334: one point or one comma is the decimals."""
    if s is None:
        return None
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        s = repr(float(s)) if isinstance(s, float) else str(s)
    s = re.sub(r"[\s  ']", "", str(s))
    if not s:
        return None
    c, d = s.rfind(","), s.rfind(".")
    grouped = lambda x, th: re.match(r"^\d{1,3}(" + re.escape(th) + r"\d{3})+$", x)   # noqa: E731 thousands: groups of 3
    if c >= 0 and d >= 0:                                   # both: the last one is the decimals, the other the thousands
        ds, th = (",", ".") if c > d else (".", ",")
        ip, fp = s.rsplit(ds, 1)
        if not grouped(ip, th):
            raise ReadingError("not a number")
        s = ip.replace(th, "") + "." + fp
    elif s.count(",") > 1 or s.count(".") > 1:              # one kind, several times: thousands only
        th = "," if s.count(",") > 1 else "."
        if not grouped(s, th):
            raise ReadingError("not a number")
        s = s.replace(th, "")
    elif c >= 0:
        s = s.replace(",", ".")
    if not re.match(r"^\d{1,12}(\.\d{1,6})?$", s):
        raise ReadingError("not a number")
    return float(s), len(s.split(".")[1]) if "." in s else 0, s


def fv(v, d=0):
    """20096.87 -> "20 096.870": a narrow space between thousands (never a comma or a point), a point before the decimals."""
    if v is None:
        return "–"
    return ("−" if v < 0 else "") + f"{abs(v):,.{d}f}".replace(",", " ")


def _parse_utc(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_to_utc(text, off):
    """ "YYYY-MM-DDTHH:MM" (or with a space) in hotel time -> UTC datetime, None if it is not that."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})$", str(text or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) - off
    except ValueError:
        return None


def loc(t, off):
    return (t + off).strftime("%Y-%m-%d %H:%M")


def fwhen(t, off):
    """UTC datetime -> "Tue 10 Nov 08:05" in hotel time."""
    x = t + off
    return f"{x.strftime('%a')} {x.day} {x.strftime('%b %H:%M')}"


def fdur(seconds):
    m = round(seconds / 60)
    d, h, mi = m // 1440, m % 1440 // 60, m % 60
    return f"{d} day{'s' if d > 1 else ''} {h} h" if d else f"{h} h {mi:02d} min" if h else f"{mi} min"


def _clean(s, n=MAX_TEXT):
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(s or "")).strip()[:n]


# ---------------------------------------------------------------------- the file
def path(store, site, mid):
    return os.path.join(store.site_dir(site), "manual", mid + ".csv")


def _rows(p):
    """The lines of a meter's file, oldest first. A last line still being written is skipped."""
    try:
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    if text and not text.endswith("\n"):
        text = text[:text.rfind("\n") + 1]
    return list(csv.DictReader(io.StringIO(text)))


def _replay(rows):
    """Every reading by id, deleted ones included (deleted: True), with its history of changes."""
    out = {}
    for r in rows:
        at, user, act, rid = r.get("at"), r.get("user", ""), r.get("action"), r.get("id")
        try:
            v = float(r["value"]) if r.get("value") else None
        except ValueError:
            v = None
        t = _parse_utc(r.get("time"))
        if act == "add" and rid and t and v is not None and rid not in out:
            try:
                old = float(r["old"]) if r.get("old") else None
            except ValueError:
                old = None
            out[rid] = {"id": rid, "t": t, "value": v, "user": user, "entered": _parse_utc(at) or t, "note": r.get("note", ""),
                        "reset": r.get("reset") == "1", "old": old, "deleted": False,
                        "hist": [{"at": at, "user": user, "what": "entered", "value": v}]}
        elif act in ("correct", "delete") and rid in out and not out[rid]["deleted"]:
            x = out[rid]
            h = {"at": at, "user": user, "what": "corrected" if act == "correct" else "deleted", "reason": r.get("reason", "")}
            if act == "delete":
                x["deleted"] = True
            elif t and v is not None:
                h.update(value=v, was=x["value"])
                if t != x["t"]:
                    h.update(t=_iso(t), was_t=_iso(x["t"]))
                x.update(t=t, value=v, note=r.get("note", ""))
            x["hist"].append(h)
    return out


def readings(store, site, mid, deleted=False):
    """The readings of a meter, oldest first (without the deleted ones unless deleted=True)."""
    rs = [r for r in _replay(_rows(path(store, site, mid))).values() if deleted or not r["deleted"]]
    return sorted(rs, key=lambda r: r["t"])


def _append(store, site, mid, row):
    """Add one line (under _lock, by the caller). Returns its seq."""
    p = path(store, site, mid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    new = not os.path.exists(p) or os.path.getsize(p) == 0
    seq = 1
    if not new:
        rows = _rows(p)
        seq = max((int(r["seq"]) for r in rows if (r.get("seq") or "").isdigit()), default=0) + 1
    if row.get("action") == "add":
        row = dict(row, id=f"r{seq}")      # a new reading's id: r<seq>
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if new:
        w.writerow(COLS)
    w.writerow([seq] + [row.get(k, "") for k in COLS[1:]])
    with open(p, "a", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
        f.flush()
        os.fsync(f.fileno())
    return seq


# ---------------------------------------------------------------------- the rules
def check(m, rs, t, raw, off, now, skip=None, reset=False, old=None, usual=None):
    """The checks of a reading, the same as the page's (live.html mmCheck). rs: the meter's readings, oldest first.
    cls "crit" (red) refuses it, "warn" (amber) asks to check it, "good", "muted" (empty). Text in words for the page."""
    u, dec = m["unit"], m["decimals"]

    def R(cls, text, **x):
        return dict(cls=cls, text=text, ok=cls != "crit", **x)
    try:
        n = parse_value(raw)
    except ReadingError:
        return R("crit", "Not a number. Type the figures of the meter, with a point or a comma before the decimals.")
    if n is None:
        return R("muted", "Leave empty to skip this meter.", empty=True)
    if t is None:
        return R("crit", "Choose the date and the time of the reading.")
    if t > now + timedelta(minutes=5):
        return R("crit", "The time is in the future.")
    v, ndec, s = n
    try:
        o = parse_value(old)
    except ReadingError:
        o = None
    old_v = o[0] if o else None
    x = {"v": v, "s": s, "old": old_v, "old_s": o[2] if o else None}
    lst = [r for r in rs if r["id"] != skip]
    prev = next((r for r in reversed(lst) if r["t"] < t), None)
    nxt = next((r for r in lst if r["t"] > t), None)
    same = next((r for r in lst if abs((r["t"] - t).total_seconds()) < 60), None)
    shown = lambda r: f"{fwhen(r['t'], off)} ({fv(r['value'], dec)} {u})"   # noqa: E731
    if same:
        return R("crit", f"There is already a reading at that time: {shown(same)}.")
    if reset and prev and old_v is not None and old_v < prev["value"]:
        return R("crit", f"The old meter's last figure is lower than its reading of {shown(prev)}.")
    if not reset and prev and v < prev["value"]:
        return R("crit", f"Lower than the reading of {shown(prev)}. Check the figure, or tick “Meter replaced or reset”.")
    if nxt and not nxt["reset"] and v > nxt["value"]:
        return R("crit", f"Higher than the later reading of {shown(nxt)}. Check the figure and the time.")
    more = f" The meter shows {dec} decimal{'' if dec == 1 else 's'}: check the figure." if ndec > dec else ""
    if reset:
        tail = "" if not prev else (f"The old meter's use since {fwhen(prev['t'], off)}: {fv(old_v - prev['value'], dec)} {u}."
                                    if old_v is not None else
                                    f"The use from {fwhen(prev['t'], off)} to the change is not known: those days get no figure.")
        return R("warn", f"Starts a new count at {fv(v, dec)} {u}. {tail}{more}", **x)
    if not prev:
        return R("warn" if more else "good", f"First reading of this meter.{more}", **x)
    use, dt = v - prev["value"], (t - prev["t"]).total_seconds()
    dd = day_decimals(m)
    text = f"+{fv(use, dec)} {u} since {fwhen(prev['t'], off)} ({fdur(dt)})"
    if dt < 12 * 3600 or not usual:
        return R("warn" if more else "good", text + "." + more, **x)
    pd = use / dt * 86400
    text += f", {fv(pd, dd)} {u} a day"
    rng = f"usual {fv(usual['lo'], dd)}–{fv(usual['hi'], dd)}"
    if pd > usual["hi"] * 1.5:
        return R("warn", f"{text}: {pd / usual['median']:.1f} × the usual ({rng}). Check the figure; if it is right, say why in the note.", **x)
    if pd < usual["lo"] * 0.5:
        return R("warn", f"{text}: much less than usual ({rng}). Check the figure: meter stuck, or supply cut?", **x)
    return R("warn" if more else "good", f"{text}, {rng}.{more}", **x)


def day_decimals(m):
    return 1 if m["kind"] == "water" else 0


def intervals(rs, off):
    """From one reading to the next: the use, and whether it is spread (over SPREAD_H) or not counted per day (gap)."""
    out = []
    for a, b in zip(rs, rs[1:]):
        dt = (b["t"] - a["t"]).total_seconds()
        if b["reset"]:
            use = None if b["old"] is None else b["old"] - a["value"]
        else:
            use = b["value"] - a["value"]
        if use is not None and use < 0:
            use = None
        out.append({"from": loc(a["t"], off), "to": loc(b["t"], off), "t0": a["t"], "t1": b["t"], "a": a["id"], "b": b["id"],
                    "use": None if use is None else round(use, 6), "h": round(dt / 3600, 3),
                    "per_day": None if use is None or dt <= 0 else round(use / dt * 86400, 3),
                    "spread": dt > SPREAD_H * 3600, "gap": use is None or dt > GAP_D * 86400})
    return out


def day_use(segs, day, off, today):
    """One local day (a date): its use from the intervals, how it was worked out, and the readings behind it."""
    d0 = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - off
    d1 = d0 + timedelta(days=1)
    use = cov = span = 0.0
    spread, s0, s1, via = False, None, None, []
    for s in segs:
        if s["gap"]:
            continue
        o0, o1 = max(d0, s["t0"]), min(d1, s["t1"])
        if o1 <= o0:
            continue
        part = (o1 - o0).total_seconds()
        use += s["use"] * part / (s["t1"] - s["t0"]).total_seconds()
        cov += part
        spread = spread or s["spread"]
        span = max(span, s["h"])
        if not via:
            via.append(s["from"])
        via.append(s["to"])
        s0 = o0 if s0 is None else min(s0, o0)
        s1 = o1 if s1 is None else max(s1, o1)
    if cov >= 86400 - 60:
        how = "spread" if spread else "measured"
    elif day == today and cov > 0 and s0 <= d0 + timedelta(minutes=1) and abs((s1 - s0).total_seconds() - cov) < 60:
        how = "so_far"
    else:
        how = "none"
    return {"date": day.isoformat(), "use": None if how == "none" else round(use, 3), "how": how,
            "via": [] if how == "none" else via, "span_h": round(span, 2), "until": loc(s1, off) if how == "so_far" else None}


def usual(segs, off, today):
    vals = []
    for i in range(USUAL_DAYS, 0, -1):
        x = day_use(segs, today - timedelta(days=i), off, today)
        if x["how"] == "measured":
            vals.append(x["use"])
    if len(vals) < 5:
        return None
    vals.sort()
    q = lambda p: vals[min(len(vals) - 1, int(p * len(vals)))]   # noqa: E731
    return {"lo": q(0.1), "hi": q(0.9), "median": q(0.5), "days": len(vals)}


def _out(r, off):
    return {"id": r["id"], "t": _iso(r["t"]), "local": loc(r["t"], off), "value": r["value"], "user": r["user"], "reset": r["reset"]}


def meter_view(store, site, m, off, d_from, d_to, now):
    """One meter for the page and the API: its readings of the period (newest first), the use of each day, the
    intervals between readings, the usual range, the last reading and whether a reading is due."""
    rs = readings(store, site, m["id"])
    segs = intervals(rs, off)
    today = (now + off).date()
    days, d = [], d_from
    while d <= d_to:
        days.append(day_use(segs, d, off, today))
        d += timedelta(days=1)
    us = usual(segs, off, today)
    by_b = {s["b"]: s for s in segs}
    in_p = lambda r: d_from <= (r["t"] + off).date() <= d_to   # noqa: E731
    out = []
    for r in reversed([r for r in rs if in_p(r)]):
        s = by_b.get(r["id"])
        out.append(dict(_out(r, off), entered=_iso(r["entered"]), entered_local=loc(r["entered"], off), note=r["note"],
                        old=r["old"], hist=r["hist"] if len(r["hist"]) > 1 else None,
                        use=s["use"] if s else None, h=s["h"] if s else None, per_day=s["per_day"] if s else None,
                        high=bool(s and us and s["h"] >= 12 and s["per_day"] is not None and s["per_day"] > us["hi"] * 1.5)))
    before = next((r for r in reversed(rs) if (r["t"] + off).date() < d_from), None)
    last = rs[-1] if rs else None
    ago = (now - last["t"]).total_seconds() / 3600 if last else None
    return dict(m, readings=out, before=_out(before, off) if before else None, last=_out(last, off) if last else None,
                due=ago is not None and ago > m["due_h"], ago_h=None if ago is None else round(ago, 2), days=days, usual=us,
                first_day=(rs[0]["t"] + off).date().isoformat() if rs else None,
                intervals=[{k: v for k, v in s.items() if k not in ("t0", "t1")} for s in segs
                           if d_from <= (s["t1"] + off).date() <= d_to])


def view(store, site, days=14, start=None, end=None, now=None, only=None):
    """GET /api/v1/manual/<site>: every meter of the site read by hand (or only one). ValueError for a bad period."""
    now = now or datetime.now(timezone.utc)
    off = history._offset(store, site)
    d0, d1 = history.period(off, days, start, end, now)
    d_from, d_to = d0.date(), (d1 - timedelta(days=1)).date()
    ms = [m for m in meters(store.site_profile(site)) if only is None or m["id"] == only]
    return {"site": site, "now": loc(now, off), "from": d_from.isoformat(), "to": d_to.isoformat(),
            "spread_h": SPREAD_H, "gap_d": GAP_D, "back_days": BACK_DAYS,
            "meters": [meter_view(store, site, m, off, d_from, d_to, now) for m in ms]}


# ---------------------------------------------------------------------- entries
def add(store, site, mid, body, user, now=None, source="page"):
    """A new reading. body: {time: "YYYY-MM-DDTHH:MM" hotel time, value, note, reset, old}.
    Returns (http status, answer). source "import" (manage.py) has no BACK_DAYS limit."""
    now = now or datetime.now(timezone.utc)
    m = meter(store.site_profile(site), mid)
    if not m:
        return 404, {"ok": False, "error": f"no meter {mid} read by hand on this site (site.json manual_meters)"}
    off = history._offset(store, site)
    t = local_to_utc(body.get("time"), off)
    if t is None:
        return 400, {"ok": False, "error": "time: YYYY-MM-DDTHH:MM, hotel time"}
    if source != "import" and t < now - timedelta(days=BACK_DAYS):
        return 400, {"ok": False, "error": f"more than {BACK_DAYS} days ago: an admin imports older readings "
                                           "(manage.py import-readings)"}
    reset = bool(body.get("reset"))
    with _lock:
        rs = readings(store, site, mid)
        segs = intervals(rs, off)
        c = check(m, rs, t, body.get("value"), off, now, reset=reset, old=body.get("old") if reset else None,
                  usual=usual(segs, off, (now + off).date()))
        if c.get("empty"):
            return 400, {"ok": False, "error": "no figure"}
        if not c["ok"]:
            return 400, {"ok": False, "error": c["text"]}
        seq = _append(store, site, mid, {"at": _iso(now), "user": user, "action": "add", "id": "", "time": _iso(t),
                                         "value": c["s"], "note": _clean(body.get("note")), "reset": "1" if reset else "",
                                         "old": c["old_s"] if reset and c["old_s"] else "", "reason": ""})
    r = {"id": f"r{seq}", "t": _iso(t), "local": loc(t, off), "value": c["v"], "user": user}
    return 200, {"ok": True, "reading": r, "warning": c["text"] if c["cls"] == "warn" else ""}


def change(store, site, mid, rid, body, user, admin, now=None):
    """A correction ({time, value, note, reason}) or a deletion ({delete: true, reason}) of a reading: by the person
    who entered it, or an admin; a reason is required. Returns (http status, answer)."""
    now = now or datetime.now(timezone.utc)
    m = meter(store.site_profile(site), mid)
    if not m:
        return 404, {"ok": False, "error": f"no meter {mid} read by hand on this site"}
    off = history._offset(store, site)
    reason = _clean(body.get("reason"))
    with _lock:
        rs = readings(store, site, mid)
        r = next((x for x in rs if x["id"] == rid), None)
        if not r:
            return 404, {"ok": False, "error": "no such reading"}
        if r["user"] != user and not admin:
            return 403, {"ok": False, "error": "only the person who entered it, or an admin (ADMIN_USERS), can change it"}
        if not reason:
            return 400, {"ok": False, "error": "say why"}
        if body.get("delete"):
            _append(store, site, mid, {"at": _iso(now), "user": user, "action": "delete", "id": rid, "reason": reason})
            return 200, {"ok": True}
        t = local_to_utc(body.get("time"), off) if body.get("time") else r["t"]
        if t is None:
            return 400, {"ok": False, "error": "time: YYYY-MM-DDTHH:MM, hotel time"}
        c = check(m, rs, t, body.get("value"), off, now, skip=rid, reset=r["reset"],
                  usual=usual(intervals(rs, off), off, (now + off).date()))
        if c.get("empty"):
            return 400, {"ok": False, "error": "no figure: delete the reading instead"}
        if not c["ok"]:
            return 400, {"ok": False, "error": c["text"]}
        note = _clean(body["note"]) if "note" in body else r["note"]
        _append(store, site, mid, {"at": _iso(now), "user": user, "action": "correct", "id": rid, "time": _iso(t),
                                   "value": c["s"], "note": note, "reason": reason})
    return 200, {"ok": True, "reading": {"id": rid, "t": _iso(t), "local": loc(t, off), "value": c["v"], "user": r["user"]},
                 "warning": c["text"] if c["cls"] == "warn" else ""}


# ---------------------------------------------------------------------- CSV
def csv_text(v, what):
    """CSV of one meter of view(): what "days" (use per hotel day) or "readings" (the readings of the period)."""
    m = v["meters"][0]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    u = m["unit"]
    if what == "days":
        w.writerow(["date", f"use_{u}", "how", "readings", "until"])
        for d in m["days"]:
            w.writerow([d["date"], "" if d["use"] is None else f"{d['use']:.3f}", d["how"], " > ".join(d["via"]), d["until"] or ""])
    else:
        w.writerow(["time_local", "time_utc", f"reading_{u}", f"use_since_previous_{u}", "hours", f"per_day_{u}", "user",
                    "entered_utc", "note", "new_count", "old_meter_last", "corrected"])
        for r in reversed(m["readings"]):
            w.writerow([r["local"], r["t"], f"{r['value']:.{m['decimals']}f}", "" if r["use"] is None else f"{r['use']:.{m['decimals']}f}",
                        "" if r["h"] is None else f"{r['h']:.2f}", "" if r["per_day"] is None else f"{r['per_day']:.3f}",
                        r["user"], r["entered"], r["note"], "1" if r["reset"] else "", "" if r["old"] is None else r["old"],
                        "1" if r["hist"] else ""])
    return buf.getvalue()
