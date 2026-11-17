#!/usr/bin/env python3
"""Admin tool for the monitoring data folder. Python 3.9+, standard library only.

Run it on the VPS inside the container (it then uses /data):
    docker compose exec ingest python tools/manage.py <command> ...
or anywhere with --data <folder> (for example a copy of the data folder on a laptop).

Commands:
  init                                  create the folder layout
  add-site <code> --name "Adab hotel" --contracted-kva 82.5 --rated-a 200 [--nominal-v 230]
                                        [--tz Asia/Makassar] [--utc-offset 8] [--lat -8.5 --lon 115.2]
  add-device <site> <device> [--sd-settings FILE --server URL]
                                        register a logger, print its token and setup WiFi password ONCE
  rotate-token <device>                 new token (the old one stops working at once)
  disable-device <device> / enable-device <device>
  list                                  sites, loggers, last record
  daily <site>                          rebuild sites/<site>/daily.csv (local days)
  export-oed <site> [--from D] [--to D] [--all] [--out DIR]
                                        one CSV per value in Open Energy Dashboard upload format
  backfill <site> <device> <folder>     merge an SD card copy (its /data folder) into the site
  publish-fw <file.bin> [--version X] [--device D] [--force]
                                        offer a firmware image to the loggers (OTA; only to older versions).
                                        Same as "Firmware update" in the site page menu (docs/OTA.md)
  set-config <device> key=value ... [--force]
                                        settings sent to the logger (value @default = back to default)
  show-config <device>                  settings asked for, and the settings the logger reported
  set-registers <device> <file.csv> [--comment TEXT] | --builtin
                                        meter register table sent to the logger (same as the page /live/<site>/register)
  show-registers <device>               register table sent, table the logger reported, history
  alarms <site> [--rebuild]             open alarms and the last lines of the alarm log;
                                        --rebuild replays every record (after a backfill or a register change)
  weather <site> [--lat L --lon L] [--dayahead-hour 18] [--model M] [--off] [--no-fetch]
                                        weather forecast and log of the site (Open-Meteo, no key, app/weather.py):
                                        set or change the place, fetch once now, show today, tomorrow and the log
  manual-meter <site> [<id> --name N --kind water|power|gas|other --unit m3 --decimals 3 --due-h 26 --long TEXT
                      --where TEXT --compare EM01 | <id> --remove]
                                        meters read by hand (site.json manual_meters, app/manual.py): without an id,
                                        list them with their last reading; with an id, add or change one, or remove it
                                        (its readings file is kept). Their pages: Meter readings on the site page
  import-readings <site> <meter> <file.csv | -> [--user NAME] [--dry-run]
  site-set <site> key=value ...         change fields of site.json (no restart): meter_checked=2026-11-20 (date of the
                                        on-site register check, shown on Current & balance), i_imbalance_floor_a=25
                                        (A10 counted from this mean current), contracted_kva, contract_v_ln, rated_a,
                                        nominal_v, name. An empty value removes the field (back to its default)
  alarm-register [--add]                lines of the default register (docs/alarms/alarms.csv, in the image) missing
                                        from the register in use: listed, or appended with --add (the lines already
                                        there, edited or not, are never changed)
                                        past readings from a CSV (date,time,value[,note], hotel time, a header line
                                        allowed), e.g. the paper round sheet: every line is checked first, nothing
                                        is written if one is refused
"""

import argparse
import csv
import io
import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import registers  # noqa: E402
from alarms import AlarmEngine  # noqa: E402
from firmware import Firmware, FirmwareError, check_image  # noqa: E402
import manual  # noqa: E402
from weather import Weather  # noqa: E402
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
        "grid": "PLN 3-phase 4-wire, 230/400 V nominal (SNI), contracts on 220/380 V",
        "nominal_v": a.nominal_v,
        "nominal_hz": 50,
        "contracted_kva": a.contracted_kva,
        "contract_v_ln": 220,
        "rated_a": a.rated_a,
    }
    if a.lat is not None and a.lon is not None:
        prof["weather"] = {"lat": a.lat, "lon": a.lon, "dayahead_hour": 18, "model": "best_match"}
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


