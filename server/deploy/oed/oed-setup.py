#!/usr/bin/env python3
"""Set up one site in Open Energy Dashboard (OED v1.0.0) through its API, on the VPS loopback.

Does, in this order, what tutorial 3 A.11, C.2 and B.2 to B.6 describe for the browser:
  site settings (title, Line, English, Asia/Makassar), Celsius displayable, our units and
  conversions, the meters of the site, the site group and the group "All sites", and
  optionally the CSV user. Safe to run again: what already exists is left as it is.

Run on hermes-vps as user ai (Python 3 standard library only, no sudo):
  python3 /opt/arkan-monitoring/server/deploy/oed/oed-setup.py adab --admin <oed-admin-email>
  python3 .../oed-setup.py adab --admin <email> --gps=-8.65,115.13 --electrical \
      --csv-user <csv-user-email> --csv-password-file /home/ai/.oed-csv-password

The admin password is asked without echo (or read from --admin-password-file).
Talks to http://127.0.0.1:8810 (OED web, loopback only), never through Caddy.
Tested on OED v1.0.0 (commit 0a615845fcb7c0e43a6cb8db3b4468648d5f8fab).
Tutorial: docs/tutorials/3-OPEN-ENERGY-DASHBOARD.md
"""

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request

# Our units (tutorial B.3). typeOfUnit "meter" = what a meter collects in (never graphed);
# "unit" = what people graph in. raw = averaged, never added up (temperature, humidity, V, A, PF).
UNITS = [
    # identifier, name, typeOfUnit, unitRepresent, displayable, electrical (optional set)
    ("% RH", "percent relative humidity", "unit", "raw", "all", False),
    ("Temperature_Sensor_C", "Temperature_Sensor_C", "meter", "raw", "none", False),
    ("Humidity_Sensor_RH", "Humidity_Sensor_RH", "meter", "raw", "none", False),
    ("A", "ampere", "unit", "raw", "all", True),
    ("Current_Sensor_A", "Current_Sensor_A", "meter", "raw", "none", True),
    ("V", "volt", "unit", "raw", "all", True),
    ("Voltage_Sensor_V", "Voltage_Sensor_V", "meter", "raw", "none", True),
    ("PF", "power factor", "unit", "raw", "all", True),
    ("PF_Sensor", "PF_Sensor", "meter", "raw", "none", True),
]

# Conversions (tutorial B.4): meter unit -> graphing unit, slope 1, one way.
CONVERSIONS = [
    ("Temperature_Sensor_C", "Celsius", False),
    ("Humidity_Sensor_RH", "% RH", False),
    ("Current_Sensor_A", "A", True),
    ("Voltage_Sensor_V", "V", True),
    ("PF_Sensor", "PF", True),
]


class OED:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.token = None

    def call(self, method, path, body=None, ok_codes=(200,)):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                text = r.read().decode("utf-8", "replace")
                code = r.status
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            code = e.code
        except urllib.error.URLError as e:
            sys.exit(f"cannot reach OED at {self.url}: {e.reason} (is arkan-oed-web running?)")
        if code not in ok_codes:
            sys.exit(f"{method} {path} failed: HTTP {code}: {text[:500]}")
        try:
            return json.loads(text)
        except ValueError:
            return text

    def login(self, email, password):
        r = self.call("POST", "/api/login", {"email": email, "password": password}, ok_codes=(200, 401))
        if not isinstance(r, dict) or "token" not in r:
            sys.exit("OED login failed: check the admin email and password (tutorial A.9)")
        if r.get("role") != "admin":
            sys.exit(f"{email} is not an OED admin (role {r.get('role')})")
        self.token = r["token"]


def say(done, what):
    print(f"  {'created ' if done else 'exists  '} {what}")


def parse_gps(text):
    if not text:
        return None
    try:
        lat, lon = (float(x) for x in text.split(","))
    except ValueError:
        sys.exit("--gps must be latitude,longitude, for example --gps=-8.65,115.13")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        sys.exit("--gps out of range")
    return {"latitude": lat, "longitude": lon}


