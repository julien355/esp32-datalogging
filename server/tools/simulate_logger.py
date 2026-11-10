#!/usr/bin/env python3
"""Simulated logger: posts the same CSV records and live snapshots as the real firmware.

Use it to test the VPS before the board is ready, and to rehearse an outage:
    python3 simulate_logger.py --url http://127.0.0.1:8800 --token <token> --backlog-hours 3
    python3 simulate_logger.py --url https://arkan-monitoring.duckdns.org --token <token> --live

--backlog-hours N  first sends N hours of past records in batches of 60 (as after an outage)
--live             then keeps going: a snapshot every 15 s, a record every minute
--resend           sends the last batch twice (the server must count duplicates, not store them)
--event dip|hot|ct|ota|sensor  during the backlog, simulates a voltage dip on L2 (A26, then A05 for 6 min),
                   a hot electrical room (A11), a CT fitted backwards on L3 (A30), a remote firmware update
                   (A35), or a failed outdoor sensor (A14): to test the alarm log
"""

import argparse
import json
import math
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

MINMAX = ["v1", "v2", "v3", "v12", "v23", "v31", "i1", "i2", "i3", "f", "p1", "p2", "p3", "p", "q", "s", "pf"]
METER_COLS = [c for v in MINMAX for c in (v, v + "_min", v + "_max")] + ["e", "eq"]
HEADER = ("ts," + ",".join("EM01_" + c for c in METER_COLS) + ",EM01_n,TH1_t,TH1_rh,TH2_t,TH2_rh,"
          "rssi,heap_kb,up_s,backlog_min,sd,boot")


