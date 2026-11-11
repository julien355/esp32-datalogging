#!/usr/bin/env python3
"""Builds docs/mockup/readings/index.html: the site page of the Arkan mockup (server/app/live.html with
docs/mockup/arkan/fixtures.json) plus the PROPOSED pages for meter readings entered by hand (water meter,
power meter 2), with 45 days of simulated readings.

    python3 docs/mockup/readings/build.py

Nothing in server/ is changed: the new pages (readings.js, readings.css) are put into a copy of the page here,
at fixed places of live.html. Every place must be found once, or the build stops. One file, no network.
"""
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "..")
APP = os.path.join(ROOT, "server", "app")
OFF = timedelta(hours=8)          # Adab: Asia/Makassar, UTC+8

# The proposed site.json entry: one line per meter read by hand (docs/mockup/readings/README.md)
METERS = [
    {"id": "water", "name": "Water", "long": "Water, PDAM main meter", "kind": "water", "unit": "m³", "decimals": 3,
     "due_h": 26, "where": "street side, beside the staff entrance"},
    {"id": "pm2", "name": "Power meter 2", "long": "Power meter 2 (read by hand)", "kind": "power", "unit": "kWh", "decimals": 1,
     "due_h": 26, "compare": "EM01", "where": "name and place to confirm"},
]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def utc(local):
    return local - OFF


def iso(dt):
    return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


# ------------------------------------------------------------------ simulated readings
def water_rate(t_local, rnd_day):
    """m³ in the hour starting at t_local (hotel time): a hotel day profile, more at the weekend,
    a leaking WC from 19 to 21 October, the pool topped up on 4 November."""
    h = t_local.hour
    prof = [0.35, 0.3, 0.3, 0.3, 0.4, 0.9, 2.3, 3.1, 2.9, 2.2, 1.7, 1.5, 1.6, 1.5, 1.4, 1.4, 1.6, 2.0, 2.5, 2.6, 2.2, 1.6, 1.0, 0.6]
    v = prof[h] * (1.12 if t_local.weekday() >= 5 else 1.0) * rnd_day
    d = t_local.date().isoformat()
    if "2026-10-19 14" <= t_local.strftime("%Y-%m-%d %H") < "2026-10-21 11":
        v += 0.45                                   # leak: about 11 m³ a day more, night included
    if d == "2026-11-04" and 10 <= h < 14:
        v += 6.0                                    # pool top-up, 24 m³
    return v


def main_profile(fx):
    """kWh of the main meter per hotel hour (the logger's history in the fixtures) and its mean by hour of the day."""
    hours = {r["t"]: r["kwh"] for r in fx["history"]["hours"] if r.get("minutes", 0) >= 55}
    byh = {}
    for t, k in hours.items():
        byh.setdefault(int(t[11:13]), []).append(k)
    mean = {h: sum(v) / len(v) for h, v in byh.items()}
    return hours, mean


