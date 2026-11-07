#!/usr/bin/env python3
"""Build the dashboard mockup page (docs/mockup/index.html) from a monitoring data folder.

How the mockup was made (README.md in this folder):
  1. a local ingest service fed by tools/simulate_logger.py (14 days of backlog, then --live);
  2. screenshots of the real live pages (/live/ and /live/adab/) in img/;
  3. this script: reads the site's day files and daily.csv and draws the Open Energy Dashboard
     graphs the plan configures (tutorial 3, Part D), as an approximation of OED's graph page.

    python3 docs/mockup/build_mockup.py --data <data folder> [--site adab] [--device LOG-0001]

Python 3.9+, standard library only. The output is one HTML file with the data inside; it needs
the img/ folder beside it.
"""

import argparse
import csv
import glob
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_rows(data, site, device):
    rows = []
    for f in sorted(glob.glob(os.path.join(data, "sites", site, device, "raw", "*", "*", "*.csv"))):
        with open(f, newline="") as fh:
            rows.extend(csv.DictReader(fh))
    rows.sort(key=lambda r: r["ts"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--site", default="adab")
    ap.add_argument("--device", default="LOG-0001")
    ap.add_argument("--out", default=os.path.join(HERE, "index.html"))
    a = ap.parse_args()

    prof = json.load(open(os.path.join(a.data, "sites", a.site, "site.json")))
    off = timedelta(hours=prof.get("utc_offset_h", 8))
    rows = read_rows(a.data, a.site, a.device)
    if not rows:
        raise SystemExit("no records found")

    def local(r):
        return datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + off

    # Hourly kWh (= mean kW, what OED's line graph shows with unit kWh and rate Hour), from the counter
    hourly = defaultdict(list)
    sens = defaultdict(lambda: defaultdict(list))
    minute = []
    prev = None
    for r in rows:
        t = local(r)
        e = fnum(r.get("EM01_e"))
        if prev is not None and e is not None and prev[1] is not None:
            hourly[t.replace(minute=0, second=0)].append((e - prev[1]) * 60)   # kWh in one minute -> kW
        prev = (t, e)
        for k in ("TH1_t", "TH2_t", "TH1_rh", "TH2_rh"):
            v = fnum(r.get(k))
            if v is not None:
                sens[k][t.replace(minute=0, second=0)].append(v)
        minute.append((t, fnum(r.get("EM01_p"))))

    def fmt(t):
        return t.strftime("%Y-%m-%d %H:%M")

    hours = sorted(hourly)
    kw_hour = [[fmt(h), round(sum(hourly[h]) / len(hourly[h]), 2)] for h in hours]

    # One full local day at 1-minute resolution (OED after zoom + Redraw)
    last = local(rows[-1]).date()
    zoom_day = last - timedelta(days=1)
    kw_minute = [[fmt(t), round(p, 2)] for t, p in minute if t.date() == zoom_day and p is not None]

    def hourly_series(k):
        return [[fmt(h), round(sum(v) / len(v), 2)] for h, v in sorted(sens[k].items())]

    # Daily kWh (OED bar, interval Day) from daily.csv
    days = []
    with open(os.path.join(a.data, "sites", a.site, "daily.csv"), newline="") as fh:
        for d in csv.DictReader(fh):
            if d.get("device") == a.device:
                days.append({"date": d["date"], "kwh": fnum(d["EM01_e_delta"]), "cov": fnum(d["coverage_pct"]),
                             "peak": fnum(d["EM01_p_max"]), "peak_t": d["EM01_p_max_time"],
                             "tmin": fnum(d["TH1_t_min"]), "tmax": fnum(d["TH1_t_max"])})

    # OED Compare, Week: this week so far (weeks start on Sunday 00:00) against the same time last week
    now = local(rows[-1])
    week0 = datetime.combine(now.date() - timedelta(days=(now.weekday() + 1) % 7), datetime.min.time(), now.tzinfo)
    lweek0 = week0 - timedelta(days=7)
    elapsed = now - week0

    def energy_between(t0, t1):
        es = [fnum(r["EM01_e"]) for r in rows if t0 <= local(r) <= t1 and fnum(r.get("EM01_e")) is not None]
        return round(es[-1] - es[0], 1) if len(es) > 1 else None

    compare = {"this": energy_between(week0, now), "last": energy_between(lweek0, lweek0 + elapsed),
               "this_from": fmt(week0), "last_from": fmt(lweek0), "elapsed_h": round(elapsed.total_seconds() / 3600, 1),
               "now": fmt(now)}

    alarms = []
    for f in sorted(glob.glob(os.path.join(a.data, "sites", a.site, "alarms", "*.csv"))):
        with open(f, newline="") as fh:
            alarms.extend(csv.DictReader(fh))

    data = {"site": prof.get("name", a.site), "code": a.site, "kw_hour": kw_hour, "kw_minute": kw_minute,
            "zoom_day": zoom_day.isoformat(), "t_room": hourly_series("TH1_t"), "t_out": hourly_series("TH2_t"),
            "rh_room": hourly_series("TH1_rh"), "rh_out": hourly_series("TH2_rh"), "days": days, "compare": compare,
            "contracted_kva": prof.get("contracted_kva"),
            "alarms": [{k: r.get(k) for k in ("local_time", "id", "name", "severity", "state", "value", "unit", "message")}
                       for r in alarms][-12:],
            "range": [fmt(local(rows[0])), fmt(now)]}

    tpl = open(os.path.join(HERE, "template.html")).read()
    out = tpl.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    with open(a.out, "w") as fh:
        fh.write(out)
    print(f"{a.out}: {len(kw_hour)} hourly points, {len(kw_minute)} minute points, {len(days)} days, "
          f"compare {compare['last']} -> {compare['this']} kWh")


if __name__ == "__main__":
    main()