class Sim:
    def __init__(self, event=None):
        self.event = event
        self.minute_no = 0
        self.e = 184522.70
        self.eq = 40210.10
        self.boot = "poweron@0.4.0"
        self.t0 = time.time()

    def values(self, t, advance=False):
        hour = (datetime.fromtimestamp(t, timezone.utc).hour + 8) % 24   # WITA
        load = 18 + 14 * max(0, math.sin((hour - 6) / 24 * 2 * math.pi)) + random.uniform(-1.5, 1.5)
        # the supply sags a little with the load; the power factor is lower at light load (night), as in most hotels
        v = [233 - 0.12 * load + d + random.uniform(-1.5, 1.5) for d in (0.0, -1.0, 0.8)]
        pf = min(0.98, 0.74 + 0.006 * load + random.uniform(-0.02, 0.02))
        p_ph = [load / 3 * random.uniform(0.9, 1.1) for _ in range(3)]
        i = [p_ph[k] * 1000 / (v[k] * pf) for k in range(3)]
        p = sum(p_ph)
        s = p / pf
        q = math.sqrt(max(0, s * s - p * p))
        out = {"v1": v[0], "v2": v[1], "v3": v[2], "v12": v[0] * 1.732, "v23": v[1] * 1.732, "v31": v[2] * 1.732,
               "i1": i[0], "i2": i[1], "i3": i[2], "f": 50 + random.uniform(-0.05, 0.05),
               "p1": p_ph[0], "p2": p_ph[1], "p3": p_ph[2], "p": p, "q": q, "s": s, "pf": pf}
        if advance:   # one minute of energy, only when a record is made
            self.e += p / 60
            self.eq += q / 60
        out["e"], out["eq"] = self.e, self.eq
        room = 31 + 2 * math.sin((hour - 9) / 24 * 2 * math.pi)
        outdoor = 28 + 4 * math.sin((hour - 9) / 24 * 2 * math.pi)
        out.update({"TH1_t": room + random.uniform(-.2, .2), "TH1_rh": 60 + random.uniform(-2, 2),
                    "TH2_t": outdoor + random.uniform(-.2, .2), "TH2_rh": 75 + random.uniform(-3, 3)})
        return out

    def row(self, minute_ts, backlog):
        v = self.values(minute_ts, advance=True)
        self.minute_no += 1
        mm = {k: (v[k] * 0.99, v[k] * 1.01) for k in MINMAX}
        mm["f"] = (v["f"] - 0.03, v["f"] + 0.03)
        if self.event and 30 <= self.minute_no < 36:       # six minutes of trouble, 30 min into the backlog
            if self.event == "dip":
                v["v2"] = 195.0
                mm["v2"] = (180.0, 205.0)
            elif self.event == "ct":
                v["p3"] = -abs(v["p3"])
                mm["p3"] = (v["p3"] * 1.01, v["p3"] * 0.99)
        if self.event == "hot" and 30 <= self.minute_no < 50:
            v["TH1_t"] = 37.5
        if self.event == "ota" and self.minute_no == 40:
            self.boot = "sw:ota@0.3.1"
        ts = datetime.fromtimestamp(minute_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = []
        for c in MINMAX:
            parts += [f"{v[c]:.3f}", f"{mm[c][0]:.3f}", f"{mm[c][1]:.3f}"]
        parts += [f"{v['e']:.2f}", f"{v['eq']:.2f}"]
        # Sensors: 5-minute means on the rows at :00, :05, ... only (logger 0.3.0); "err" = sensor fault
        if minute_ts % 300:
            th = ",,,"
        elif self.event == "sensor" and 30 <= self.minute_no < 60:
            th = f"{v['TH1_t']:.2f},{v['TH1_rh']:.1f},err,err"
        else:
            th = f"{v['TH1_t']:.2f},{v['TH1_rh']:.1f},{v['TH2_t']:.2f},{v['TH2_rh']:.1f}"
        r = (f"{ts},{','.join(parts)},4,{th},"
             f"-63,180,{int(time.time() - self.t0)},{backlog},1,{self.boot}")
        self.boot = ""
        return r, v


def post(url, token, path, body, ctype):
    req = urllib.request.Request(url.rstrip("/") + path, data=body.encode(), method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": ctype,
                                          "X-Fw": "0.4.0", "X-Schema": "1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8800")
    ap.add_argument("--token", required=True)
    ap.add_argument("--device", default="LOG-0001")
    ap.add_argument("--backlog-hours", type=float, default=0)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--resend", action="store_true")
    ap.add_argument("--event", choices=["dip", "hot", "ct", "ota", "sensor"])
    a = ap.parse_args()
    sim = Sim(a.event)
    now = int(time.time())
    first = now - now % 60 - int(a.backlog_hours * 3600)
    rows = []
    for m in range(first, now - now % 60, 60):
        rows.append(sim.row(m, (now - m) // 60)[0])
    for k in range(0, len(rows), 60):
        batch = rows[k:k + 60]
        code, resp = post(a.url, a.token, "/api/v1/ingest", HEADER + "\n" + "\n".join(batch) + "\n", "text/csv")
        print(f"batch {k // 60 + 1}: {len(batch)} rows {batch[0][:20]} -> HTTP {code} {resp}")
        if a.resend and k + 60 >= len(rows):
            code, resp = post(a.url, a.token, "/api/v1/ingest", HEADER + "\n" + "\n".join(batch) + "\n", "text/csv")
            print(f"same batch again -> HTTP {code} {resp} (expect stored 0, duplicates {len(batch)})")
    if not a.live:
        return
    print("live: snapshot every 15 s, record every minute (Ctrl-C to stop)")
    last_minute = None
    while True:
        t = time.time()
        minute = int(t) - int(t) % 60
        if last_minute is not None and minute != last_minute:
            r, _ = sim.row(last_minute, 0)
            code, resp = post(a.url, a.token, "/api/v1/ingest", HEADER + "\n" + r + "\n", "text/csv")
            print(f"record {r[:20]} -> HTTP {code} {resp}")
        last_minute = minute
        v = sim.values(t)
        snap = {"device": a.device, "ts": datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "values": {("EM01_" + k if not k.startswith("TH") else k): round(x, 3) for k, x in v.items()},
                "sys": {"rssi": -63, "backlog_min": 0, "sd": True, "fw": "sim-0.1.0", "up_s": int(t - sim.t0)}}
        code, _ = post(a.url, a.token, "/api/v1/live", json.dumps(snap), "application/json")
        print(f"live {snap['ts']} -> HTTP {code}")
        time.sleep(15 - time.time() % 15)


if __name__ == "__main__":
    main()