def simulate(fx):
    rnd = random.Random(20261110)
    now_utc = datetime.fromisoformat(fx["time"].replace("Z", ""))
    now_local = now_utc + OFF
    start = datetime(2026, 9, 26, 0, 0)               # hotel time
    main_h, main_mean = main_profile(fx)

    # cumulative counters hour by hour (hotel time), from the start to now
    cum = {"water": [18342.105], "pm2": [48210.4]}
    day_rnd_w, day_rnd_p = {}, {}
    t = start
    while t < now_local + timedelta(hours=1):
        d = t.date()
        day_rnd_w.setdefault(d, rnd.uniform(0.9, 1.1))
        day_rnd_p.setdefault(d, rnd.uniform(0.9, 1.1))
        cum["water"].append(cum["water"][-1] + water_rate(t, day_rnd_w[d]) * rnd.uniform(0.95, 1.05))
        key = t.strftime("%Y-%m-%d %H:00")
        main = main_h.get(key, main_mean.get(t.hour, 25.0))
        cum["pm2"].append(cum["pm2"][-1] + 0.31 * main * day_rnd_p[d] * rnd.uniform(0.85, 1.15))   # about 31 % of the main meter
        t += timedelta(hours=1)

    def at(meter, t_local):                           # counter at any time, linear inside the hour
        x = (t_local - start).total_seconds() / 3600
        i = int(x)
        c = cum[meter]
        return c[i] + (c[i + 1] - c[i]) * (x - i)

    # the round: every morning about 08:00; no reading on some Sundays and on 12 to 14 October (Galungan holidays)
    skip = {"2026-10-04", "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-18", "2026-11-01"}
    readings = {"water": [], "pm2": []}
    n = {"water": 0, "pm2": 0}

    def add(meter, t_local, user, note="", entered_after_min=None, hist=None, value=None):
        n[meter] += 1
        dec = 3 if meter == "water" else 1
        v = round(at(meter, t_local) if value is None else value, dec)
        ent = t_local + timedelta(minutes=entered_after_min if entered_after_min is not None else rnd.randint(1, 9))
        r = {"id": f"{meter[0]}{n[meter]:04d}", "t": iso(utc(t_local)), "value": v, "user": user,
             "entered": iso(utc(ent)), "note": note}
        if hist:
            r["hist"] = hist
        readings[meter].append(r)
        return r

    d = start.date()
    while d <= now_local.date():
        ds = d.isoformat()
        if ds not in skip:
            user = "tech-adab" if d.weekday() in (5, 6) else "wayan"
            tw = datetime(d.year, d.month, d.day, 7, 50) + timedelta(minutes=rnd.randint(-15, 25))
            tp = tw + timedelta(minutes=rnd.randint(4, 9))   # power meter 2 a few minutes later, on the same round
            if tw < now_local:
                note = {"2026-10-20": "Night use high: WC of room 12 leaking, reported to maintenance",
                        "2026-10-21": "WC room 12 fixed yesterday 10:30",
                        "2026-11-05": "Pool topped up yesterday 10:00 to 14:00"}.get(ds, "")
                late = 412 if ds == "2026-10-30" else None    # written on paper, typed in the afternoon
                if ds == "2026-10-30":
                    note = "Written on the round sheet, entered later"
                if ds == "2026-10-28":                        # a typing error, corrected by an admin
                    true = round(at("water", tw), 3)
                    add("water", tw, user, "", hist=[
                        {"at": iso(utc(tw + timedelta(minutes=6))), "user": user, "what": "entered", "value": round(true + 1000, 3)},
                        {"at": iso(utc(tw + timedelta(hours=3, minutes=12))), "user": "julien", "what": "corrected",
                         "value": true, "reason": "Typing error: 19 … instead of 18 …, checked on the meter"}])
                else:
                    add("water", tw, user, note, late)
            if tp < now_local and ds != now_local.date().isoformat():   # power meter 2 not read yet today: due
                add("pm2", tp, user, "Written on the round sheet, entered later" if ds == "2026-10-30" else "",
                    412 if ds == "2026-10-30" else None)
        if ds == "2026-11-04":                                # a second reading the same day
            add("water", datetime(2026, 11, 4, 17, 40), "wayan", "After the pool top-up")
        d += timedelta(days=1)

    for m in readings.values():
        m.sort(key=lambda r: r["t"])
    return {"meters": METERS, "readings": readings}


# ------------------------------------------------------------------ the page
def main():
    fx = json.loads(read(os.path.join(ROOT, "docs", "mockup", "arkan", "fixtures.json")))
    fx["manual"] = simulate(fx)
    fx["live"]["profile"]["manual_meters"] = METERS
    page = read(os.path.join(APP, "live.html"))
    js, css = read(os.path.join(HERE, "readings.js")), read(os.path.join(HERE, "readings.css"))
    fxs = json.dumps(fx, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    page_marker = "// ------------------------------------------------------------------ page\n"
    parts = [
        # the proposed pages, inside the page's own script, before the page starts
        (page_marker, js + "\n" + page_marker),
        ("  if (QVIEWS[view]) return QVIEWS[view](box);\n", "  if (QVIEWS[view]) return QVIEWS[view](box);\n  if (MVIEWS[view]) return MVIEWS[view](box);\n"),
        # the entry form is not redrawn by a resize or the 5-minute refresh (it would empty the fields)
        ("const STATIC = ['now', 'firmware', 'prefs', 'register'];", "const STATIC = ['now', 'firmware', 'prefs', 'register', 'readings'];"),
        ("</style>\n<script src=\"/live/_ui/arkan-ui.js\"></script>", css + "</style>\n<script src=\"/live/_ui/arkan-ui.js\"></script>"),
        ("Design mockup · simulated data, 14 days · nothing is sent to a logger",
         "Design mockup · <b>Meter readings</b> pages proposed for review · simulated data · nothing is saved"),
        # then the kit and the saved answers, as docs/mockup/arkan/build.py does
        ('<link rel="stylesheet" href="/live/_ui/arkan-ui.css">', "<style>" + read(os.path.join(APP, "arkan-ui", "arkan-ui.css")) + "</style>"),
        ('<script src="/live/_ui/arkan-ui.js"></script>', "<script>" + read(os.path.join(APP, "arkan-ui", "arkan-ui.js")) + "</script>"),
        ("<title>Live</title>", "<title>Arkan Monitoring: meter readings (proposal)</title>"),
        ("/*__FIXTURES__*/null", fxs),
    ]
    for key, text in parts:
        if page.count(key) != 1:
            sys.exit(f"live.html: expected 1 x {key!r}, found {page.count(key)}")
        page = page.replace(key, text)
    out = os.path.join(HERE, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    r = fx["manual"]["readings"]
    print(f"{out}: {os.path.getsize(out) // 1024} kB, {len(r['water'])} water and {len(r['pm2'])} power meter 2 readings")


if __name__ == "__main__":
    main()
