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
  archive <site> --before "YYYY-MM-DD HH:MM" [--apply]
                                        move every record before that site-local time (a test period) to
                                        archive/<site>-before-<time>/, rebuild the alarm log and daily.csv from
                                        the records kept, and refuse older rows from then on (docs/ARCHIVE.md).
                                        Without --apply: only says what it would do. Stop the service first
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
"""

import argparse
import csv
import json
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import registers  # noqa: E402
from alarms import AlarmEngine  # noqa: E402
from firmware import Firmware, FirmwareError, check_image  # noqa: E402
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
        start = store.records_from(site)
        print(f"{site}: {prof.get('name', '')} ({prof.get('timezone', '')})"
              + (f", records from {start} (older ones archived)" if start else ""))
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
    total = dup = bad = early = 0
    start = store.records_from(a.site)
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
            s, d, _, b = store.store_rows(a.site, a.device, header, good)
            total, dup, bad, early = total + s, dup + d, bad + nbad, early + b
            print(f"  {fn}: {s} new, {d} already there, {nbad} bad" + (f", {b} before {start} (archived period)" if b else ""))
    store.event(a.site, a.device, "backfill", {"rows": total, "from": os.path.abspath(a.folder)})
    print(f"backfill done: {total} new row(s), {dup} duplicate(s), {bad} bad row(s)"
          + (f", {early} row(s) before {start} not stored (archived period, docs/ARCHIVE.md)" if early else ""))
    if total:
        print(f"older rows are not in the alarm log yet: run  manage.py alarms {a.site} --rebuild")


# ---------------------------------------------------------------------- archive (docs/ARCHIVE.md)

def service_answers():
    """The ingest service, if it is running: 127.0.0.1 from the VPS or inside its container,
    arkan-monitoring-ingest from a "docker compose run" container. None when nothing answers."""
    port = int(os.environ.get("PORT", "8800"))
    for host in ("127.0.0.1", "arkan-monitoring-ingest"):
        try:
            with socket.create_connection((host, port), timeout=2):
                return f"{host}:{port}"
        except OSError:
            continue
    return None


def _ts_csv(line):
    return line.split(",", 1)[0].strip()


def _ts_live(line):
    try:
        return json.loads(line).get("recv")
    except (ValueError, AttributeError):
        return None


def split_file(src, dst, cut, key, header, apply):
    """Lines of src whose time (key(line), UTC) is before cut go to dst, the others stay in src; a header line
    goes to both. A file with nothing to keep is moved whole. Returns (moved, kept); changes nothing unless apply."""
    moved = kept = 0
    with open(src, encoding="utf-8", newline="") as f:
        if header:
            f.readline()
        for ln in f:
            if ln.strip():
                k = key(ln)
                if k and k < cut:
                    moved += 1
                else:
                    kept += 1
    if not apply or not moved:
        return moved, kept
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not kept:
        os.replace(src, dst)
        return moved, kept
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(src), prefix=".tmp-")
    with open(src, encoding="utf-8", newline="") as f, open(dst, "x", encoding="utf-8", newline="") as old, \
            os.fdopen(fd, "w", encoding="utf-8", newline="") as new:
        if header:
            head = f.readline()
            old.write(head)
            new.write(head)
        for ln in f:
            if not ln.strip():
                continue
            ln = ln if ln.endswith("\n") else ln + "\n"
            k = key(ln)
            (old if k and k < cut else new).write(ln)
        for g in (old, new):
            g.flush()
            os.fsync(g.fileno())
    os.chmod(tmp, 0o640)
    os.chmod(dst, 0o640)
    os.replace(tmp, src)
    return moved, kept


def remove_empty_dirs(top):
    for dirpath, _, _ in sorted(os.walk(top), key=lambda x: -len(x[0])):
        if dirpath != top and not os.listdir(dirpath):
            os.rmdir(dirpath)


def cmd_archive(store, a):
    """Moves every record of a site before a local time (the test period) into a folder of its own."""
    site = a.site
    if not os.path.exists(os.path.join(store.site_dir(site), "site.json")):
        die(f"no site {site}")
    tz = site_offset(store, site)
    local = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            local = datetime.strptime(a.before.strip(), fmt).replace(tzinfo=tz)
            break
        except ValueError:
            continue
    if local is None:
        die(f'--before "{a.before}": expected "YYYY-MM-DD HH:MM", the site\'s local time')
    cut_t = local.astimezone(timezone.utc)
    if cut_t > datetime.now(timezone.utc):
        die(f"{a.before} ({cut_t:%Y-%m-%dT%H:%M:%SZ}) is in the future: the records after it would be refused")
    cut = cut_t.strftime("%Y-%m-%dT%H:%M:%SZ")
    cut_day = cut[:10]
    name = f"{site}-before-{local:%Y-%m-%dT%H%M}"
    arch = os.path.join(store.root, "archive", name)
    if os.path.exists(arch):
        die(f"{arch} exists already: this archive was made. Nothing was changed")
    if a.apply:
        running = service_answers()
        if running:
            die(f"the ingest service answers on {running}: stop it first (docker compose stop ingest), "
                "then use docker compose run --rm ingest python tools/manage.py archive ... --apply")
    dst = lambda p: os.path.join(arch, os.path.relpath(p, store.root))   # noqa: E731
    sd = store.site_dir(site)
    print(f"Archive of {site}: every record before {local:%Y-%m-%d %H:%M} {tz} = {cut}")
    print(f"Into: {arch}")
    if a.apply:
        os.makedirs(arch)
        for p in (store.devices_path(), os.path.join(sd, "site.json")):   # so the tools can read the archive
            os.makedirs(os.path.dirname(dst(p)), exist_ok=True)
            shutil.copy2(p, dst(p))

    devices = set(store.site_devices(site))
    devices |= {x for x in os.listdir(sd) if DEVICE_RE.match(x)
                and (os.path.isdir(os.path.join(sd, x, "raw")) or os.path.isdir(os.path.join(sd, x, "live")))}
    report = {"cut": cut, "local": f"{local:%Y-%m-%d %H:%M} {tz}", "devices": {}}
    for dev in sorted(devices):
        dd = store.device_dir(site, dev)
        rec = {"files_moved": 0, "rows_moved": 0, "rows_kept_cut_day": 0, "first_day": None, "last_day": None,
               "live_moved": 0}
        for day, part, path in store.day_files(site, dev):
            if day > cut_day:
                continue
            moved, kept = split_file(path, dst(path), cut, _ts_csv, True, a.apply)
            if moved:
                rec["rows_moved"] += moved
                rec["first_day"] = rec["first_day"] or day
                rec["last_day"] = day
                rec["files_moved"] += 0 if kept else 1
            if day == cut_day:
                rec["rows_kept_cut_day"] += kept
        live_dir = os.path.join(dd, "live")
        if os.path.isdir(live_dir):
            for fn in sorted(os.listdir(live_dir)):
                if fn.endswith(".jsonl") and fn[:10] <= cut_day:
                    path = os.path.join(live_dir, fn)
                    rec["live_moved"] += split_file(path, dst(path), cut, _ts_live, False, a.apply)[0]
        if a.apply:
            remove_empty_dirs(os.path.join(dd, "raw"))
            for fn in ("events.jsonl", "alarm-state.json"):   # copies: the events stay (firmware page)
                if os.path.exists(os.path.join(dd, fn)):
                    os.makedirs(os.path.dirname(dst(os.path.join(dd, fn))), exist_ok=True)
                    shutil.copy2(os.path.join(dd, fn), dst(os.path.join(dd, fn)))
        report["devices"][dev] = rec
        days = f" ({rec['first_day']} to {rec['last_day']})" if rec["first_day"] else ""
        print(f"  {dev} records: {rec['rows_moved']} row(s) moved{days}, {rec['files_moved']} day file(s) whole; "
              f"{cut_day}: {rec['rows_kept_cut_day']} row(s) from {cut} kept")
        print(f"  {dev} live snapshots (15 s): {rec['live_moved']} moved")

    alarm_moved = alarm_kept = 0
    ad = os.path.join(sd, "alarms")
    if os.path.isdir(ad):
        for fn in sorted(os.listdir(ad)):
            if fn.endswith(".csv") and fn[:4] <= cut[:4]:
                m, k = split_file(os.path.join(ad, fn), dst(os.path.join(ad, fn)), cut, _ts_csv, True, a.apply)
                alarm_moved, alarm_kept = alarm_moved + m, alarm_kept + k
    print(f"  alarm log: {alarm_moved} line(s) moved, {alarm_kept} kept, then rebuilt from the records kept")
    moves = [p for p in (os.path.join(sd, "daily.csv"), os.path.join(store.root, "export", "oed", site))
             if os.path.exists(p)]
    for p in moves:
        print(f"  {os.path.relpath(p, store.root)}: moved" + (", then rebuilt" if p.endswith("daily.csv") else ""))
        if a.apply:
            os.makedirs(os.path.dirname(dst(p)), exist_ok=True)
            os.replace(p, dst(p))
    print(f'  site.json: "records_from": "{cut}": older rows (a logger\'s backlog, an SD card backfill) are '
          "not stored again")
    print("  kept as they are: the logger events, settings and register table, the weather log, devices, firmware")
    if not a.apply:
        print("Nothing was changed. Stop the service (docker compose stop ingest), then run again with --apply.")
        return

    prof_path = os.path.join(sd, "site.json")
    with open(prof_path, encoding="utf-8") as f:
        prof = json.load(f)
    prof["records_from"] = max(cut, str(prof.get("records_from") or ""))
    atomic_write(prof_path, json.dumps(prof, indent=2) + "\n")

    eng = AlarmEngine(store)
    for dev in sorted(devices):
        # Open offline or clock alarms (not replayed from the records) that began before the cut end here:
        # their start line is in the archive. Those that began later stay open.
        st = eng.load_state(site, dev)
        alarms = {k: v for k, v in st.get("alarms", {}).items()
                  if not (v.get("active") and str(v.get("since") or "") < cut)}
        eng.save_state(site, dev, {"alarms": alarms})
    lines = eng.rebuild(site, lambda dev: (row for _, row in read_rows(store, site, dev)))
    print(f"alarm log rebuilt from the records kept: {len(lines)} line(s)")
    if any(p.endswith("daily.csv") for p in moves):
        cmd_daily(store, argparse.Namespace(site=site))
    for dev, rec in report["devices"].items():
        store.event(site, dev, "archive", {"before": cut, "rows": rec["rows_moved"], "to": "archive/" + name})
    with open(os.path.join(arch, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"Records of site {site} before {report['local']} ({cut}), moved here on {iso_now()}\n"
                "by tools/manage.py archive (docs/ARCHIVE.md). Same layout as the data folder: read it with\n"
                f"  python tools/manage.py --data /data/archive/{name} daily {site}   (or export-oed, list)\n"
                f"The site keeps the records from {cut} on; its site.json has \"records_from\": \"{cut}\".\n\n"
                + json.dumps(report, indent=2) + "\n")
    print(f"Done. Archive: {arch}. Start the service again: docker compose start ingest")


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
    p = sub.add_parser("archive"); p.add_argument("site")
    p.add_argument("--before", required=True, help='site-local time, e.g. "2026-11-11 17:00": records before it move')
    p.add_argument("--apply", action="store_true", help="make the changes (without it: only say what it would do)")
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
    a = ap.parse_args()
    store = DataStore(a.data)
    {
        "init": cmd_init, "add-site": cmd_add_site, "add-device": cmd_add_device,
        "rotate-token": cmd_rotate_token, "disable-device": lambda s, x: cmd_enable(s, x, True),
        "enable-device": lambda s, x: cmd_enable(s, x, False), "list": cmd_list, "daily": cmd_daily,
        "export-oed": cmd_export_oed, "backfill": cmd_backfill, "archive": cmd_archive, "publish-fw": cmd_publish_fw,
        "set-config": cmd_set_config, "show-config": cmd_show_config, "alarms": cmd_alarms,
        "set-registers": cmd_set_registers, "show-registers": cmd_show_registers, "weather": cmd_weather,
    }[a.cmd](store, a)


if __name__ == "__main__":
    main()
