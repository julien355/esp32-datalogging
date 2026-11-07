#!/usr/bin/env python3
"""Admin tool for the monitoring data folder. Python 3.9+, standard library only.

Run it on the VPS inside the container (it then uses /data):
    docker compose exec ingest python tools/manage.py <command> ...
or anywhere with --data <folder> (for example a copy of the data folder on a laptop).

Commands:
  init                                  create the folder layout
  add-site <code> --name "Adab hotel" [--tz Asia/Makassar] [--utc-offset 8]
  add-device <site> <device> [--sd-settings FILE --server URL]
                                        register a logger, print its token and setup WiFi password ONCE
  rotate-token <device>                 new token (the old one stops working at once)
  disable-device <device> / enable-device <device>
  list                                  sites, loggers, last record
  daily <site>                          rebuild sites/<site>/daily.csv (local days)
  export-oed <site> [--from D] [--to D] [--all] [--out DIR]
                                        one CSV per value in Open Energy Dashboard upload format
  backfill <site> <device> <folder>     merge an SD card copy (its /data folder) into the site
  publish-fw <file.bin> --version X [--device D]
                                        offer a firmware image to the loggers (OTA)
  set-config <device> key=value ...     settings sent to the logger (value @default = back to default)
  show-config <device>                  settings asked for, and the settings the logger reported
  alarms <site> [--rebuild]             open alarms and the last lines of the alarm log;
                                        --rebuild replays every record (after a backfill or a register change)
"""

import argparse
import csv
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from alarms import AlarmEngine  # noqa: E402
from store import CODE_RE, DEVICE_RE, DataStore, atomic_write, iso_now, token_hash  # noqa: E402


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def site_offset(store, site):
    """Fixed UTC offset of the site (WITA = +8, no daylight saving)."""
    prof = store.site_profile(site)
    tzname = prof.get("timezone")
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tzname)
        except Exception:
            pass
    return timezone(timedelta(hours=float(prof.get("utc_offset_h", 8))))


# ---------------------------------------------------------------------- setup commands

def cmd_init(store, a):
    for d in ("sites", "firmware", "logs", "export"):
        os.makedirs(os.path.join(store.root, d), exist_ok=True)
    if not os.path.exists(store.devices_path()):
        store.save_devices({"devices": {}})
    reg = os.path.join(store.root, "alarm-register.csv")
    if not os.path.exists(reg):
        shutil.copyfile(AlarmEngine(store).default_register, reg)
        print(f"alarm register copied to {reg} (edit it in Excel; changes apply at once)")
    print(f"data folder ready: {store.root}")


def cmd_add_site(store, a):
    if not CODE_RE.match(a.code):
        die("site code: lower case letters, digits and '-', e.g. adab")
    d = store.site_dir(a.code)
    p = os.path.join(d, "site.json")
    if os.path.exists(p):
        die(f"{p} exists already: edit it by hand")
    os.makedirs(d, exist_ok=True)
    prof = {
        "code": a.code,
        "name": a.name or a.code,
        "timezone": a.tz,
        "utc_offset_h": a.utc_offset,
        "created": iso_now(),
        "labels": {
            "EM01_p": "Total power (kW)", "EM01_s": "Apparent power (kVA)", "EM01_pf": "Power factor",
            "EM01_f": "Frequency (Hz)", "EM01_v1": "V L1-N", "EM01_v2": "V L2-N", "EM01_v3": "V L3-N",
            "EM01_i1": "I L1 (A)", "EM01_i2": "I L2 (A)", "EM01_i3": "I L3 (A)", "EM01_e": "Energy counter (kWh)",
            "EM01_v1_min": "V L1-N min", "EM01_p_max": "Peak power (kW)",
            "TH1_t": "Electrical room (C)", "TH1_rh": "Electrical room (%RH)",
            "TH2_t": "Outdoor (C)", "TH2_rh": "Outdoor (%RH)",
        },
        "live": {"refresh_s": 15, "values": ["EM01_p", "EM01_s", "EM01_pf", "EM01_f", "EM01_v1", "EM01_v2",
                                              "EM01_v3", "EM01_i1", "EM01_i2", "EM01_i3",
                                              "TH1_t", "TH1_rh", "TH2_t", "TH2_rh"]},
        "sensors": {"TH1": "electrical room (on the board)", "TH2": "outdoor, beside the panel room"},
        "nominal_v": 230,
        "nominal_hz": 50,
        "contracted_kva": None,
        "rated_a": None,
    }
    atomic_write(p, json.dumps(prof, indent=2) + "\n")
    print(f"site {a.code} created: {p}")