def meter_body(name, unit_id, graphic_id, freq, cumulative, gap, variation, gps):
    # Same fields and defaults as OED's own "Create a Meter" window (CreateMeterModalComponent.tsx).
    return {
        "name": name, "identifier": name, "url": "", "enabled": False, "displayable": True,
        "meterType": "other", "timeZone": None, "gps": gps, "note": "", "area": 0,
        "cumulative": cumulative, "cumulativeReset": False, "cumulativeResetStart": "",
        "cumulativeResetEnd": "", "endOnlyTime": False, "readingGap": gap,
        "readingVariation": variation, "readingDuplication": 1, "timeSort": "increasing",
        "reading": 0.0, "startTimestamp": "", "endTimestamp": "", "previousEnd": "",
        "unitId": unit_id, "defaultGraphicUnit": graphic_id, "areaUnit": "none",
        "readingFrequency": freq,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", help="site code, the prefix of the meter names (adab)")
    ap.add_argument("--admin", required=True, help="OED admin email (tutorial A.9)")
    ap.add_argument("--admin-password-file", help="file holding the admin password (else asked)")
    ap.add_argument("--energy", nargs="+", default=["EM01"], help="energy meters of the site (EM01)")
    ap.add_argument("--sensors", nargs="+", default=["TH1", "TH2"], help="TH sensors of the site (TH1 TH2)")
    ap.add_argument("--electrical", action="store_true",
                    help="also the optional A, V, PF units and meters (needs export-oed --all)")
    ap.add_argument("--gps", help="latitude,longitude of the site, for the meters and the site group; write it --gps=-8.65,115.13 (with =, the minus sign would be read as an option)")
    ap.add_argument("--csv-user", help="email of the OED user with the CSV role, created if missing")
    ap.add_argument("--csv-password-file", help="file holding that user's password (tutorial C.2)")
    ap.add_argument("--title", default="Arkan monitoring", help="OED site title")
    ap.add_argument("--timezone", default="Asia/Makassar", help="OED default time zone")
    ap.add_argument("--url", default="http://127.0.0.1:8810", help="OED web, loopback")
    a = ap.parse_args()
    gps = parse_gps(a.gps)
    if a.csv_user and not a.csv_password_file:
        ap.error("--csv-user needs --csv-password-file")

    if a.admin_password_file:
        with open(a.admin_password_file, encoding="utf-8") as f:
            password = f.read().strip("\r\n")
    else:
        password = getpass.getpass(f"OED password of {a.admin}: ")
    oed = OED(a.url)
    oed.login(a.admin, password)
    print(f"logged in to OED {oed.call('GET', '/api/version')} as {a.admin}")

    # 1. Site settings (A.11)
    print("site settings")
    prefs = oed.call("GET", "/api/preferences")
    want = {"displayTitle": a.title, "defaultChartToRender": "line", "defaultLanguage": "en",
            "defaultTimezone": a.timezone}
    if any(prefs.get(k) != v for k, v in want.items()):
        prefs.update(want)
        oed.call("POST", "/api/preferences", {"preferences": prefs})
        say(True, f"title '{a.title}', Line, English, {a.timezone}")
    else:
        say(False, f"title '{a.title}', Line, English, {a.timezone}")

    # 2. Units (B.2, B.3)
    print("units")
    redo_cik = False
    units = {u["identifier"]: u for u in oed.call("GET", "/api/units")}
    cel = units.get("Celsius")
    if not cel:
        sys.exit("OED has no Celsius unit: was 'npm run createdb' run (tutorial A.8)?")
    if cel["displayable"] != "all":
        cel = dict(cel, displayable="all")
        oed.call("POST", "/api/units/edit", {k: cel[k] for k in (
            "id", "name", "identifier", "unitRepresent", "secInRate", "typeOfUnit", "suffix",
            "displayable", "preferredDisplay", "note")})
        say(True, "Celsius displayable: all")
    else:
        say(False, "Celsius displayable: all")
    for ident, name, kind, rep, disp, electrical in UNITS:
        if electrical and not a.electrical:
            continue
        if ident in units:
            say(False, f"unit {ident}")
            continue
        oed.call("POST", "/api/units/addUnit", {
            "name": name, "identifier": ident, "unitRepresent": rep, "secInRate": 3600,
            "typeOfUnit": kind, "suffix": "", "displayable": disp, "preferredDisplay": True,
            "note": "Arkan monitoring (oed-setup.py)"})
        say(True, f"unit {ident} ({kind}, {rep}, displayable {disp})")
        redo_cik = True
    units = {u["identifier"]: u for u in oed.call("GET", "/api/units")}

    # 3. Conversions (B.4)
    print("conversions")
    convs = {(c["sourceId"], c["destinationId"]) for c in oed.call("GET", "/api/conversions")}
    for src, dst, electrical in CONVERSIONS:
        if electrical and not a.electrical:
            continue
        key = (units[src]["id"], units[dst]["id"])
        if key in convs:
            say(False, f"conversion {src} -> {dst}")
            continue
        oed.call("POST", "/api/conversions/addConversion", {
            "sourceId": key[0], "destinationId": key[1], "bidirectional": False,
            "slope": 1, "intercept": 0, "note": "Arkan monitoring (oed-setup.py)"})
        say(True, f"conversion {src} -> {dst}, slope 1")
        redo_cik = True

    # OED's own pages do this after a unit or conversion change: rebuild the table of which
    # meter can be graphed in which unit (the "Cik" table). Without it the new units stay unusable.
    if redo_cik:
        print("  rebuilding OED's unit table (redoCik)...")
        oed.call("POST", "/api/conversion-array/refresh", {"redoCik": True, "refreshReadingViews": False})

    # 4. Meters (B.5). Names = what manage.py export-oed writes (oed_meter_name).
    print("meters")
    uid = lambda ident: units[ident]["id"]
    plan = []
    for em in a.energy:
        # Cumulative counter, 1-minute readings, Reading Gap 3600 s (tutorial B.5 explains why)
        plan.append((f"{a.site}-{em}-energy", uid("Electric_Utility"), uid("kWh"), "00:01:00", True, 3600, 0))
        if a.electrical:
            for ph in ("1", "2", "3"):
                plan.append((f"{a.site}-{em}-i{ph}", uid("Current_Sensor_A"), uid("A"), "00:01:00", False, 3600, 0))
                plan.append((f"{a.site}-{em}-v{ph}", uid("Voltage_Sensor_V"), uid("V"), "00:01:00", False, 3600, 0))
            plan.append((f"{a.site}-{em}-pf", uid("PF_Sensor"), uid("PF"), "00:01:00", False, 3600, 0))
    for th in a.sensors:
        plan.append((f"{a.site}-{th}-temp", uid("Temperature_Sensor_C"), uid("Celsius"), "00:05:00", False, 3600, 3600))
        plan.append((f"{a.site}-{th}-hum", uid("Humidity_Sensor_RH"), uid("% RH"), "00:05:00", False, 3600, 3600))
    meters = {m["name"]: m for m in oed.call("GET", "/api/meters")}
    for name, unit_id, graphic_id, freq, cumul, gap, var in plan:
        if name in meters:
            m = meters[name]
            note = "" if m.get("unitId") == unit_id else f"  WARNING: its unit differs (id {m.get('unitId')}, expected {unit_id})"
            say(False, f"meter {name}{note}")
            continue
        m = oed.call("POST", "/api/meters/addMeter", meter_body(name, unit_id, graphic_id, freq, cumul, gap, var, gps))
        meters[name] = m
        say(True, f"meter {name} (id {m['id']}, every {freq}{', cumulative' if cumul else ''})")

    # 5. Groups (B.6): energy meters only (OED only groups meters that share a unit).
    print("groups")
    groups = {g["name"]: g for g in oed.call("GET", "/api/groups")}
    energy_ids = [meters[f"{a.site}-{em}-energy"]["id"] for em in a.energy]
    if a.site not in groups:
        oed.call("POST", "/api/groups/create", {
            "name": a.site, "displayable": True, "gps": gps, "note": "", "area": 0,
            "childGroups": [], "childMeters": energy_ids, "defaultGraphicUnit": uid("kWh"), "areaUnit": "none"})
        say(True, f"group {a.site} (energy meters {', '.join(a.energy)}, kWh)")
        groups = {g["name"]: g for g in oed.call("GET", "/api/groups")}
    else:
        say(False, f"group {a.site}")
    site_gid = groups[a.site]["id"]
    if "All sites" not in groups:
        oed.call("POST", "/api/groups/create", {
            "name": "All sites", "displayable": True, "gps": None, "note": "", "area": 0,
            "childGroups": [site_gid], "childMeters": [], "defaultGraphicUnit": uid("kWh"), "areaUnit": "none"})
        say(True, f"group All sites (with {a.site})")
    else:
        all_g = groups["All sites"]
        kids = oed.call("GET", f"/api/groups/children/{all_g['id']}")
        if site_gid in kids.get("groups", []):
            say(False, f"group All sites (with {a.site})")
        else:
            body = {k: all_g.get(k) for k in ("id", "name", "displayable", "gps", "note", "area",
                                              "defaultGraphicUnit", "areaUnit")}
            body.update(childGroups=kids.get("groups", []) + [site_gid], childMeters=kids.get("meters", []))
            body = {k: v for k, v in body.items() if v is not None or k in ("gps", "note")}
            oed.call("PUT", "/api/groups/edit", body)
            say(True, f"{a.site} added to group All sites")

    # 6. CSV user (C.2)
    if a.csv_user:
        print("users")
        with open(a.csv_password_file, encoding="utf-8") as f:
            csv_pw = f.read().strip("\r\n")
        if len(csv_pw) < 8:
            sys.exit(f"{a.csv_password_file}: the password needs at least 8 characters")
        users = {u["email"]: u for u in oed.call("GET", "/api/users")}
        if a.csv_user in users:
            say(False, f"user {a.csv_user} (role {users[a.csv_user]['role']})")
        else:
            oed.call("POST", "/api/users/create", {"email": a.csv_user, "password": csv_pw, "role": "csv"})
            say(True, f"user {a.csv_user} (role csv)")

    # 7. Chart links (OED's own link format, RouteComponent.tsx): bookmarks for Part D.
    base = "https://arkan-monitoring.duckdns.org/graph?"
    temps = ",".join(str(meters[f"{a.site}-{th}-temp"]["id"]) for th in a.sensors)
    hums = ",".join(str(meters[f"{a.site}-{th}-hum"]["id"]) for th in a.sensors)
    print("chart links (add &serverRange=2026-11-01T00:00:00Z_2026-11-08T00:00:00Z for a fixed period)")
    print(f"  power, kW:          {base}groupIDs={site_gid}&chartType=line&unitID={uid('kWh')}")
    print(f"  energy per day:     {base}groupIDs={site_gid}&chartType=bar&unitID={uid('kWh')}&barDuration=1")
    print(f"  this vs last week:  {base}groupIDs={site_gid}&chartType=compare&unitID={uid('kWh')}&comparePeriod=Week")
    print(f"  temperatures:       {base}meterIDs={temps}&chartType=line&unitID={uid('Celsius')}")
    print(f"  humidity:           {base}meterIDs={hums}&chartType=line&unitID={uid('% RH')}")
    print("done. Next: tutorial 3 Part C (export, upload, refresh).")


if __name__ == "__main__":
    main()