SENSOR_COL = re.compile(r"^TH\d+_(t|rh)$")


def alarm_counts(store, site):
    """(local date, device) -> {"dips": n, "swells": n, "power_interruptions": n, "alarms_started": n}"""
    out = {}
    d = os.path.join(store.site_dir(site), "alarms")
    if not os.path.isdir(d):
        return out
    names = {"A26": "dips", "A27": "swells", "A02": "power_interruptions"}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".csv"):
            continue
        with open(os.path.join(d, fn), encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                key = (r["local_time"][:10], r["device"])
                c = out.setdefault(key, {"dips": 0, "swells": 0, "power_interruptions": 0, "alarms_started": 0})
                if r["state"] == "start":
                    c["alarms_started"] += 1
                if r["id"] in names and r["state"] in ("start", "event"):
                    c[names[r["id"]]] += 1
    return out


def cmd_daily(store, a):
    tz = site_offset(store, a.site)
    days = {}   # (local date, device) -> stats
    for dev in store.site_devices(a.site):
        for t, row in read_rows(store, a.site, dev):
            lt = t.astimezone(tz)
            key = (lt.strftime("%Y-%m-%d"), dev)
            # Sensor values are 5-minute means that END at the row's time: the 00:00 row belongs to the day before.
            skey = ((t - timedelta(seconds=1)).astimezone(tz).strftime("%Y-%m-%d"), dev)
            s = days.setdefault(key, {"minutes": 0, "cols": {}})
            s["minutes"] += 1
            for col, val in row.items():
                v = num(val)
                if v is None or col in ("ts", "rssi", "heap_kb", "up_s", "backlog_min", "sd", "boot"):
                    continue
                target = days.setdefault(skey, {"minutes": 0, "cols": {}}) if SENSOR_COL.match(col) else s
                c = target["cols"].setdefault(col, {"n": 0, "sum": 0.0, "min": v, "max": v, "first": v, "last": v,
                                               "tmax": lt})
                c["n"] += 1
                c["sum"] += v
                c["last"] = v
                c["min"] = min(c["min"], v)
                if v > c["max"]:
                    c["max"], c["tmax"] = v, lt
    counts = alarm_counts(store, a.site)
    out_rows, header = [], ["date", "device", "minutes", "coverage_pct", "dips", "swells", "power_interruptions",
                            "alarms_started"]
    prev = {}   # (device, column) -> (date, last counter value): the day's kWh runs from the previous day's last reading
    for (day, dev), s in sorted(days.items()):
        r = {"date": day, "device": dev, "minutes": s["minutes"], "coverage_pct": round(s["minutes"] / 14.4, 1)}
        r.update(counts.get((day, dev), {"dips": 0, "swells": 0, "power_interruptions": 0, "alarms_started": 0}))
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
    print(f"{p}: {len(out_rows)} day(s); energy columns end in _e_delta (kWh), local time {tz}; "
          f"dips, swells, power_interruptions counted from the alarm log")


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
    last_sensor = {}   # (device, column) -> time of the previous sensor value
    last_end = {}      # (device, column) -> end of the previous energy reading
    for dev in store.site_devices(a.site):
        for t, row in read_rows(store, a.site, dev, a.date_from, a.date_to):
            start = t.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            end = (t + timedelta(minutes=1)).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            for col, val in row.items():
                if col in ("ts", "rssi", "heap_kb", "up_s", "backlog_min", "sd", "boot") or not keep.match(col):
                    continue
                if num(val) is None:
                    continue
                if SENSOR_COL.match(col):   # a 5-minute mean ending at the row's time
                    p_t = last_sensor.get((dev, col))
                    w_start = p_t if p_t and t - p_t <= timedelta(minutes=60) else t - timedelta(minutes=5)
                    last_sensor[(dev, col)] = t
                    start_s = w_start.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
                    end_s = t.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
                elif col.endswith("_e") or col.endswith("_eq"):
                    # Cumulative counters: each reading starts where the previous one ended, so a missing minute
                    # does not leave a hole in which OED would drop the energy (its default Reading Gap is 0).
                    # After a gap of more than 60 min, a new chain starts at the row's own minute.
                    p_end = last_end.get((dev, col))
                    w_start = p_end if p_end and t - p_end <= timedelta(minutes=60) else t
                    last_end[(dev, col)] = t + timedelta(minutes=1)
                    start_s = w_start.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
                    end_s = end
                else:
                    start_s, end_s = start, end
                name = oed_meter_name(a.site, col)
                if name not in files:
                    f = open(os.path.join(out_dir, name + ".csv"), "w", encoding="utf-8", newline="")
                    f.write("reading,start_timestamp,end_timestamp\n")
                    files[name] = f
                files[name].write(f"{val},{start_s},{end_s}\n")
    for f in files.values():
        f.close()
    print(f"{len(files)} file(s) in {out_dir} (upload with headerRow=yes, gzip=no; *-energy files: cumulative=yes)")


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
    fw = Firmware(store)
    try:
        with open(a.file, "rb") as f:
            data = f.read()
        info = check_image(data)
        if a.version and a.version != info["version"]:
            die(f"the file is version {info['version']} (FW_VERSION in the build), not {a.version}")
        _, name = fw.store_image(data)
        target = a.device or "default"
        fw.offer(target, name, force=a.force, by="manage.py", source="manage.py " + os.path.basename(a.file))
    except (FirmwareError, OSError) as e:
        die(str(e))
    print(f"{name} ({info['env']} build) offered to {a.device or 'every logger'}. Loggers with ota_on=1 take it "
          "within a minute if they are online (live hint), else at their next check (6 h, or console 'ota').")


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
    elif not a.force:
        die("the logger has not reported its settings yet, so the keys cannot be checked: "
            "wait for its first connection (show-config), or add --force if you are sure of the key names")
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


def cmd_set_registers(store, a):
    site = device_site(store, a.device)
    if a.builtin == bool(a.file):
        die("give a file, or --builtin (not both)")
    if a.builtin:
        ver = store.set_registers(site, a.device, builtin=True, by="manage.py", comment=a.comment)
    else:
        text = open(a.file, encoding="utf-8-sig").read()
        rows, errors, warnings = registers.parse(text)
        for w in warnings:
            print("warning: " + w)
        if errors:
            die("table refused:\n  " + "\n  ".join(errors))
        ver = store.set_registers(site, a.device, registers.to_csv(rows), by="manage.py", comment=a.comment)
    print(f"register table version {ver} for {a.device}: the logger takes it at its next check "
          "(15 min, or console 'config'), writes /config/registers.csv and restarts; check with show-registers")


def cmd_show_registers(store, a):
    site = device_site(store, a.device)
    want = store.get_registers(site, a.device)
    if want:
        what = "back to the built-in table" if want.get("builtin") else "table below"
        print(f"sent: version {want['version']} at {want.get('updated')} by {want.get('by') or '-'}: {what}")
        if want.get("csv"):
            print(want["csv"], end="")
    else:
        print("sent: nothing (the logger uses its own table)")
    rep = store.get_report(site, a.device)
    if rep and "reg_version" in rep:
        print(f"\nreported by the logger at {rep.get('received')}: version {rep.get('reg_version')}, "
              f"source {rep.get('reg_source')}" + (f", REFUSED version {rep.get('reg_refused')}: {rep.get('reg_error')}"
                                                   if rep.get("reg_refused") else ""))
        print(rep.get("registers", ""), end="")
    elif rep:
        print(f"\nthe logger (fw {rep.get('fw')}) does not report its register table: firmware 0.4.0 or later needed")
    else:
        print("\nthe logger has not reported yet")
    hist = store.registers_history(site, a.device)
    if hist:
        print("\nhistory:")
        for h in hist:
            print(f"  v{h['version']} {h.get('updated')} {h.get('by') or '-'}: "
                  f"{'built-in' if h.get('builtin') else 'table'} {h.get('comment') or ''}")


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


def cmd_weather(store, a):
    p = os.path.join(store.site_dir(a.site), "site.json")
    if not os.path.exists(p):
        die(f"no site {a.site}")
    prof = store.site_profile(a.site)
    w = dict(prof.get("weather") or {})
    changed = False
    if (a.lat is None) != (a.lon is None):
        die("give both --lat and --lon (decimal degrees, south and west negative, e.g. --lat -8.5069 --lon 115.2625)")
    if a.lat is not None:
        if not (-90 <= a.lat <= 90 and -180 <= a.lon <= 180):
            die("latitude -90..90, longitude -180..180")
        w.update(lat=a.lat, lon=a.lon, enabled=True)
        w.setdefault("dayahead_hour", 18)
        w.setdefault("model", "best_match")
        changed = True
    if a.dayahead_hour is not None:
        if not 0 <= a.dayahead_hour <= 23:
            die("--dayahead-hour 0..23 (hotel time)")
        w["dayahead_hour"] = a.dayahead_hour
        changed = True
    if a.model:
        w["model"] = a.model
        changed = True
    if a.off:
        w["enabled"] = False
        changed = True
    if changed:
        prof["weather"] = w
        atomic_write(p, json.dumps(prof, indent=2) + "\n")
        print(f"site.json: weather {json.dumps(w)}")
    wx = Weather(store)
    if not wx.settings(a.site):
        print("weather is off for this site" + ("" if w.get("lat") is not None else ": set --lat and --lon"))
        return
    if not a.no_fetch:
        try:
            r = wx.update(a.site)
        except Exception as e:
            die(f"fetch failed: {e}")
        print(f"fetched {r['hours']} hours; logged {r['actual']} actual hour(s), {r['dayahead']} day-ahead hour(s)")
    v = wx.view(a.site)
    if v.get("current"):
        c = v["current"]
        print(f"now ({c['t']}): {c['temp_c']} C, {c['rh_pct']} %RH, {c['condition']}, wind {c['wind_kmh']} km/h")
    for d in (v.get("days") or []):
        if d["date"] >= v["now"][:10]:
            print(f"{d['date']}: {d['condition']:<22} {d['tmin_c']}-{d['tmax_c']} C, rain {d['precip_mm']} mm "
                  f"({d['precip_prob_pct']} %), sun {d['sun_kwh_m2']} kWh/m2, {d['sunrise']}-{d['sunset']}")
    lg = wx.log(a.site, 7)
    print(f"weather log, last 7 days: {len(lg['hours'])} hour(s), {sum(1 for h in lg['hours'] if h['fc_temp_c'] is not None)} "
          f"with a day-ahead forecast. Files: {wx.dir(a.site)}")


UNITS = {"m3": "m³", "kwh": "kWh", "l": "L", "mwh": "MWh"}


def cmd_manual_meter(store, a):
    p = os.path.join(store.site_dir(a.site), "site.json")
    if not os.path.exists(p):
        die(f"no site {a.site}")
    prof = store.site_profile(a.site)
    if not a.id:
        ms = manual.meters(prof)
        if not ms:
            print(f"no meter read by hand on {a.site}: add one with manual-meter {a.site} water --name Water --kind water --unit m3")
        now = datetime.now(timezone.utc)
        for m in ms:
            rs = manual.readings(store, a.site, m["id"])
            off = manual.history._offset(store, a.site)
            last = (f"last reading {manual.fv(rs[-1]['value'], m['decimals'])} {m['unit']} at {manual.loc(rs[-1]['t'], off)} "
                    f"by {rs[-1]['user']}" + (" (due)" if (now - rs[-1]["t"]).total_seconds() > m["due_h"] * 3600 else "")
                    if rs else "no reading yet")
            print(f"{m['id']:<10} {m['name']} ({m['kind']}, {m['unit']}, {m['decimals']} decimals, due after {m['due_h']:g} h): "
                  f"{len(rs)} reading(s), {last}. File: {manual.path(store, a.site, m['id'])}")
        return
    if not manual.ID_RE.match(a.id) or a.id in manual.RESERVED:
        die(f"meter id: lower case letters, digits and '-', starting with a letter, not one of the page names "
            f"({', '.join(sorted(manual.RESERVED))}); e.g. water, pm2")
    lst = [dict(m) for m in (prof.get("manual_meters") or []) if isinstance(m, dict)]
    cur = next((m for m in lst if m.get("id") == a.id), None)
    if a.remove:
        if not cur:
            die(f"no meter {a.id} on {a.site}")
        prof["manual_meters"] = [m for m in lst if m.get("id") != a.id]
        atomic_write(p, json.dumps(prof, indent=2, ensure_ascii=False) + "\n")
        print(f"meter {a.id} removed from site.json; its readings stay in {manual.path(store, a.site, a.id)}")
        return
    new = cur is None
    m = cur or {"id": a.id}
    if a.kind:
        if a.kind not in manual.KINDS:
            die(f"--kind: one of {', '.join(manual.KINDS)}")
        m["kind"] = a.kind
    m.setdefault("kind", "water" if a.id.startswith("water") else "other")
    for k in ("name", "long", "where", "compare"):
        v = getattr(a, k)
        if v is not None:
            if v:
                m[k] = v
            else:
                m.pop(k, None)
    if a.unit:
        m["unit"] = UNITS.get(a.unit.lower(), a.unit)
    if a.decimals is not None:
        if not 0 <= a.decimals <= 4:
            die("--decimals 0..4: the decimals the meter shows (3 for a water meter in m³ with litres)")
        m["decimals"] = a.decimals
    if a.due_h is not None:
        if a.due_h <= 0:
            die("--due-h: hours after the last reading before it shows as due, e.g. 26")
        m["due_h"] = a.due_h
    m.setdefault("name", a.id.capitalize())
    m.setdefault("unit", "m³" if m["kind"] == "water" else "kWh")
    m.setdefault("decimals", 3 if m["kind"] == "water" else 1)
    m.setdefault("due_h", 26)
    if new:
        lst.append(m)
    prof["manual_meters"] = lst
    atomic_write(p, json.dumps(prof, indent=2, ensure_ascii=False) + "\n")
    print(f"site.json: meter {'added' if new else 'changed'}: {json.dumps(m, ensure_ascii=False)}")
    print(f"page: /live/{a.site}/#{a.id} (menu Meter readings), readings entered at /live/{a.site}/#readings")


def cmd_import_readings(store, a):
    prof = store.site_profile(a.site)
    m = manual.meter(prof, a.meter)
    if not m:
        die(f"no meter {a.meter} read by hand on {a.site} (manual-meter {a.site} to list them)")
    off = manual.history._offset(store, a.site)
    rows = []
    if a.file == "-":                     # from stdin: docker compose exec -T ingest ... - < file.csv (the container is read only)
        text = sys.stdin.buffer.read().decode("utf-8-sig")
    else:
        with open(a.file, encoding="utf-8-sig", newline="") as f:
            text = f.read()
    delim = ";" if text[:2048].count(";") > text[:2048].count(",") else ","
    for n, r in enumerate(csv.reader(io.StringIO(text), delimiter=delim), 1):
        if not r or not "".join(r).strip():
            continue
        if n == 1 and not re.match(r"^\s*\d{4}-\d{2}-\d{2}", r[0]):
            continue                          # header line
        if len(r) < 3:
            die(f"line {n}: date,time,value[,note] expected, got {r}")
        t = manual.local_to_utc(f"{r[0].strip()} {r[1].strip()[:5]}", off)
        if t is None:
            die(f"line {n}: date YYYY-MM-DD and time HH:MM (hotel time) expected, got {r[0]!r} {r[1]!r}")
        rows.append((t, n, r[2].strip(), r[3].strip() if len(r) > 3 else ""))
    rows.sort()
    now = datetime.now(timezone.utc)
    have = manual.readings(store, a.site, a.meter)
    sim, errors = list(have), []
    for t, n, v, note in rows:          # every line checked against the readings and the lines before it
        c = manual.check(m, sorted(sim, key=lambda x: x["t"]), t, v, off, now)
        if c.get("empty") or not c["ok"]:
            errors.append(f"line {n} ({manual.loc(t, off)}, {v}): {'no figure' if c.get('empty') else c['text']}")
            continue
        sim.append({"id": f"line{n}", "t": t, "value": c["v"], "reset": False})
    if errors:
        print("\n".join(errors), file=sys.stderr)
        die(f"{len(errors)} line(s) refused: nothing imported")
    print(f"{len(rows)} reading(s) checked for {a.meter} on {a.site}"
          + (f", from {manual.loc(rows[0][0], off)} to {manual.loc(rows[-1][0], off)}" if rows else ""))
    if a.dry_run or not rows:
        return
    for t, n, v, note in rows:
        code, res = manual.add(store, a.site, a.meter, {"time": manual.loc(t, off), "value": v, "note": note},
                               a.user, now=now, source="import")
        if code != 200:
            die(f"line {n}: {res['error']} (the lines before it are imported)")
    print(f"imported as {a.user}: {manual.path(store, a.site, a.meter)}")


SITE_FIELDS = {"meter_checked": "date", "i_imbalance_floor_a": float, "contracted_kva": float, "contract_v_ln": float,
               "rated_a": float, "nominal_v": float, "name": str}


def cmd_site_set(store, a):
    p = os.path.join(store.site_dir(a.site), "site.json")
    if not os.path.exists(p):
        die(f"no site {a.site}")
    prof = store.site_profile(a.site)
    for pair in a.pairs:
        k, eq, v = pair.partition("=")
        if not eq or k not in SITE_FIELDS:
            die(f"{pair}: key=value, key one of {', '.join(SITE_FIELDS)}")
        kind = SITE_FIELDS[k]
        if v == "":
            prof.pop(k, None)
            print(f"{k} removed")
            continue
        try:
            if kind == "date":
                datetime.strptime(v, "%Y-%m-%d")
            elif kind is float:
                v = float(v)
                if v < 0:
                    raise ValueError
        except ValueError:
            die(f"{k}: {'a date YYYY-MM-DD' if kind == 'date' else 'a number, 0 or more'}, not {v!r}")
        prof[k] = v
        print(f"{k} = {v}")
    atomic_write(p, json.dumps(prof, indent=2, ensure_ascii=False) + "\n")
    print(f"saved {p} (read at each request: no restart)")


def cmd_alarm_register(store, a):
    eng = AlarmEngine(store)
    used = os.path.join(store.root, "alarm-register.csv")
    if not os.path.exists(used):
        die(f"no register in use at {used}: run init")
    have = {r["id"] for r in eng._read_register(used)}
    with open(eng.default_register, encoding="utf-8-sig", newline="") as f:
        lines = f.read().splitlines()
    new = [ln for ln in lines[1:] if ln.strip() and next(csv.reader([ln]))[0] not in have]
    if not new:
        print(f"{used}: every line of the default register is there")
        return
    for ln in new:
        print(("added: " if a.add else "missing: ") + ln)
    if not a.add:
        print(f"{len(new)} line(s) missing from {used}: add them with --add")
        return
    shutil.copyfile(used, used + ".bak")
    with open(used, encoding="utf-8-sig", newline="") as f:
        cur = f.read()
    with open(used, "a", encoding="utf-8", newline="") as f:
        f.write(("" if cur.endswith("\n") else "\n") + "\n".join(new) + "\n")
    print(f"{len(new)} line(s) appended to {used} (the previous file: alarm-register.csv.bak); they apply at the next record")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.environ.get("DATA_DIR", "/data"), help="data folder (default $DATA_DIR or /data)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("add-site"); p.add_argument("code"); p.add_argument("--name")
    p.add_argument("--tz", default="Asia/Makassar"); p.add_argument("--utc-offset", type=float, default=8)
    p.add_argument("--contracted-kva", type=float, help="PLN contract, e.g. 82.5 (A08, A37)")
    p.add_argument("--rated-a", type=float, help="main breaker or CT rating in A, e.g. 200 (A29)")
    p.add_argument("--nominal-v", type=float, default=230, help="nominal phase voltage L-N")
    p.add_argument("--lat", type=float, help="latitude of the site for the weather forecast, e.g. -8.5069")
    p.add_argument("--lon", type=float, help="longitude of the site, e.g. 115.2625")
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
    p = sub.add_parser("publish-fw"); p.add_argument("file")
    p.add_argument("--version", help="optional: checked against the version written in the file")
    p.add_argument("--device")
    p.add_argument("--force", action="store_true",
                   help="offer it even to a logger with a newer version (step back) or another build variant")
    p = sub.add_parser("set-config"); p.add_argument("device"); p.add_argument("pairs", nargs="+")
    p.add_argument("--force", action="store_true", help="accept keys before the logger has reported its settings")
    p = sub.add_parser("show-config"); p.add_argument("device")
    p = sub.add_parser("set-registers"); p.add_argument("device"); p.add_argument("file", nargs="?")
    p.add_argument("--builtin", action="store_true", help="the logger deletes its file and uses the firmware's table")
    p.add_argument("--comment", default="")
    p = sub.add_parser("show-registers"); p.add_argument("device")
    p = sub.add_parser("alarms"); p.add_argument("site"); p.add_argument("--rebuild", action="store_true")
    p.add_argument("--lines", type=int, default=20)
    p = sub.add_parser("weather"); p.add_argument("site")
    p.add_argument("--lat", type=float); p.add_argument("--lon", type=float)
    p.add_argument("--dayahead-hour", type=int, help="hotel hour at which tomorrow's forecast is logged (default 18)")
    p.add_argument("--model", help="Open-Meteo model, default best_match (e.g. ecmwf_ifs025, gfs_seamless)")
    p.add_argument("--off", action="store_true", help="stop fetching for this site (the logs are kept)")
    p.add_argument("--no-fetch", action="store_true")
    p = sub.add_parser("manual-meter"); p.add_argument("site"); p.add_argument("id", nargs="?")
    p.add_argument("--name", help="menu name, e.g. Water"); p.add_argument("--long", help="page title, e.g. 'Water, PDAM main meter'")
    p.add_argument("--kind", help="water, power, gas or other"); p.add_argument("--unit", help="m3, kWh, ...")
    p.add_argument("--decimals", type=int, help="decimals the meter shows (water in m³ with litres: 3)")
    p.add_argument("--due-h", type=float, help="hours after the last reading before it shows as due (26)")
    p.add_argument("--where", help="where the meter is, shown on the page"); p.add_argument("--compare", help="main meter to compare with, e.g. EM01")
    p.add_argument("--remove", action="store_true")
    p = sub.add_parser("import-readings"); p.add_argument("site"); p.add_argument("meter"); p.add_argument("file")
    p.add_argument("--user", default="import", help="name kept with each reading (default import)")
    p.add_argument("--dry-run", action="store_true", help="check the lines only")
    p = sub.add_parser("site-set"); p.add_argument("site"); p.add_argument("pairs", nargs="+")
    p = sub.add_parser("alarm-register"); p.add_argument("--add", action="store_true", help="append the missing lines")
    a = ap.parse_args()
    store = DataStore(a.data)
    {
        "init": cmd_init, "add-site": cmd_add_site, "add-device": cmd_add_device,
        "rotate-token": cmd_rotate_token, "disable-device": lambda s, x: cmd_enable(s, x, True),
        "enable-device": lambda s, x: cmd_enable(s, x, False), "list": cmd_list, "daily": cmd_daily,
        "export-oed": cmd_export_oed, "backfill": cmd_backfill, "publish-fw": cmd_publish_fw,
        "set-config": cmd_set_config, "show-config": cmd_show_config, "alarms": cmd_alarms,
        "set-registers": cmd_set_registers, "show-registers": cmd_show_registers, "weather": cmd_weather,
        "manual-meter": cmd_manual_meter, "import-readings": cmd_import_readings,
        "site-set": cmd_site_set, "alarm-register": cmd_alarm_register,
    }[a.cmd](store, a)


if __name__ == "__main__":
    main()