def cmd_add_device(store, a):
    if not DEVICE_RE.match(a.device):
        die("device code: letters, digits, '-' or '_', e.g. LOG-0001")
    if not os.path.exists(os.path.join(store.site_dir(a.site), "site.json")):
        die(f"no site {a.site}: run add-site first")
    data = store.load_devices()
    devs = data.setdefault("devices", {})
    if a.device in devs:
        die(f"{a.device} exists already (site {devs[a.device]['site']}): use rotate-token")
    token = secrets.token_urlsafe(24)
    devs[a.device] = {"site": a.site, "token_sha256": token_hash(token), "added": iso_now(), "fw": None}
    store.save_devices(data)
    os.makedirs(store.device_dir(a.site, a.device), exist_ok=True)
    store.event(a.site, a.device, "device_added")
    portal = secrets.token_urlsafe(9)
    print(f"device {a.device} added to site {a.site}")
    print(f"TOKEN (shown once, keep it secret): {token}")
    print(f"SETUP WIFI PASSWORD for ARKAN-{a.device} (portal_pass, keep it with the token): {portal}")
    if a.sd_settings:
        write_sd_settings(a.sd_settings, a.device, token, a.server, portal)


def write_sd_settings(path, device, token, server, portal):
    lines = [
        "# Copy this file to the SD card as /config/settings.txt, add the WiFi lines,",
        "# insert the card and power the logger: it applies the settings, DELETES this file",
        "# from the card and restarts. Do not leave copies of this file around: it holds the token.",
        f"dev_id={device}",
        f"dev_token={token}",
        f"srv_url={server}",
        f"portal_pass={portal}",
        "# wifi_ssid=",
        "# wifi_pass=",
        "# wifi_ssid2=",
        "# wifi_pass2=",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    print(f"SD card settings file written: {path}")


def cmd_rotate_token(store, a):
    data = store.load_devices()
    info = data.get("devices", {}).get(a.device) or die(f"no device {a.device}")
    token = secrets.token_urlsafe(24)
    info["token_sha256"] = token_hash(token)
    info["token_rotated"] = iso_now()
    store.save_devices(data)
    store.event(info["site"], a.device, "token_rotated")
    print(f"NEW TOKEN for {a.device} (shown once): {token}")
    print("Set it on the logger: console 'set dev_token ...' then 'reboot', or the setup portal.")


def cmd_enable(store, a, disabled):
    data = store.load_devices()
    info = data.get("devices", {}).get(a.device) or die(f"no device {a.device}")
    info["disabled"] = disabled
    store.save_devices(data)
    print(f"{a.device} {'disabled' if disabled else 'enabled'}")


def cmd_list(store, a):
    for site in store.sites():
        prof = store.site_profile(site)
        print(f"{site}: {prof.get('name', '')} ({prof.get('timezone', '')})")
        for dev in store.site_devices(site):
            info = store.load_devices()["devices"][dev]
            flag = " DISABLED" if info.get("disabled") else ""
            print(f"  {dev}: fw {info.get('fw')}, last record {store.last_record(site, dev)}{flag}")


# ---------------------------------------------------------------------- data commands

def read_rows(store, site, device, day_from=None, day_to=None):
    """Yields (utc datetime, dict of column -> text) for every stored row, oldest first."""
    for day, part, path in store.day_files(site, device):
        if (day_from and day < day_from) or (day_to and day > day_to):
            continue
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    t = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                except (KeyError, ValueError):
                    continue
                yield t, row


def num(x):
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def cmd_daily(store, a):
    tz = site_offset(store, a.site)
    days = {}   # (local date, device) -> stats
    for dev in store.site_devices(a.site):
        for t, row in read_rows(store, a.site, dev):
            lt = t.astimezone(tz)
            key = (lt.strftime("%Y-%m-%d"), dev)
            s = days.setdefault(key, {"minutes": 0, "cols": {}})
            s["minutes"] += 1
            for col, val in row.items():
                v = num(val)
                if v is None or col in ("ts", "rssi", "heap_kb", "up_s", "backlog_min", "sd", "boot"):
                    continue
                c = s["cols"].setdefault(col, {"n": 0, "sum": 0.0, "min": v, "max": v, "first": v, "last": v,
                                               "tmax": lt})
                c["n"] += 1
                c["sum"] += v
                c["last"] = v
                c["min"] = min(c["min"], v)
                if v > c["max"]:
                    c["max"], c["tmax"] = v, lt
    out_rows, header = [], ["date", "device", "minutes", "coverage_pct"]
    prev = {}   # (device, column) -> (date, last counter value): the day's kWh runs from the previous day's last reading
    for (day, dev), s in sorted(days.items()):
        r = {"date": day, "device": dev, "minutes": s["minutes"], "coverage_pct": round(s["minutes"] / 14.4, 1)}
        for col, c in sorted(s["cols"].items()):
            if col.endswith("_n"):
                continue
            if col.endswith("_e") or col.endswith("_eq"):          # energy counters
                first = c["first"]
                pday, plast = prev.get((dev, col), (None, None))
                yesterday = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                if pday == yesterday:
                    first = plast
                r[col + "_delta"] = round(c["last"] - first, 2)
                prev[(dev, col)] = (day, c["last"])
            elif col.endswith("_max"):                           # highest 15 s sample of the day
                r[col] = round(c["max"], 3)
                if col.endswith("_p_max") or col.endswith("_s_max"):
                    r[col + "_time"] = c["tmax"].strftime("%H:%M")
            elif col.endswith("_min"):                           # lowest 15 s sample of the day
                r[col] = round(c["min"], 3)
            else:
                r[col + "_mean"] = round(c["sum"] / c["n"], 3)
                if col.endswith("_t") or col.endswith("_rh"):
                    r[col + "_min"] = round(c["min"], 2)
                    r[col + "_max"] = round(c["max"], 2)
        for k in r:
            if k not in header:
                header.append(k)
        out_rows.append(r)
    lines = [",".join(header)]
    for r in out_rows:
        lines.append(",".join(str(r.get(k, "")) for k in header))
    p = os.path.join(store.site_dir(a.site), "daily.csv")
    atomic_write(p, "\n".join(lines) + "\n")
    print(f"{p}: {len(out_rows)} day(s); energy columns end in _e_delta (kWh), local time {tz}")


OED_NAMES = {"e": "energy", "eq": "reactive-energy", "t": "temp", "rh": "hum"}


def oed_meter_name(site, col):
    dev, _, value = col.partition("_")
    return f"{site}-{dev}-{OED_NAMES.get(value, value.replace('_', '-'))}"


def cmd_export_oed(store, a):
    """Open Energy Dashboard CSV upload format: reading,start_timestamp,end_timestamp in local time.
    Energy (_e) is the cumulative counter: upload with cumulative=yes. Others: raw readings."""
    tz = site_offset(store, a.site)
    out_dir = a.out or os.path.join(store.root, "export", "oed", a.site)
    os.makedirs(out_dir, exist_ok=True)
    keep = re.compile(r"^(EM\d+_e|TH\d+_t|TH\d+_rh)$") if not a.all else re.compile(r"^(?!.*_n$)[A-Za-z0-9]+_.+$")
    files = {}
    for dev in store.site_devices(a.site):
        for t, row in read_rows(store, a.site, dev, a.date_from, a.date_to):
            start = t.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            end = (t + timedelta(minutes=1)).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            for col, val in row.items():
                if col in ("ts", "rssi", "heap_kb", "up_s", "backlog_min", "sd", "boot") or not keep.match(col):
                    continue
                if num(val) is None:
                    continue
                name = oed_meter_name(a.site, col)
                if name not in files:
                    f = open(os.path.join(out_dir, name + ".csv"), "w", encoding="utf-8", newline="")
                    f.write("reading,start_timestamp,end_timestamp\n")
                    files[name] = f
                files[name].write(f"{val},{start},{end}\n")
    for f in files.values():
        f.close()
    print(f"{len(files)} file(s) in {out_dir} (header row: yes; *-energy files: cumulative=yes)")


def cmd_backfill(store, a):
    if a.device not in store.site_devices(a.site):
        die(f"{a.device} is not a device of {a.site}")
    total = dup = bad = 0
    for dirpath, _, fns in sorted(os.walk(a.folder)):
        for fn in sorted(fns):
            if not re.match(r"^\d{4}-\d{2}-\d{2}(_\d+)?\.csv$", fn):
                continue
            with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as f:
                text = f.read()
            try:
                header, cols, good, nbad = store.parse_csv(text)
            except ValueError as e:
                print(f"  {fn}: skipped ({e})")
                continue
            s, d, _ = store.store_rows(a.site, a.device, header, good)
            total, dup, bad = total + s, dup + d, bad + nbad
            print(f"  {fn}: {s} new, {d} already there, {nbad} bad")
    store.event(a.site, a.device, "backfill", {"rows": total, "from": os.path.abspath(a.folder)})
    print(f"backfill done: {total} new row(s), {dup} duplicate(s), {bad} bad row(s)")
    if total:
        print(f"older rows are not in the alarm log yet: run  manage.py alarms {a.site} --rebuild")


def cmd_publish_fw(store, a):
    if not re.match(r"^[0-9A-Za-z._-]{1,20}$", a.version):
        die("bad version")
    fw_dir = os.path.join(store.root, "firmware")
    os.makedirs(fw_dir, exist_ok=True)
    name = f"logger-{a.version}.bin"
    dst = os.path.join(fw_dir, name)
    shutil.copyfile(a.file, dst)
    md5 = hashlib.md5(open(dst, "rb").read()).hexdigest()
    p = os.path.join(fw_dir, "manifest.json")
    man = json.load(open(p)) if os.path.exists(p) else {}
    man[a.device or "default"] = {"version": a.version, "file": name, "md5": md5,
                                  "size": os.path.getsize(dst), "published": iso_now()}
    atomic_write(p, json.dumps(man, indent=2) + "\n")
    print(f"{name} offered to {a.device or 'every logger'} (md5 {md5}). Loggers with ota_on=1 take it at their next check.")


def device_site(store, device):
    info = store.load_devices().get("devices", {}).get(device) or die(f"no device {device}")
    return info["site"]


def cmd_set_config(store, a):
    site = device_site(store, a.device)
    changes = {}
    for kv in a.pairs:
        if "=" not in kv:
            die(f"expected key=value, got {kv!r}")
        k, v = kv.split("=", 1)
        changes[k.strip()] = v.strip()
    rep = os.path.join(store.device_dir(site, a.device), "settings-reported.json")
    if os.path.exists(rep):
        known = json.load(open(rep)).get("settings", {})
        for k in changes:
            if k not in known:
                die(f"{k}: not a setting of this logger (see show-config)")
    blocked = {"dev_id", "dev_token", "srv_url", "tls_verify", "wifi_ssid", "wifi_pass", "wifi_ssid2", "wifi_pass2",
               "portal_pass"}
    for k in changes:
        if k in blocked:
            die(f"{k} cannot be changed remotely (it could cut the logger off): use the setup portal on site")
    ver = store.set_config(site, a.device, changes)
    print(f"settings version {ver} for {a.device}: the logger takes it at its next check (15 min, or console 'config')")
    print("it restarts if anything changed; check with show-config")


def cmd_show_config(store, a):
    site = device_site(store, a.device)
    cfg = store.get_config(site, a.device)
    print("asked by the platform:", json.dumps(cfg, indent=2) if cfg else "nothing")
    rep = os.path.join(store.device_dir(site, a.device), "settings-reported.json")
    if os.path.exists(rep):
        r = json.load(open(rep))
        print(f"reported by the logger at {r.get('received')}: fw {r.get('fw')}, settings version "
              f"{r.get('cfg_version')}, boot {r.get('boot')}, TH1 chip {r.get('th1_chip')}")
        for k, v in sorted(r.get("settings", {}).items()):
            print(f"  {k} = {v}")
    else:
        print("the logger has not reported its settings yet")


def cmd_alarms(store, a):
    eng = AlarmEngine(store)
    if a.rebuild:
        lines = eng.rebuild(a.site, lambda dev: (row for _, row in read_rows(store, a.site, dev)))
        print(f"alarm log rebuilt: {len(lines)} line(s)")
    for o in eng.open_alarms(a.site):
        print(f"OPEN {o['severity']:8} {o['id']} {o['name']} on {o['device']} since {o['since']} (worst {o['worst']})")
    d = os.path.join(store.site_dir(a.site), "alarms")
    files = sorted(f for f in os.listdir(d) if f.endswith(".csv")) if os.path.isdir(d) else []
    if files:
        lines = open(os.path.join(d, files[-1]), encoding="utf-8").read().splitlines()
        print(f"last lines of {os.path.join(d, files[-1])}:")
        for ln in lines[-a.lines:]:
            print("  " + ln)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.environ.get("DATA_DIR", "/data"), help="data folder (default $DATA_DIR or /data)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("add-site"); p.add_argument("code"); p.add_argument("--name")
    p.add_argument("--tz", default="Asia/Makassar"); p.add_argument("--utc-offset", type=float, default=8)
    p = sub.add_parser("add-device"); p.add_argument("site"); p.add_argument("device")
    p.add_argument("--sd-settings", help="also write a settings.txt for the logger's SD card")
    p.add_argument("--server", default="https://arkan-monitoring.duckdns.org")
    p = sub.add_parser("rotate-token"); p.add_argument("device")
    p = sub.add_parser("disable-device"); p.add_argument("device")
    p = sub.add_parser("enable-device"); p.add_argument("device")
    sub.add_parser("list")
    p = sub.add_parser("daily"); p.add_argument("site")
    p = sub.add_parser("export-oed"); p.add_argument("site")
    p.add_argument("--from", dest="date_from"); p.add_argument("--to", dest="date_to")
    p.add_argument("--all", action="store_true", help="every value, not only energy, temperature, humidity")
    p.add_argument("--out")
    p = sub.add_parser("backfill"); p.add_argument("site"); p.add_argument("device"); p.add_argument("folder")
    p = sub.add_parser("publish-fw"); p.add_argument("file"); p.add_argument("--version", required=True)
    p.add_argument("--device")
    p = sub.add_parser("set-config"); p.add_argument("device"); p.add_argument("pairs", nargs="+")
    p = sub.add_parser("show-config"); p.add_argument("device")
    p = sub.add_parser("alarms"); p.add_argument("site"); p.add_argument("--rebuild", action="store_true")
    p.add_argument("--lines", type=int, default=20)
    a = ap.parse_args()
    store = DataStore(a.data)
    {
        "init": cmd_init, "add-site": cmd_add_site, "add-device": cmd_add_device,
        "rotate-token": cmd_rotate_token, "disable-device": lambda s, x: cmd_enable(s, x, True),
        "enable-device": lambda s, x: cmd_enable(s, x, False), "list": cmd_list, "daily": cmd_daily,
        "export-oed": cmd_export_oed, "backfill": cmd_backfill, "publish-fw": cmd_publish_fw,
        "set-config": cmd_set_config, "show-config": cmd_show_config, "alarms": cmd_alarms,
    }[a.cmd](store, a)


if __name__ == "__main__":
    main()
