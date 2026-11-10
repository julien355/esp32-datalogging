#!/usr/bin/env python3
"""Saves the answers of a local ingest service (simulated data) as fixtures.json for the Arkan-design mockup.

    python3 docs/mockup/arkan/capture.py --url http://127.0.0.1:8800 --site adab --user julien

The service must run with ADMIN_USERS=<user>. The simulated logger sends no settings report, so the register table,
the firmware history and the day-ahead forecast are filled in here with made-up values: the mockup shows every part
of each page. Nothing here is real hotel data.
"""
import argparse
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# The table built into the firmware (firmware/src/meter.cpp)
BUILTIN = [("v1", 0x0000, "u16", 0.1, 0, "minmax"), ("v2", 0x0001, "u16", 0.1, 0, "minmax"), ("v3", 0x0002, "u16", 0.1, 0, "minmax"),
           ("v12", 0x0003, "u16", 0.1, 0, "minmax"), ("v23", 0x0004, "u16", 0.1, 0, "minmax"), ("v31", 0x0005, "u16", 0.1, 0, "minmax"),
           ("i1", 0x0006, "u16", 0.001, 1, "minmax"), ("i2", 0x0007, "u16", 0.001, 1, "minmax"), ("i3", 0x0008, "u16", 0.001, 1, "minmax"),
           ("f", 0x0009, "u16", 0.01, 0, "minmax"), ("p1", 0x000A, "s16", 0.001, 1, "minmax"), ("p2", 0x000B, "s16", 0.001, 1, "minmax"),
           ("p3", 0x000C, "s16", 0.001, 1, "minmax"), ("p", 0x000D, "s16", 0.001, 1, "minmax"), ("q", 0x000E, "s16", 0.001, 1, "minmax"),
           ("s", 0x000F, "u16", 0.001, 1, "minmax"), ("pf", 0x0010, "s16", 0.001, 0, "minmax"), ("e", 0x0018, "u32", 0.01, 0, "last"),
           ("eq", 0x001A, "u32", 0.01, 0, "last")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8800")
    ap.add_argument("--site", default="adab")
    ap.add_argument("--user", default="julien")
    a = ap.parse_args()

    def get(path):
        req = urllib.request.Request(a.url + path, headers={"X-Auth-User": a.user})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    s = a.site
    fx = {"site": s, "status": get("/api/v1/status"), "live": get(f"/api/v1/live/{s}"), "alarms": get(f"/api/v1/alarms/{s}"),
          "history": get(f"/api/v1/history/{s}?days=31"), "weather": get(f"/api/v1/weather/{s}"),
          "wxlog": get(f"/api/v1/weather/{s}/log?days=31"), "versions": get(f"/api/v1/versions/{s}"),
          "me": get("/api/v1/admin/me"), "github": get("/api/v1/admin/github/releases")}
    fx["time"] = fx["live"]["time"]
    dev = sorted(fx["status"]["sites"][s])[0]
    fx["fw"] = get(f"/api/v1/admin/fw/{dev}")
    fx["registers"] = get(f"/api/v1/admin/registers/{dev}")
    days = sorted({r["t"][:10] for r in fx["history"]["hours"]})[-3:]
    fx["days"] = {d: get(f"/api/v1/history/{s}/day/{d}") for d in days}

    # ---- made-up parts (the simulator does not send them)
    t0 = fx["time"]
    rows = [{"name": n, "fc": 3, "addr": ad, "type": ty, "scale": sc, "ct": bool(ct), "agg": ag} for n, ad, ty, sc, ct, ag in BUILTIN]
    csv = "name,fc,addr,type,scale,ct,agg\n" + "".join(
        f"{n},3,0x{ad:04X},{ty},{sc},{ct},{ag}\n" for n, ad, ty, sc, ct, ag in BUILTIN)
    csv1 = csv.replace("i1,3,0x0006,u16,0.001", "i1,3,0x0006,u16,0.01")
    v2 = {"version": 2, "updated": "2026-11-08T06:12:00Z", "by": a.user, "builtin": False, "csv": csv,
          "comment": "Current scale fixed after the LCD check"}
    v1 = {"version": 1, "updated": "2026-11-07T09:40:00Z", "by": a.user, "builtin": False, "csv": csv1, "comment": "First table from the meter guide"}
    fx["registers"].update(state="applied", platform=v2, history=[v2, v1], reported={
        "received": "2026-11-08T06:20:31Z", "fw": "0.4.0", "reg_source": "sd", "reg_version": 2, "reg_error": None, "rows": rows,
        "settings": {"meters": "EM01:1", "mb_baud": "9600", "mb_format": "8N1", "ct_mult": "1", "rcfg_check_m": "15"}})
    hist = [{"kind": "boot", "reason": "sw:remote_regs@0.4.0", "ts": "2026-11-08T06:20:31Z", "record": "2026-11-08T06:20:00Z"},
            {"kind": "boot", "reason": "sw:ota@0.4.0", "ts": "2026-11-08T12:05:40Z", "record": "2026-11-08T12:05:00Z"},
            {"kind": "firmware", "from": "0.3.0", "to": "0.4.0", "ts": "2026-11-08T12:05:40Z"},
            {"kind": "ota_offered", "version": "0.4.0", "source": "fw-v0.4.0", "by": a.user, "ts": "2026-11-08T12:03:10Z"},
            {"kind": "boot", "reason": "poweron@0.3.0", "ts": "2026-10-27T03:27:00Z", "record": "2026-10-27T03:27:00Z"},
            {"kind": "firmware", "from": None, "to": "0.3.0", "ts": "2026-10-27T03:27:00Z"}]
    hist.sort(key=lambda e: e["ts"], reverse=True)
    offer = {"version": "0.4.0", "file": "logger-0.4.0.bin", "source": "fw-v0.4.0", "scope": "device", "by": a.user, "published": "2026-11-08T12:03:10Z"}
    for lg in fx["versions"]["loggers"]:
        lg.update(env="usb", since="2026-11-08T12:05:40Z", added="2026-10-27T03:20:00Z", reported="2026-11-08T12:05:52Z", schema=1,
                  cfg_version=3, reg_version=2, reg_source="SD card /config/registers.csv", ota_on="1", offer=offer, state="installed",
                  last_boot=hist[0], history=hist)
        lg["running"] = "0.4.0"
    files = [{"file": "logger-0.4.0.bin", "version": "0.4.0", "env": "usb", "size": 1099136}]
    fx["versions"]["files"] = files
    fx["fw"].update(env="usb", ota_on="1", offer=offer, state="installed", files=files, events=hist)
    for d in fx["live"]["devices"].values():
        d["last"].setdefault("sys", {})["fw"] = "0.4.0"
        d["last"]["sys"]["up_s"] = 141300
    for devs in fx["status"]["sites"].values():
        for d in devs.values():
            d["fw"] = "0.4.0"
    # one open alarm, so the review shows the alarm card
    fx["live"]["alarms"] = [{"id": "A11", "name": "Electrical room hot", "severity": "warning", "since": t0[:11] + "01:40:00Z",
                             "worst": 35.4, "unit": "C"}]
    # the day-ahead forecast of each logged hour: the actual value, shifted a little
    for i, r in enumerate(fx["wxlog"]["hours"]):
        if r.get("temp_c") is None:
            continue
        r["fc_temp_c"] = round(r["temp_c"] + ((i * 7) % 11 - 5) * 0.22 + 0.3, 1)
        r["fc_precip_mm"] = r.get("precip_mm")
        r["fc_code"], r["fc_condition"] = r.get("code"), r.get("condition")
    for d in fx["wxlog"]["days"]:
        hrs = [r for r in fx["wxlog"]["hours"] if r["t"].startswith(d["date"]) and r.get("fc_temp_c") is not None]
        if hrs:
            d.update(fc_hours=len(hrs), fc_tmin_c=min(r["fc_temp_c"] for r in hrs), fc_tmax_c=max(r["fc_temp_c"] for r in hrs),
                     fc_precip_mm=round(d.get("precip_mm", 0) * 0.8, 1), fc_code=d.get("code"), fc_condition=d.get("condition"))

    out = os.path.join(HERE, "fixtures.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(fx, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{out}: {os.path.getsize(out) // 1024} kB, time {fx['time']}, "
          f"{len(next(iter(fx['live']['devices'].values()))['history'])} live points, {len(fx['history']['hours'])} hours")


if __name__ == "__main__":
    main()
