"""Tests of the data folder and the HTTP service. Run: python3 -m unittest discover -s server/tests"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import server as server_mod  # noqa: E402
from server import make_server  # noqa: E402

server_mod.Handler.log_message = lambda *a: None   # quiet tests
from alarms import AlarmEngine  # noqa: E402
import registers  # noqa: E402
from store import DataStore, IngestError, token_hash  # noqa: E402

MANAGE = os.path.join(HERE, "..", "tools", "manage.py")
HEADER = "ts,EM01_v1,EM01_p,EM01_p_max,EM01_e,EM01_n,TH1_t,TH1_rh,TH1_n,rssi,heap_kb,up_s,backlog_min,boot"


def ts(minutes_ago):
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=minutes_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def fake_image(version, env="usb", chip=9, size=70000):
    """Bytes shaped like an ESP32-S3 app image with the logger's marker (firmware/include/config.h FW_TAG)."""
    head = bytes([0xE9, 3, 2, 0x20]) + b"\0" * 8 + chip.to_bytes(2, "little") + b"\0" * 10
    tag = f"ARKAN-LOGGER-FW;ver={version};env={env};".encode() + b"\0"
    return (head + b"\x11" * 2000 + tag).ljust(size, b"\x22")


def row(t, e=1000.0, boot=""):
    return f"{t},231.2,12.345,13.1,{e:.2f},4,31.20,62.0,4,-63,180,600,0,{boot}"


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = DataStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def day_lines(self, day, part=1):
        with open(self.s.day_path("adab", "LOG-0001", day, part)) as f:
            return f.read().splitlines()

    def test_append_and_duplicates(self):
        rows = [row(ts(m)) for m in (3, 2, 1)]
        r = self.s.ingest("adab", "LOG-0001", HEADER + "\n" + "\n".join(rows) + "\n")
        self.assertEqual((r["stored"], r["duplicates"]), (3, 0))
        r = self.s.ingest("adab", "LOG-0001", HEADER + "\n" + "\n".join(rows) + "\n")
        self.assertEqual((r["stored"], r["duplicates"]), (0, 3))
        day = ts(1)[:10]
        lines = self.day_lines(day) if ts(3)[:10] == day else None
        if lines:
            self.assertEqual(lines[0], HEADER)
            self.assertEqual(len(lines), 4)

    def test_out_of_order_rows_are_sorted(self):
        base = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)
        mk = lambda m: (base + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.s.ingest("adab", "LOG-0001", HEADER + "\n" + row(mk(5)) + "\n" + row(mk(6)) + "\n")
        r = self.s.ingest("adab", "LOG-0001", HEADER + "\n" + row(mk(1)) + "\n")   # backfill of an older row
        self.assertEqual(r["stored"], 1)
        lines = self.day_lines("2026-11-07")
        self.assertEqual([ln[:20] for ln in lines[1:]], [mk(1), mk(5), mk(6)])

    def test_new_columns_go_to_a_new_part(self):
        t = "2026-11-07T03:00:00Z"
        self.s.ingest("adab", "LOG-0001", HEADER + "\n" + row(t) + "\n")
        h2 = HEADER.replace(",rssi", ",TH2_t,rssi")
        r2 = row("2026-11-07T03:01:00Z").replace(",-63,", ",29.5,-63,")
        self.s.ingest("adab", "LOG-0001", h2 + "\n" + r2 + "\n")
        self.assertEqual(self.day_lines("2026-11-07", 2)[0], h2)
        # the same timestamp is not stored twice even across parts
        r = self.s.ingest("adab", "LOG-0001", h2 + "\n" + row(t).replace(",-63,", ",29.5,-63,") + "\n")
        self.assertEqual(r["duplicates"], 1)

    def test_bad_rows_are_counted_not_stored(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:00Z")
        body = "\n".join([HEADER, row(ts(1)), "2026-11-07T03:00:00Z,231", row(future), "garbage;rm -rf", row("2020-01-01T00:00:00Z")])
        r = self.s.ingest("adab", "LOG-0001", body)
        self.assertEqual((r["stored"], r["rejected_rows"]), (1, 4))

    def test_bad_header_is_refused(self):
        with self.assertRaises(IngestError):
            self.s.ingest("adab", "LOG-0001", "time,a\n")
        with self.assertRaises(IngestError):
            self.s.ingest("adab", "LOG-0001", "ts,a b\n")

    def test_rows_before_records_from_are_not_stored(self):
        p = os.path.join(self.s.site_dir("adab"), "site.json")
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as f:
            json.dump({"code": "adab", "records_from": "2026-11-07T09:00:00Z"}, f)
        r = self.s.ingest("adab", "LOG-0001", HEADER + "\n" + row("2026-11-07T08:59:00Z") + "\n"
                          + row("2026-11-07T09:00:00Z") + "\n")
        self.assertEqual((r["stored"], r["duplicates"], r["before_start"]), (1, 0, 1))
        self.assertEqual(self.day_lines("2026-11-07")[1:], [row("2026-11-07T09:00:00Z")])
        r = self.s.ingest("adab", "LOG-0001", HEADER + "\n" + row("2026-11-07T09:01:00Z") + "\n")
        self.assertNotIn("before_start", r)   # the usual answer, as in the docs

    def test_boot_event(self):
        self.s.ingest("adab", "LOG-0001", HEADER + "\n" + row(ts(1), boot="sw:daily") + "\n")
        with open(os.path.join(self.s.device_dir("adab", "LOG-0001"), "events.jsonl")) as f:
            ev = [json.loads(x) for x in f]
        self.assertEqual(ev[0]["kind"], "boot")
        self.assertEqual(ev[0]["reason"], "sw:daily")


PQ_HEADER = ("ts,EM01_v1,EM01_v1_min,EM01_v1_max,EM01_v2,EM01_v2_min,EM01_v2_max,EM01_v3,EM01_v3_min,EM01_v3_max,"
             "EM01_p1,EM01_p2,EM01_p3,EM01_p,EM01_e,EM01_n,TH1_t,TH1_rh,TH2_t,TH2_rh,rssi,backlog_min,sd,boot")


def pq_row(t, v2=230.0, v2min=None, p3=3.0, e=100.0, th1=30.0, n=4, sd=1, boot="", rssi=-60):
    v2min = v2 if v2min is None else v2min
    return (f"{t},230,229,231,{v2},{v2min},{v2},230,229,231,3,3,{p3},{6 + p3},{e:.2f},{n},{th1},60,28,70,"
            f"{rssi},0,{sd},{boot}")


class AlarmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = DataStore(self.tmp.name)
        self.s.alarms = AlarmEngine(self.s)
        self.base = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def t(self, m):
        return (self.base + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def send(self, rows):
        return self.s.ingest("adab", "LOG-0001", PQ_HEADER + "\n" + "\n".join(rows) + "\n")

    def log(self):
        import csv
        with open(os.path.join(self.s.site_dir("adab"), "alarms", "2026.csv"), newline="") as f:
            return list(csv.reader(f))[1:]

    def test_undervoltage_with_delay_and_dip(self):
        rows = [pq_row(self.t(m), e=100 + m) for m in range(5)]
        rows += [pq_row(self.t(m), v2=200, v2min=190, e=100 + m) for m in range(5, 12)]   # 7 min low
        rows += [pq_row(self.t(m), e=100 + m) for m in range(12, 15)]
        self.send(rows)
        got = [(x[3], x[6], x[0]) for x in self.log()]
        self.assertIn(("A26", "start", self.t(5)), got)      # dip: immediate
        self.assertIn(("A05", "start", self.t(5)), got)      # undervoltage: start time = when it began
        self.assertIn(("A05", "clear", self.t(12)), got)
        self.assertNotIn("A05", [o["id"] for o in self.s.alarms.open_alarms("adab")])

    def test_short_low_voltage_is_not_undervoltage(self):
        rows = [pq_row(self.t(m), v2=200 if 2 <= m < 5 else 230, e=100 + m) for m in range(8)]   # 3 min only
        self.send(rows)
        self.assertNotIn("A05", [x[3] for x in self.log()])

    def test_events_power_interruption_and_ct(self):
        rows = [pq_row(self.t(m), e=100 + m) for m in range(3)]
        rows += [pq_row(self.t(m), e=100 + m, boot="poweron", p3=-2.0 if m < 20 else 3.0) for m in (13,)]
        rows += [pq_row(self.t(m), e=100 + m, p3=-2.0) for m in range(14, 20)]
        self.send(rows)
        log = self.log()
        power = [x for x in log if x[3] == "A02"]
        self.assertEqual(len(power), 1)
        self.assertIn("outage about 10 min", ",".join(power[0]))
        self.assertIn("A30", [x[3] for x in log if x[6] == "start"])   # CT backwards on L3

    def test_open_alarm_survives_restart_and_rebuild_is_identical(self):
        rows = [pq_row(self.t(m), th1=37.0, e=100 + m) for m in range(15)]
        self.send(rows[:8])
        self.send(rows[8:])                                  # state carried between uploads
        self.assertIn("A11", [o["id"] for o in self.s.alarms.open_alarms("adab")])
        before = self.log()
        self.s.alarms.rebuild("adab", lambda dev: [dict(zip(PQ_HEADER.split(","), r.split(","))) for r in rows])
        self.assertEqual([x[:7] for x in self.log()], [x[:7] for x in before])

    def test_offline_then_back(self):
        self.s.save_devices({"devices": {"LOG-0001": {"site": "adab", "token_sha256": "x"}}})
        self.send([pq_row(self.t(0))])
        self.s.alarms.last_rx[("adab", "LOG-0001")] = time.time() - 3600
        self.s.alarms.check_offline()
        self.assertIn("A01", [o["id"] for o in self.s.alarms.open_alarms("adab")])
        self.send([pq_row(self.t(1))])
        self.assertNotIn("A01", [o["id"] for o in self.s.alarms.open_alarms("adab")])
        self.assertEqual([x[6] for x in self.log() if x[3] == "A01"], ["start", "clear"])

    def test_rebuild_keeps_offline_lines(self):
        self.s.save_devices({"devices": {"LOG-0001": {"site": "adab", "token_sha256": "x"}}})
        rows = [pq_row(self.t(m), e=100 + m) for m in range(3)]
        self.send(rows)
        self.s.alarms.last_rx[("adab", "LOG-0001")] = time.time() - 3600
        self.s.alarms.check_offline()
        self.s.alarms.rebuild("adab", lambda dev: [dict(zip(PQ_HEADER.split(","), r.split(","))) for r in rows])
        self.assertIn("A01", [x[3] for x in self.log()])
        self.assertIn("A01", [o["id"] for o in self.s.alarms.open_alarms("adab")])

    def test_backlog_alarm_ignores_wifi_outage(self):
        rows = [pq_row(self.t(m), rssi="").replace(",0,1,", ",90,1,") for m in range(5)]
        self.send(rows)
        self.assertFalse(os.path.exists(os.path.join(self.s.site_dir("adab"), "alarms", "2026.csv"))
                         and "A16" in [x[3] for x in self.log()])


    def test_firmware_update_and_rollback(self):
        rows = [pq_row(self.t(0), boot="poweron@0.3.0"), pq_row(self.t(1)),
                pq_row(self.t(5), boot="sw:ota@0.3.1"), pq_row(self.t(6)),
                pq_row(self.t(9), boot="sw:ota_rollback@0.3.0"),
                pq_row(self.t(20), boot="poweron@0.3.2")]          # flashed by hand
        self.send(rows)
        ev = {(x[3], x[0]): x[11] for x in self.log() if x[3] in ("A35", "A36")}
        self.assertIn("0.3.0 -> 0.3.1, by remote update (OTA)", ev[("A35", self.t(5))])
        self.assertIn("back to 0.3.0", ev[("A36", self.t(9))])
        self.assertIn("flashed by hand", ev[("A35", self.t(20))])
        self.assertEqual(len(ev), 3)                                  # no A35 for the rollback itself
        self.assertEqual(len([x for x in self.log() if x[3] == "A02"]), 2)   # poweron@... still a power interruption

    def test_sensor_rows_every_5_min_and_err(self):
        def row5(m, th):
            r = pq_row(self.t(m), e=100 + m).split(",")
            r[16:20] = th
            return ",".join(r)
        rows = [row5(m, ["30", "60", "28", "70"] if m % 5 == 0 else ["", "", "", ""]) for m in range(0, 30)]
        self.send(rows)                                               # empty rows between: no fault
        self.assertFalse(os.path.exists(os.path.join(self.s.site_dir("adab"), "alarms", "2026.csv"))
                         and "A14" in [x[3] for x in self.log()])
        rows = [row5(m, ["30", "60", "err", "err"] if m % 5 == 0 else ["", "", "", ""]) for m in range(30, 50)]
        self.send(rows)
        starts = [x for x in self.log() if x[3] == "A14" and x[6] == "start"]
        self.assertEqual(starts[0][0], self.t(30))

    def test_pln_limit_per_phase(self):
        os.makedirs(self.s.site_dir("adab"), exist_ok=True)
        with open(os.path.join(self.s.site_dir("adab"), "site.json"), "w") as f:
            json.dump({"contracted_kva": 82.5, "contract_v_ln": 220}, f)
        h = "ts,EM01_i1,EM01_i1_max,EM01_i2,EM01_i2_max,EM01_i3,EM01_i3_max,EM01_n"
        rows = [f"{self.t(m)},60,{120 if 3 <= m < 10 else 70},60,70,60,70,4" for m in range(14)]   # 120 A = 96 %
        self.s.ingest("adab", "LOG-0001", h + "\n" + "\n".join(rows) + "\n")
        a37 = [(x[6], x[0]) for x in self.log() if x[3] == "A37"]
        self.assertEqual(a37, [("start", self.t(3)), ("clear", self.t(10))])


class ToolsAndHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = self.tmp.name
        self.manage("init")
        self.manage("add-site", "adab", "--name", "Adab hotel")
        out = self.manage("add-device", "adab", "LOG-0001")
        self.token = [ln for ln in out.splitlines() if ln.startswith("TOKEN")][0].split(": ", 1)[1]
        self.srv = make_server(self.data, "127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def manage(self, *args):
        return subprocess.run([sys.executable, MANAGE, "--data", self.data, *args], check=True,
                              capture_output=True, text=True).stdout

    def req(self, method, path, body=None, token=None, ctype="text/csv", headers=None):
        headers = dict(headers or {}, **{"Content-Type": ctype})
        if token:
            headers["Authorization"] = "Bearer " + token
        if isinstance(body, str):
            body = body.encode()
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=body, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read().decode("latin-1")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_token_hash_only(self):
        with open(os.path.join(self.data, "devices.json")) as f:
            text = f.read()
        self.assertNotIn(self.token, text)
        self.assertIn(token_hash(self.token), text)

    def test_ingest_live_status(self):
        code, _ = self.req("POST", "/api/v1/ingest", HEADER + "\n" + row(ts(1)) + "\n")
        self.assertEqual(code, 401)
        code, body = self.req("POST", "/api/v1/ingest", HEADER + "\n" + row(ts(2)) + "\n" + row(ts(1)) + "\n", self.token)
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)["stored"], 2)
        snap = {"ts": ts(0), "values": {"EM01_p": 12.3}, "sys": {"rssi": -60}}
        code, _ = self.req("POST", "/api/v1/live", json.dumps(snap), self.token, "application/json")
        self.assertEqual(code, 204)
        code, body = self.req("GET", "/api/v1/live/adab")
        self.assertEqual(json.loads(body)["devices"]["LOG-0001"]["last"]["values"]["EM01_p"], 12.3)
        prof = json.loads(body)["profile"]   # what the live page needs, and nothing private
        self.assertIn("sensors", prof)
        self.assertEqual(prof["nominal_v"], 230)
        self.assertNotIn("devices", prof)
        code, body = self.req("GET", "/api/v1/status")
        self.assertEqual(json.loads(body)["sites"]["adab"]["LOG-0001"]["last_record"], ts(1))
        code, body = self.req("GET", "/live/adab/")
        self.assertEqual(code, 200)
        self.assertIn("<title>Live</title>", body)
        self.assertIn('href="/live/_ui/arkan-ui.css"', body)                # the Arkan UI kit, served beside the page
        for name, mark in (("arkan-ui.css", "--brand"), ("arkan-ui.js", "ArkanUI")):
            code, body = self.req("GET", f"/live/_ui/{name}")
            self.assertEqual(code, 200)
            self.assertIn(mark, body)
        self.assertEqual(self.req("GET", "/live/_ui/server.py")[0], 404)
        self.assertEqual(self.req("GET", "/live/")[0], 200)

    def test_meter_link_on_the_live_page(self):
        # firmware 0.5.0 sends the Modbus link of each meter in sys.mb; the page gets one line per meter
        ok = {"ok": True, "id": 1, "since": ts(30), "last_ok": ts(0), "fail_run": 0, "req": 4, "req_ok": 4,
              "reads": 900, "fails": 2}
        snap = {"ts": ts(0), "values": {"EM01_p": 12.3}, "sys": {"up_s": 7200, "mb": {"EM01": ok}}}
        self.assertEqual(self.req("POST", "/api/v1/live", json.dumps(snap), self.token, "application/json")[0], 204)
        code, body = self.req("GET", "/api/v1/live/adab")
        links = json.loads(body)["devices"]["LOG-0001"]["meters"]
        self.assertEqual([(m["meter"], m["state"], m["stale"], m["source"]) for m in links], [("EM01", "ok", False, "logger")])
        self.assertEqual((links[0]["modbus_id"], links[0]["req_ok"], links[0]["since"]), (1, 4, ts(30)))
        self.assertAlmostEqual(links[0]["for_s"], 1800, delta=70)
        # the meter stops answering: the line stays, now "no_answer" with the reason
        bad = dict(ok, ok=False, since=ts(0), last_ok=ts(1), fail_run=5, req_ok=0, err="timeout", fails=7)
        snap = {"ts": ts(0), "values": {}, "sys": {"up_s": 7215, "mb": {"EM01": bad}}}
        self.assertEqual(self.req("POST", "/api/v1/live", json.dumps(snap), self.token, "application/json")[0], 204)
        links = json.loads(self.req("GET", "/api/v1/live/adab")[1])["devices"]["LOG-0001"]["meters"]
        self.assertEqual((links[0]["state"], links[0]["err"], links[0]["fail_run"], links[0]["last_ok"]),
                         ("no_answer", "timeout", 5, ts(1)))

    def test_live_saved_and_restored(self):
        # every snapshot is saved in the data folder: another dashboard reads the same data, a restart keeps it
        for i in range(3):
            snap = {"ts": ts(0), "values": {"EM01_p": 10.0 + i}, "sys": {"rssi": -60}}
            self.assertEqual(self.req("POST", "/api/v1/live", json.dumps(snap), self.token, "application/json")[0], 204)
        dev_dir = os.path.join(self.data, "sites", "adab", "LOG-0001")
        with open(os.path.join(dev_dir, "live.json")) as f:
            last = json.load(f)
        self.assertEqual((last["values"]["EM01_p"], last["device"]), (12.0, "LOG-0001"))
        self.assertTrue(last["recv"].endswith("Z"))
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        code, body = self.req("GET", f"/api/v1/live/adab/day/{day}")
        self.assertEqual(code, 200, body)
        self.assertEqual([x["values"]["EM01_p"] for x in json.loads(body)["snapshots"]], [10.0, 11.0, 12.0])
        self.assertEqual(self.req("GET", f"/api/v1/live/adab/day/{day}?device=LOG-9")[0], 404)
        # a new service on the same folder (restart, update) has the last 60 minutes at once
        live2 = server_mod.Live(DataStore(self.data))
        hist = live2.site("adab")["LOG-0001"]["history"]
        self.assertEqual([h["values"]["EM01_p"] for h in hist], [10.0, 11.0, 12.0])
        # old day files go, today's stays
        old = os.path.join(dev_dir, "live", "2020-01-01.jsonl")
        open(old, "w").close()
        live2.prune()
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(os.path.join(dev_dir, "live", day + ".jsonl")))
        # LIVE_KEEP_DAYS=0: memory only, nothing written
        mem = server_mod.Live(DataStore(self.data), keep_days=0)
        mem.add("adab", "LOG-0002", {"ts": ts(0), "values": {}})
        self.assertFalse(os.path.exists(os.path.join(self.data, "sites", "adab", "LOG-0002")))

    def test_history(self):
        # 6 minutes, the counter going up 0.5 kWh a minute: 2.5 kWh between the first and the last record
        rows = [row(ts(m), e=1000 + (5 - m) * 0.5) for m in range(5, -1, -1)]
        code, body = self.req("POST", "/api/v1/ingest", HEADER + "\n" + "\n".join(rows) + "\n", self.token)
        self.assertEqual(code, 200, body)
        code, body = self.req("GET", "/api/v1/history/adab?days=2")
        self.assertEqual(code, 200, body)
        h = json.loads(body)["hours"]
        self.assertAlmostEqual(sum(r["kwh"] for r in h), 2.5, places=3)
        self.assertEqual(sum(r["minutes"] for r in h), 6)
        self.assertAlmostEqual(h[-1]["p"], 12.345, places=3)
        self.assertAlmostEqual(h[-1]["p_max"], 13.1, places=3)
        self.assertAlmostEqual(h[-1]["TH1_t"], 31.2, places=2)
        local = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
        code, body = self.req("GET", f"/api/v1/history/adab/day/{local}")
        self.assertEqual(code, 200, body)
        self.assertGreaterEqual(len(json.loads(body)["minutes"]), 1)   # rows before 00:00 WITA fall on the previous day
        self.assertEqual(self.req("GET", "/api/v1/history/nosite")[0], 404)
        self.assertEqual(self.req("GET", "/api/v1/history/adab/day/2026-13-40")[0], 400)
        self.assertEqual(self.req("GET", "/api/v1/history/adab?meter=../x")[0], 400)

    def test_custom_period_and_records_csv(self):
        # hotel time is UTC+8: the hotel day 3 November is in the UTC day files of 2 and 3 November
        rows = [row("2026-11-02T10:00:00Z", 1000), row("2026-11-02T17:00:00Z", 1001),   # hotel 2 Nov 18:00, 3 Nov 01:00
                row("2026-11-03T05:00:00Z", 1002), row("2026-11-03T17:00:00Z", 1003)]   # hotel 3 Nov 13:00, 4 Nov 01:00
        code, body = self.req("POST", "/api/v1/ingest", HEADER + "\n" + "\n".join(rows) + "\n", self.token)
        self.assertEqual(json.loads(body)["stored"], 4, body)
        j = json.loads(self.req("GET", "/api/v1/history/adab?from=2026-11-03&to=2026-11-03")[1])
        self.assertEqual([r["t"] for r in j["hours"]], ["2026-11-03 01:00", "2026-11-03 13:00"])
        self.assertEqual((j["from"], j["to"], j["first_day"]), ("2026-11-03 00:00", "2026-11-03", "2026-11-02"))
        j = json.loads(self.req("GET", "/api/v1/quality/adab?from=2026-11-02&to=2026-11-03")[1])
        self.assertEqual((len(j["hours"]), j["to"]), (3, "2026-11-03"))
        # the CSV: the whole day files that hold those hotel dates, every row and column, as they are
        url = f"http://127.0.0.1:{self.port}/api/v1/records/adab?from=2026-11-03&to=2026-11-03"
        with urllib.request.urlopen(url, timeout=5) as r:
            self.assertIn("text/csv", r.headers["Content-Type"])
            self.assertIn('filename="adab-LOG-0001-2026-11-03.csv"', r.headers["Content-Disposition"])
            self.assertEqual(r.read().decode().split("\n"), [HEADER] + rows + [""])
        with urllib.request.urlopen(url.replace("from=2026-11-03", "from=2026-11-04").replace("to=2026-11-03", "to=2026-11-05"),
                                    timeout=5) as r:
            self.assertIn('filename="adab-LOG-0001-2026-11-04-to-2026-11-05.csv"', r.headers["Content-Disposition"])
            self.assertEqual(r.read().decode().splitlines(), [HEADER] + rows[2:])   # 3 Nov (UTC) file only
        # new columns that day (a _2 file): one header with every column, each value under its own column
        h2 = HEADER.replace(",rssi", ",TH2_t,rssi")
        r2 = row("2026-11-03T06:00:00Z", 1002.5).replace(",-63,", ",29.5,-63,")
        self.assertEqual(json.loads(self.req("POST", "/api/v1/ingest", h2 + "\n" + r2 + "\n", self.token)[1])["stored"], 1)
        code, body = self.req("GET", "/api/v1/records/adab?from=2026-11-03&to=2026-11-03")
        self.assertEqual(code, 200, body)
        self.assertEqual(body.splitlines(), [HEADER + ",TH2_t"] + [x + "," for x in rows] + [row("2026-11-03T06:00:00Z", 1002.5) + ",29.5"])
        # refused: dates the wrong way round, more than 92 days, to without from, a bad date; nothing recorded: 404
        for q in ("from=2026-11-05&to=2026-11-04", "from=2026-01-01&to=2026-11-01", "to=2026-11-03", "from=2026-13-01&to=2026-13-02"):
            self.assertEqual(self.req("GET", "/api/v1/records/adab?" + q)[0], 400, q)
            self.assertEqual(self.req("GET", "/api/v1/history/adab?" + q)[0], 400, q)
            self.assertEqual(self.req("GET", "/api/v1/quality/adab?" + q)[0], 400, q)
        self.assertEqual(self.req("GET", "/api/v1/records/adab?from=2025-01-01&to=2025-01-02")[0], 404)
        self.assertEqual(self.req("GET", "/api/v1/records/adab?from=2026-11-03&to=2026-11-03&device=LOG-9")[0], 404)
        self.assertEqual(self.req("GET", "/api/v1/records/nosite?from=2026-11-03&to=2026-11-03")[0], 404)

    def test_quality(self):
        hdr = ("ts,EM01_v1,EM01_v1_min,EM01_v1_max,EM01_v2,EM01_v2_min,EM01_v2_max,EM01_v3,EM01_v3_min,EM01_v3_max,"
               "EM01_i1,EM01_i2,EM01_i3,EM01_f,EM01_f_min,EM01_f_max,EM01_p,EM01_q,EM01_pf,EM01_pf_min,EM01_pf_max,"
               "EM01_e,EM01_eq,EM01_n,rssi,backlog_min,sd,boot")
        rows = []
        for n, m in enumerate(range(9, -1, -1)):   # 10 minutes; e +0.5 kWh and eq +0.25 kVArh a minute
            v2, v2min, v3max, p, pf, pfmin = 230, 229, 231, 20, 0.9, 0.88
            if n == 3:
                v2, v2min = 205, 180          # undervoltage minute (mean < 207) and a dip (sample < 207)
            if n == 5:
                pf, pfmin = 0.80, 0.78        # power factor below 0.85
            if n == 7:
                p, pf, pfmin = 0.5, 0.5, 0.5  # below 1 kW: no power factor counted
            if n == 8:
                v3max = 255                   # a swell (sample > 253)
            rows.append(f"{ts(m)},230,229,231,{v2},{v2min},{v2},230,229,{v3max},10,10,10,50,49.98,50.02,{p},10,{pf},{pfmin},"
                        f"{pf},{1000 + n * 0.5:.2f},{500 + n * 0.25:.2f},4,-63,0,1,")
        code, body = self.req("POST", "/api/v1/ingest", hdr + "\n" + "\n".join(rows) + "\n", self.token)
        self.assertEqual(code, 200, body)
        code, body = self.req("GET", "/api/v1/quality/adab?days=2")
        self.assertEqual(code, 200, body)
        j = json.loads(body)
        h = j["hours"]
        tot = lambda k: sum(r.get(k, 0) for r in h)
        self.assertEqual(tot("minutes"), 10)
        self.assertEqual((tot("vn"), tot("vok"), tot("vlow"), tot("vhigh")), (10, 9, 1, 0))
        self.assertEqual((tot("dips"), tot("swells"), tot("lost")), (1, 1, 0))
        self.assertEqual((tot("loaded"), tot("pf_low")), (9, 1))
        self.assertAlmostEqual(tot("kwh"), 4.5, places=3)
        self.assertAlmostEqual(tot("kvarh"), 2.25, places=3)
        self.assertEqual(min(r["v2_min"] for r in h), 180)
        self.assertEqual(max(r["v3_max"] for r in h), 255)
        self.assertEqual(min(r["pf_min"] for r in h), 0.78)
        self.assertAlmostEqual(max(r["vu_max"] for r in h), (665 / 3 - 205) / (665 / 3) * 100, places=2)
        self.assertEqual((j["limits"]["low"]["v"], j["limits"]["swell"]["v"], j["limits"]["pf"]["v"]), (207, 253, 0.85))
        ids = {e["id"] for e in j["events"]}
        self.assertTrue({"A26", "A27"} <= ids, ids)          # dip and swell lines of the alarm log
        self.assertFalse(ids - {"A04", "A05", "A06", "A07", "A09", "A10", "A26", "A27", "A28"}, ids)
        # minute by minute, over the one or two hotel days the 10 minutes fall on
        local = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m) + timedelta(hours=8)).strftime("%Y-%m-%d")
        got = []
        for day in sorted({local(9), local(0)}):
            code, body = self.req("GET", f"/api/v1/quality/adab/day/{day}")
            self.assertEqual(code, 200, body)
            d = json.loads(body)
            got += [dict(zip(d["cols"], r)) for r in d["rows"]]
        self.assertEqual(len(got), 10)
        self.assertEqual(sorted(r["v2_min"] for r in got)[0], 180)
        self.assertEqual(sum(r["pf"] is None for r in got), 1)   # the 0.5 kW minute
        # the limits follow the alarm register: a site line A06 at 229 V puts every minute above the limits
        with open(os.path.join(self.data, "alarm-register.csv"), encoding="utf-8") as f:
            reg = f.read().splitlines()
        a06 = next(ln for ln in reg if ln.startswith("A06,")).replace(",242,240,", ",229,228,")
        with open(os.path.join(self.data, "sites", "adab", "alarm-register.csv"), "w", encoding="utf-8") as f:
            f.write(reg[0] + "\n" + a06 + "\n")
        j = json.loads(self.req("GET", "/api/v1/quality/adab?days=2")[1])
        self.assertEqual(j["limits"]["high"]["v"], 229)
        self.assertEqual((sum(r["vok"] for r in j["hours"]), sum(r["vhigh"] for r in j["hours"])), (0, 10))
        self.assertEqual(self.req("GET", "/api/v1/quality/nosite")[0], 404)
        self.assertEqual(self.req("GET", "/api/v1/quality/adab/day/2026-13-40")[0], 400)
        self.assertEqual(self.req("GET", "/api/v1/quality/adab?days=x")[0], 400)

    def write_image(self, version, env="usb", **kw):
        p = os.path.join(self.data, f"build-{env}-{version}.bin")
        with open(p, "wb") as f:
            f.write(fake_image(version, env, **kw))
        return p

    def test_ota(self):
        code, _ = self.req("GET", "/api/v1/ota?fw=0.1.0", token=self.token)
        self.assertEqual(code, 204)
        fw = self.write_image("0.1.1")
        self.manage("publish-fw", fw, "--version", "0.1.1")
        code, body = self.req("GET", "/api/v1/ota?fw=0.1.0", token=self.token)
        self.assertEqual(code, 200)
        url = json.loads(body)["url"]
        self.assertEqual(url, "/api/v1/firmware/logger-0.1.1.bin")
        code, body = self.req("GET", url, token=self.token)
        self.assertEqual(code, 200)
        code, _ = self.req("GET", "/api/v1/ota?fw=0.1.1", token=self.token)
        self.assertEqual(code, 204)
        code, _ = self.req("GET", "/api/v1/ota?fw=0.2.0", token=self.token)   # newer, flashed by hand
        self.assertEqual(code, 204)                                           # never downgraded
        with self.assertRaises(subprocess.CalledProcessError):
            self.manage("publish-fw", fw, "--version", "0.1.2")               # not the version in the file
        with open(fw, "r+b") as f:                                            # same number, other bytes
            f.seek(5000)
            f.write(b"changed")
        with self.assertRaises(subprocess.CalledProcessError):
            self.manage("publish-fw", fw)
        self.manage("publish-fw", self.write_image("0.1.1"), "--force")      # deliberate step back
        code, _ = self.req("GET", "/api/v1/ota?fw=0.2.0", token=self.token)
        self.assertEqual(code, 200)

    def test_image_check(self):
        from firmware import FirmwareError, check_image
        self.assertEqual(check_image(fake_image("0.3.1", "uart")), {"version": "0.3.1", "env": "uart"})
        for bad in (fake_image("0.3.1", chip=0),                      # ESP32, not S3
                    b"\x00" + fake_image("0.3.1")[1:],                 # not an app image
                    fake_image("0.3.1").replace(b"ARKAN-LOGGER-FW", b"OTHER-SKETCH-FW"),
                    fake_image("0.3.1", size=1000),                   # truncated
                    fake_image("0.3.1", size=0x1E0001)):              # larger than the flash slot
            with self.assertRaises(FirmwareError):
                check_image(bad)

    def test_firmware_from_the_live_page(self):
        admin = {"X-Auth-User": "julien", "X-Requested-With": "arkan"}
        server_mod.Handler.admin_users = ""
        code, body = self.req("GET", "/api/v1/admin/me", headers=admin)
        self.assertFalse(json.loads(body)["admin"])
        code, body = self.req("GET", "/api/v1/admin/fw/LOG-0001", headers=admin)
        self.assertEqual(code, 403)                                           # off until ADMIN_USERS is set
        server_mod.Handler.admin_users = "julien, ops"
        self.addCleanup(setattr, server_mod.Handler, "admin_users", "")
        code, _ = self.req("GET", "/api/v1/admin/fw/LOG-0001", headers={"X-Auth-User": "guest"})
        self.assertEqual(code, 403)
        img = fake_image("0.4.0")
        up = "/api/v1/admin/fw/LOG-0001/upload?name=firmware.bin"
        code, _ = self.req("POST", up, img, ctype="application/octet-stream", headers={"X-Auth-User": "julien"})
        self.assertEqual(code, 403)                                           # no X-Requested-With: cross-site
        code, _ = self.req("POST", up, img, ctype="application/octet-stream",
                           headers=dict(admin, Origin="https://evil.example"))
        self.assertEqual(code, 403)
        code, body = self.req("POST", up, fake_image("0.4.0", chip=0), ctype="application/octet-stream", headers=admin)
        self.assertEqual(code, 400)
        self.assertIn("another chip", json.loads(body)["error"])

        # The logger reports its build (usb) and version, then an image is uploaded for it.
        rep = {"fw": "0.3.1", "env": "usb", "cfg_version": 0, "boot": "poweron", "settings": {"ota_on": "1"}}
        self.req("POST", "/api/v1/config/report", json.dumps(rep), self.token, "application/json",
                 headers={"X-Fw": "0.3.1"})
        snap = json.dumps({"ts": ts(0), "values": {"EM01_p": 1}})
        code, _ = self.req("POST", "/api/v1/live", snap, self.token, "application/json", headers={"X-Fw": "0.3.1"})
        self.assertEqual(code, 204)                                           # nothing waiting
        code, body = self.req("POST", up, fake_image("0.4.0", env="uart"), ctype="application/octet-stream",
                              headers=admin)
        self.assertEqual(code, 400)                                           # wrong build variant
        self.assertIn("'usb' build", json.loads(body)["error"])
        code, body = self.req("POST", up, img, ctype="application/octet-stream", headers=admin)
        self.assertEqual(code, 200, body)
        view = json.loads(body)["view"]
        self.assertEqual((view["state"], view["offer"]["by"], view["scope"]), ("waiting", "julien", "device"))
        code, body = self.req("POST", "/api/v1/live", snap, self.token, "application/json", headers={"X-Fw": "0.3.1"})
        self.assertEqual((code, json.loads(body)), (200, {"ota": 1}))         # "check now" hint
        code, body = self.req("GET", "/api/v1/ota?fw=0.3.1", token=self.token)
        self.assertEqual(json.loads(body)["version"], "0.4.0")

        # The new firmware keeps restarting: the logger goes back, the platform stops offering it.
        rep.update(boot="sw:ota_rollback")
        self.req("POST", "/api/v1/config/report", json.dumps(rep), self.token, "application/json")
        code, _ = self.req("GET", "/api/v1/ota?fw=0.3.1", token=self.token)
        self.assertEqual(code, 204)
        code, body = self.req("GET", "/api/v1/admin/fw/LOG-0001", headers=admin)
        view = json.loads(body)
        self.assertEqual((view["state"], view["failed"]), ("rolled_back", ["0.4.0"]))
        self.assertEqual([f["file"] for f in view["files"]], ["logger-0.4.0.bin", "logger-uart-0.4.0.bin"])
        self.assertIn("ota_failed", [e["kind"] for e in view["events"]])

        # Offered again on purpose from the stored files, then withdrawn.
        code, body = self.req("POST", "/api/v1/admin/fw/LOG-0001/offer", json.dumps({"file": "logger-0.4.0.bin"}),
                              ctype="application/json", headers=admin)
        self.assertEqual(json.loads(body)["view"]["state"], "waiting")
        code, body = self.req("POST", "/api/v1/admin/fw/LOG-0001/offer", json.dumps({"file": "../devices.json"}),
                              ctype="application/json", headers=admin)
        self.assertEqual(code, 400)
        code, body = self.req("POST", "/api/v1/admin/fw/LOG-0001/cancel", "{}", ctype="application/json",
                              headers=admin)
        self.assertTrue(json.loads(body)["cancelled"])
        code, _ = self.req("GET", "/api/v1/ota?fw=0.3.1", token=self.token)
        self.assertEqual(code, 204)
        # An older version is refused without force.
        self.req("POST", "/api/v1/config/report", json.dumps(dict(rep, boot="sw:ota", fw="0.4.0")), self.token,
                 "application/json", headers={"X-Fw": "0.4.0"})
        code, body = self.req("POST", up, fake_image("0.3.9"), ctype="application/octet-stream", headers=admin)
        self.assertEqual(code, 400)
        self.assertIn("not newer", json.loads(body)["error"])
        code, body = self.req("POST", up + "&force=1", fake_image("0.3.9"), ctype="application/octet-stream",
                              headers=admin)
        self.assertEqual(code, 200)

    def test_versions_page(self):
        # the logger says its firmware on each upload; the page lists it, the history and the releases
        self.req("POST", "/api/v1/ingest", HEADER + "\n" + row(ts(2)) + "\n", self.token, headers={"X-Fw": "0.3.1"})
        self.req("POST", "/api/v1/ingest", HEADER + "\n" + row(ts(1), boot="sw:ota@0.3.1") + "\n", self.token,
                 headers={"X-Fw": "0.4.0"})
        server_mod.Handler._releases = {"at": time.time(), "err": None, "rel": [
            {"tag": "fw-v0.4.0", "published": "2026-11-08T01:00:00Z", "prerelease": False, "assets": []},
            {"tag": "fw-v0.5.0-rc1", "published": "2026-11-09T01:00:00Z", "prerelease": True, "assets": []}]}
        gh = server_mod.Handler.github
        server_mod.Handler.github = type("G", (), {"configured": lambda s: True})()
        try:
            code, body = self.req("GET", "/api/v1/versions/adab")
        finally:
            server_mod.Handler.github = gh
            server_mod.Handler._releases = {"at": 0, "rel": None, "err": None}
        self.assertEqual(code, 200, body)
        j = json.loads(body)
        self.assertEqual(j["latest"], "0.4.0")                     # a pre-release is not the latest
        d = j["loggers"][0]
        self.assertEqual((d["device"], d["running"], d["update"]), ("LOG-0001", "0.4.0", "up_to_date"))
        kinds = [(e["kind"], e.get("to") or e.get("reason")) for e in d["history"]]
        self.assertIn(("firmware", "0.4.0"), kinds)
        self.assertIn(("boot", "sw:ota@0.3.1"), kinds)
        self.assertEqual(self.req("GET", "/api/v1/versions/nosite")[0], 404)

    def test_github_releases(self):
        from firmware import GitHub
        gh = GitHub("julien355/esp32-datalogging", "")
        listing = [{"tag_name": "fw-v0.4.0", "draft": False, "prerelease": False, "published_at": "2026-11-08T00:00:00Z",
                    "assets": [{"id": 7, "name": "logger-0.4.0.bin", "size": 70000},
                               {"id": 8, "name": "logger-uart-0.4.0.bin", "size": 70000},
                               {"id": 9, "name": "bootloader.bin", "size": 100}]},
                   {"tag_name": "notes", "draft": False, "assets": []}]
        gh._get = lambda url, accept, limit: json.dumps(listing).encode()
        rel = gh.releases()
        self.assertEqual([a["name"] for a in rel[0]["assets"]], ["logger-0.4.0.bin", "logger-uart-0.4.0.bin"])
        self.assertEqual(len(rel), 1)
        self.assertEqual(gh.asset_label(8), "GitHub fw-v0.4.0 logger-uart-0.4.0.bin")
        self.assertFalse(GitHub("", "").configured())

    def test_remote_config(self):
        code, _ = self.req("GET", "/api/v1/config", token=self.token)
        self.assertEqual(code, 204)
        with self.assertRaises(subprocess.CalledProcessError):
            self.manage("set-config", "LOG-0001", "th1_off_t=1")              # no report yet: keys unchecked
        rep = {"fw": "0.2.0", "cfg_version": 0, "settings": {"th1_off_t": "0", "reboot_hr": "19"}}
        code, _ = self.req("POST", "/api/v1/config/report", json.dumps(rep), self.token, "application/json")
        self.assertEqual(code, 204)
        with self.assertRaises(subprocess.CalledProcessError):
            self.manage("set-config", "LOG-0001", "wifi_ssid=other")       # never remotely
        with self.assertRaises(subprocess.CalledProcessError):
            self.manage("set-config", "LOG-0001", "no_such_key=1")          # not reported by the logger
        self.manage("set-config", "LOG-0001", "th1_off_t=-1.5")
        code, body = self.req("GET", "/api/v1/config", token=self.token)
        self.assertEqual(json.loads(body), {"version": 1, "settings": {"th1_off_t": "-1.5"}})
        self.assertIn("th1_off_t = 0", self.manage("show-config", "LOG-0001"))

    def test_login_limited_to_one_site(self):
        import http.client
        self.assertEqual(server_mod.parse_user_sites(" tech:adab, ops:adab,ops:villa , typo:Adab, alone ,, :adab"),
                         {"tech": {"adab"}, "ops": {"adab", "villa"}, "typo": set(), "alone": set()})
        self.manage("add-site", "villa", "--name", "Villa")
        out = self.manage("add-device", "villa", "LOG-0002")
        token2 = [ln for ln in out.splitlines() if ln.startswith("TOKEN")][0].split(": ", 1)[1]
        server_mod.Handler.user_sites = server_mod.parse_user_sites("tech:adab, typo:Adab")
        server_mod.Handler.admin_users = "julien, tech"
        self.addCleanup(setattr, server_mod.Handler, "user_sites", {})
        self.addCleanup(setattr, server_mod.Handler, "admin_users", "")
        tech, owner = {"X-Auth-User": "tech"}, {"X-Auth-User": "julien"}
        post = dict(tech, **{"X-Requested-With": "arkan"})

        def raw(path, who):   # without following redirects
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            c.request("GET", path, headers=who)
            r = c.getresponse()
            r.read()
            c.close()
            return r.status, r.getheader("Location")

        # Pages: the list of all sites and another site's page send the login to its own site.
        self.assertEqual(raw("/live/", tech), (302, "/live/adab/"))
        self.assertEqual(raw("/live", tech), (302, "/live/adab/"))
        self.assertEqual(raw("/live/villa/", tech), (302, "/live/adab/"))
        self.assertEqual(raw("/live/adab/", tech)[0], 200)
        self.assertEqual(raw("/live/_ui/arkan-ui.css", tech)[0], 200)
        self.assertEqual(raw("/live/", owner)[0], 200)                       # not in USER_SITES: every site
        self.assertEqual(raw("/live/", {"X-Auth-User": "typo"})[0], 403)      # bad site name: no site, never all
        # Lists and the login's own description.
        self.assertEqual(list(json.loads(self.req("GET", "/api/v1/status", headers=tech)[1])["sites"]), ["adab"])
        self.assertEqual(sorted(json.loads(self.req("GET", "/api/v1/status", headers=owner)[1])["sites"]), ["adab", "villa"])
        self.assertEqual(json.loads(self.req("GET", "/api/v1/status", headers={"X-Auth-User": "typo"})[1])["sites"], {})
        me = json.loads(self.req("GET", "/api/v1/admin/me", headers=tech)[1])
        self.assertEqual((me["user"], me["admin"], me["sites"]), ("tech", True, ["adab"]))
        self.assertIsNone(json.loads(self.req("GET", "/api/v1/admin/me", headers=owner)[1])["sites"])
        # Every site API: the login's site yes, the other no.
        for p in ("/api/v1/live/{}", "/api/v1/live/{}/day/2026-11-10", "/api/v1/alarms/{}", "/api/v1/versions/{}",
                  "/api/v1/history/{}", "/api/v1/history/{}/day/2026-11-10", "/api/v1/quality/{}",
                  "/api/v1/quality/{}/day/2026-11-10", "/api/v1/weather/{}", "/api/v1/weather/{}/log"):
            self.assertEqual(self.req("GET", p.format("villa"), headers=tech)[0], 403, p)
            self.assertEqual(self.req("GET", p.format("adab"), headers=tech)[0], 200, p)
            self.assertEqual(self.req("GET", p.format("villa"), headers=owner)[0], 200, p)
        # The CSV of the original records is a site API too (404 = allowed, no records in that period).
        self.assertEqual(self.req("GET", "/api/v1/records/villa", headers=tech)[0], 403)
        self.assertIn(self.req("GET", "/api/v1/records/adab", headers=tech)[0], (200, 404))
        self.assertIn(self.req("GET", "/api/v1/records/villa", headers=owner)[0], (200, 404))
        # Logger pages and actions: only the loggers of the login's site, firmware included (ADMIN_USERS).
        self.assertEqual(self.req("GET", "/api/v1/admin/registers/LOG-0002", headers=tech)[0], 403)
        self.assertEqual(self.req("GET", "/api/v1/admin/registers/LOG-0001", headers=tech)[0], 200)
        self.assertEqual(self.req("GET", "/api/v1/admin/registers/LOG-9999", headers=tech)[0], 404)
        self.assertEqual(self.req("GET", "/api/v1/admin/fw/LOG-0002", headers=tech)[0], 403)
        self.assertEqual(self.req("GET", "/api/v1/admin/fw/LOG-0001", headers=tech)[0], 200)
        good = json.dumps({"csv": "name,fc,addr,type,scale,ct,agg\nv1,3,0x0000,u16,0.1,0,minmax\n"})
        self.assertEqual(self.req("POST", "/api/v1/admin/registers/LOG-0002/check", good, ctype="application/json",
                                  headers=tech)[0], 403)
        self.assertEqual(self.req("POST", "/api/v1/admin/registers/LOG-0002", good, ctype="application/json",
                                  headers=tech)[0], 403)
        self.assertEqual(self.req("POST", "/api/v1/admin/registers/LOG-0001/check", good, ctype="application/json",
                                  headers=tech)[0], 200)
        self.assertEqual(self.req("POST", "/api/v1/admin/meter-settings/LOG-0002", json.dumps({"mb_baud": "9600"}),
                                  ctype="application/json", headers=tech)[0], 403)
        self.assertEqual(self.req("POST", "/api/v1/admin/fw/LOG-0002/cancel", "{}", ctype="application/json",
                                  headers=post)[0], 403)
        self.assertEqual(self.req("POST", "/api/v1/admin/fw/LOG-0001/cancel", "{}", ctype="application/json",
                                  headers=post)[0], 200)
        self.assertEqual(self.req("POST", "/api/v1/admin/fw/LOG-0002/cancel", "{}", ctype="application/json",
                                  headers=dict(owner, **{"X-Requested-With": "arkan"}))[0], 200)
        # The loggers themselves are not concerned (no web login on their paths).
        snap = json.dumps({"ts": ts(0), "values": {"EM01_p": 1}})
        self.assertEqual(self.req("POST", "/api/v1/live", snap, token2, "application/json")[0], 204)

    def test_register_table_page_to_logger(self):
        good = "name,fc,addr,type,scale,ct,agg\nv1,3,0x0000,u16,0.1,0,minmax\ne,3,24,U32,0.01,0,last\n"
        code, _ = self.req("GET", "/api/v1/registers", token=self.token)
        self.assertEqual(code, 204)                                         # nothing sent yet
        code, body = self.req("GET", "/live/adab/register")                 # now a page of the site: /live/adab/#register
        self.assertEqual(code, 200)
        self.assertIn("function registerView", body)
        self.assertEqual(self.req("GET", "/live/adab/register/")[0], 200)
        self.assertEqual(self.req("GET", "/registers/LOG-0001/")[0], 404)
        code, body = self.req("GET", "/api/v1/admin/registers/LOG-0001")
        self.assertEqual(json.loads(body)["state"], "none")
        # admin POSTs: JSON only, same origin only, known logger only
        code, _ = self.req("POST", "/api/v1/admin/registers/LOG-0001", json.dumps({"csv": good}), ctype="text/plain")
        self.assertEqual(code, 415)
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/admin/registers/LOG-0001", method="POST",
                                   data=json.dumps({"csv": good}).encode(),
                                   headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r, timeout=5)
        self.assertEqual(cm.exception.code, 403)
        code, _ = self.req("POST", "/api/v1/admin/registers/LOG-9999", json.dumps({"csv": good}), ctype="application/json")
        self.assertEqual(code, 404)
        # check: errors refuse, nothing saved
        bad = good + "v1,5,0x0001,u64,0,2,avg\n"
        code, body = self.req("POST", "/api/v1/admin/registers/LOG-0001/check", json.dumps({"csv": bad}),
                              ctype="application/json")
        j = json.loads(body)
        self.assertFalse(j["ok"])
        self.assertIn("already on line", j["errors"][0])
        code, body = self.req("POST", "/api/v1/admin/registers/LOG-0001", json.dumps({"csv": bad}), ctype="application/json")
        self.assertEqual(code, 400)
        code, _ = self.req("GET", "/api/v1/registers", token=self.token)
        self.assertEqual(code, 204)
        # send a good table: normalised, versioned, served to the logger only with its token
        code, body = self.req("POST", "/api/v1/admin/registers/LOG-0001",
                              json.dumps({"csv": good, "comment": "bench check"}), ctype="application/json")
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)["version"], 1)
        code, _ = self.req("GET", "/api/v1/registers")
        self.assertEqual(code, 401)
        code, body = self.req("GET", "/api/v1/registers", token=self.token)
        dev = json.loads(body)
        self.assertEqual((dev["version"], dev["builtin"]), (1, False))
        self.assertTrue(dev["csv"].startswith("# register table version 1"))
        self.assertIn("e,3,0x0018,u32,0.01,0,last", dev["csv"])
        self.assertEqual(json.loads(self.req("GET", "/api/v1/admin/registers/LOG-0001")[1])["state"], "waiting")
        # old firmware: reports without reg_version
        self.req("POST", "/api/v1/config/report", json.dumps({"fw": "0.3.0", "settings": {}}), self.token,
                 "application/json")
        self.assertEqual(json.loads(self.req("GET", "/api/v1/admin/registers/LOG-0001")[1])["state"], "unsupported")
        # the logger applies it and reports the table it reads (printed by meter::describeTable)
        logger_table = "name,fc,addr,type,scale,ct,agg\nv1,3,0x0000,u16,0.1,0,minmax\ne,3,0x0018,u32,0.01,0,last\n"
        rep = {"fw": "0.4.0", "cfg_version": 0, "reg_version": 1, "reg_source": "sd", "registers": logger_table,
               "settings": {"meters": "EM01:1", "mb_baud": "9600", "mb_format": "8N1", "ct_mult": "1"}}
        self.req("POST", "/api/v1/config/report", json.dumps(rep), self.token, "application/json")
        view = json.loads(self.req("GET", "/api/v1/admin/registers/LOG-0001")[1])
        self.assertEqual(view["state"], "applied")
        self.assertEqual(view["reported"]["settings"]["mb_baud"], "9600")
        # the SD card changed under it: the page says so
        rep["registers"] = logger_table.replace("0.1,0", "1,0")
        self.req("POST", "/api/v1/config/report", json.dumps(rep), self.token, "application/json")
        self.assertEqual(json.loads(self.req("GET", "/api/v1/admin/registers/LOG-0001")[1])["state"], "differs")
        # back to the built-in table, then a refused version
        code, body = self.req("POST", "/api/v1/admin/registers/LOG-0001", json.dumps({"builtin": True}),
                              ctype="application/json")
        self.assertEqual(json.loads(body)["version"], 2)
        dev = json.loads(self.req("GET", "/api/v1/registers", token=self.token)[1])
        self.assertEqual((dev["version"], dev["builtin"], dev["csv"]), (2, True, None))
        rep.update({"reg_refused": 2, "reg_error": "no working SD card"})
        self.req("POST", "/api/v1/config/report", json.dumps(rep), self.token, "application/json")
        view = json.loads(self.req("GET", "/api/v1/admin/registers/LOG-0001")[1])
        self.assertEqual(view["state"], "refused")
        self.assertEqual([h["version"] for h in view["history"]], [2, 1])
        # meter link settings: checked, then the usual remote settings
        code, body = self.req("POST", "/api/v1/admin/meter-settings/LOG-0001",
                              json.dumps({"mb_baud": "9601", "meters": "EM01:300"}), ctype="application/json")
        self.assertEqual(code, 400)
        self.assertEqual(len(json.loads(body)["errors"]), 2)
        code, _ = self.req("POST", "/api/v1/admin/meter-settings/LOG-0001",
                           json.dumps({"mb_baud": "19200", "mb_format": "8e1", "wifi_ssid": "x"}), ctype="application/json")
        self.assertEqual(code, 200)
        code, body = self.req("GET", "/api/v1/config", token=self.token)
        self.assertEqual(json.loads(body)["settings"], {"mb_baud": "19200", "mb_format": "8E1"})
        # the command line does the same
        f = os.path.join(self.data, "regs.csv")
        with open(f, "w") as fh:
            fh.write(good)
        self.assertIn("version 3", self.manage("set-registers", "LOG-0001", f, "--comment", "cli"))
        self.assertIn("REFUSED version 2", self.manage("show-registers", "LOG-0001"))
        with open(f, "w") as fh:
            fh.write(bad)
        with self.assertRaises(subprocess.CalledProcessError):
            self.manage("set-registers", "LOG-0001", f)

    def test_daily_backfill_export(self):
        base = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)   # 23:00 WITA
        rows = [row((base + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ"), e=1000 + m * 0.5)
                for m in range(120) if m != 30]                      # one missing minute                                 # until 00:59 WITA on the 7th
        sd = os.path.join(self.data, "sdcopy", "data", "2026", "11")
        os.makedirs(sd)
        with open(os.path.join(sd, "2026-11-06.csv"), "w") as f:
            f.write(HEADER + "\n" + "\n".join(rows) + "\n")
        out = self.manage("backfill", "adab", "LOG-0001", os.path.join(self.data, "sdcopy"))
        self.assertIn("119 new row(s)", out)
        self.manage("daily", "adab")
        with open(os.path.join(self.data, "sites", "adab", "daily.csv")) as f:
            lines = f.read().splitlines()
        hdr = lines[0].split(",")
        d7 = dict(zip(hdr, lines[2].split(",")))
        self.assertEqual(d7["date"], "2026-11-07")
        self.assertIn("dips", hdr)
        self.assertEqual(d7["minutes"], "60")
        self.assertEqual(float(d7["EM01_e_delta"]), 30.0)   # 60 minutes x 0.5 kWh, from the 6th's last reading
        out = self.manage("export-oed", "adab", "--out", os.path.join(self.data, "oed"))
        with open(os.path.join(self.data, "oed", "adab-EM01-energy.csv")) as f:
            oed = f.read().splitlines()
        self.assertEqual(oed[0], "reading,start_timestamp,end_timestamp")
        self.assertEqual(oed[1], "1000.00,2026-11-06 23:00:00,2026-11-06 23:01:00")
        self.assertEqual(oed[2], "1000.50,2026-11-06 23:01:00,2026-11-06 23:02:00")   # contiguous chain
        self.assertEqual(oed[31], "1015.50,2026-11-06 23:30:00,2026-11-06 23:32:00")  # minute 30 missing: no hole

    def test_archive_test_period(self):
        def read(*p):
            with open(os.path.join(*p), encoding="utf-8") as f:
                return f.read()

        cut = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)   # 17:00 WITA: the test period ends
        mk = lambda m: (cut + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")   # noqa: E731
        low = HEADER.replace("EM01_v1,", "EM01_v1,EM01_v1_min,")
        rowv = lambda m, v: f"{mk(m)},{v},{v - 1}" + row(mk(m))[len(mk(m)) + 6:]   # noqa: E731
        rows = [rowv(m, 180 if -200 <= m < -180 or 30 <= m < 50 else 231) for m in range(-1500, 60)]
        for i in range(0, len(rows), 60):
            self.req("POST", "/api/v1/ingest", low + "\n" + "\n".join(rows[i:i + 60]) + "\n", token=self.token)
        dd = os.path.join(self.data, "sites", "adab", "LOG-0001")
        os.makedirs(os.path.join(dd, "live"), exist_ok=True)
        with open(os.path.join(dd, "live", "2026-11-07.jsonl"), "w") as f:
            f.write("".join(json.dumps({"recv": mk(m), "values": {}}) + "\n" for m in (-10, -5, 0, 5)))
        state = json.loads(read(dd, "alarm-state.json"))
        state["alarms"]["A01"] = {"active": True, "since": mk(-100)}   # offline during the test period
        with open(os.path.join(dd, "alarm-state.json"), "w") as f:
            json.dump(state, f)
        self.manage("daily", "adab")
        before = sorted(os.path.join(d, f) for d, _, fs in os.walk(self.data) for f in fs)
        args = [sys.executable, MANAGE, "--data", self.data, "archive", "adab", "--before", "2026-11-07 17:00"]
        env = dict(os.environ, PORT=str(self.port))
        out = subprocess.run(args, capture_output=True, text=True, env=env, check=True).stdout
        self.assertIn("= 2026-11-07T09:00:00Z", out)
        self.assertIn("1500 row(s) moved (2026-11-06 to 2026-11-07), 1 day file(s) whole; 2026-11-07: 60 row(s)", out)
        self.assertEqual(before, sorted(os.path.join(d, f) for d, _, fs in os.walk(self.data) for f in fs))
        r = subprocess.run(args + ["--apply"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("stop it first", r.stderr)   # the service of this test answers on PORT
        env["PORT"] = "1"
        out = subprocess.run(args + ["--apply"], capture_output=True, text=True, env=env, check=True).stdout
        self.assertIn("Done.", out)
        arch = os.path.join(self.data, "archive", "adab-before-2026-11-07T1700")
        a_dd = os.path.join(arch, "sites", "adab", "LOG-0001")
        kept = read(dd, "raw", "2026", "11", "2026-11-07.csv").splitlines()
        moved = read(a_dd, "raw", "2026", "11", "2026-11-07.csv").splitlines()
        self.assertEqual((kept[0], moved[0]), (low, low))
        self.assertEqual((kept[1][:20], kept[-1][:20], len(kept)), (mk(0), mk(59), 61))
        self.assertEqual((moved[1][:20], moved[-1][:20]), ("2026-11-07T00:00:00Z", mk(-1)))
        self.assertFalse(os.path.exists(os.path.join(dd, "raw", "2026", "11", "2026-11-06.csv")))
        self.assertTrue(os.path.exists(os.path.join(a_dd, "raw", "2026", "11", "2026-11-06.csv")))
        self.assertEqual([json.loads(x)["recv"] for x in read(dd, "live", "2026-11-07.jsonl").splitlines()],
                         [mk(0), mk(5)])
        self.assertEqual(len(read(a_dd, "live", "2026-11-07.jsonl").splitlines()), 2)
        # the alarm log: only the undervoltage after the cut, rebuilt from the records kept
        log = [ln.split(",") for ln in read(self.data, "sites", "adab", "alarms", "2026.csv").splitlines()[1:]]
        self.assertTrue(log and all(x[0] >= mk(0) for x in log))
        self.assertIn("A05", {x[3] for x in log})
        old_log = read(arch, "sites", "adab", "alarms", "2026.csv").splitlines()[1:]
        self.assertTrue(old_log and all(ln.split(",")[0] < mk(0) for ln in old_log))
        self.assertNotIn("A01", json.loads(read(dd, "alarm-state.json"))["alarms"])   # its start line is archived
        self.assertEqual([ln.split(",")[:3] for ln in read(self.data, "sites", "adab", "daily.csv").splitlines()[1:]],
                         [["2026-11-07", "LOG-0001", "60"]])
        self.assertEqual(json.loads(read(self.data, "sites", "adab", "site.json"))["records_from"], mk(0))
        self.assertIn('"kind": "archive"', read(dd, "events.jsonl").splitlines()[-1])
        self.assertIn("records from 2026-11-07T09:00:00Z", self.manage("list"))
        # the archive is a data folder of its own: the tools read it with --data
        out = subprocess.run([sys.executable, MANAGE, "--data", arch, "list"], check=True, capture_output=True,
                             text=True).stdout
        self.assertIn("LOG-0001: fw None, last record 2026-11-07T08:59:00Z", out)
        # the logger resends a test row: 200, not stored; the API has nothing before the cut
        code, body = self.req("POST", "/api/v1/ingest", low + "\n" + rows[0] + "\n", token=self.token)
        self.assertEqual((code, json.loads(body)["stored"], json.loads(body)["before_start"]), (200, 0, 1))
        self.assertEqual(self.req("GET", "/api/v1/records/adab?from=2026-11-06&to=2026-11-06")[0], 404)
        # twice: refused, nothing changed
        r = subprocess.run(args + ["--apply"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("exists already", r.stderr)


if __name__ == "__main__":
    unittest.main()


class MeterLinkTest(unittest.TestCase):
    """meter_links: the Modbus link line of the open alarms card (server.py)."""

    def snaps(self, pattern, t0=1_800_000_000):
        """One 15 s snapshot per character: "1" = the meter answered (values), "0" = no value."""
        return [{"ts": server_mod._iso(t0 + 15 * i), "values": {"EM01_p": 5.0} if c == "1" else {"TH1_t": 30.0}}
                for i, c in enumerate(pattern)], t0 + 15 * (len(pattern) - 1)

    def test_from_the_logger(self):
        last = {"ts": "2026-11-10T03:00:00Z", "sys": {"up_s": 600, "mb": {"EM01": {"ok": True, "id": 1, "req": 4, "req_ok": 3,
                                                                                    "err": "illegal_address"}}}}
        (m,) = server_mod.meter_links(last, 5, [], now=server_mod._epoch("2026-11-10T03:00:05Z"))
        self.assertEqual((m["state"], m["req_ok"], m["err"], m["stale"]), ("ok", 3, "illegal_address", False))
        # no "since" (the clock was not set at the change): the logger's start, from up_s
        self.assertEqual((m["since"], m["since_boot"], m["for_s"]), ("2026-11-10T02:50:00Z", True, 605))

    def test_stale_and_not_configured(self):
        last = {"ts": "2026-11-10T03:00:00Z", "sys": {"mb": {"EM01": {"ok": True, "since": "2026-11-10T01:00:00Z"}}}}
        links = server_mod.meter_links(last, 300, [], expected=["EM01", "EM02"])
        self.assertEqual([(m["meter"], m["state"], m["stale"]) for m in links],
                         [("EM01", "ok", True), ("EM02", "not_configured", True)])
        # firmware 0.5.0 with no meter in its settings: sys.mb is empty
        (m,) = server_mod.meter_links({"sys": {"mb": {}}}, 5, [], expected=["EM01"])
        self.assertEqual((m["state"], m["source"]), ("not_configured", "logger"))

    def test_older_firmware_from_the_values(self):
        hist, now = self.snaps("1111000")
        (m,) = server_mod.meter_links(hist[-1], 5, hist, expected=["EM01"], now=now)
        self.assertEqual((m["state"], m["source"], m["fail_run"]), ("no_answer", "values", 3))
        self.assertEqual((m["since"], m["last_ok"]), (hist[4]["ts"], hist[3]["ts"]))
        hist, now = self.snaps("0011")
        (m,) = server_mod.meter_links(hist[-1], 5, hist, now=now)
        self.assertEqual((m["state"], m["since"], m["for_s"], m["last_ok"]), ("ok", hist[2]["ts"], 15, hist[3]["ts"]))
        hist, now = self.snaps("111")
        self.assertIsNone(server_mod.meter_links(hist[-1], 5, hist, now=now)[0]["since"])   # the whole 60 minutes
        # a meter of site.json that sent nothing in the 60 minutes
        hist, now = self.snaps("000")
        (m,) = server_mod.meter_links(hist[-1], 5, hist, expected=["EM01"], now=now)
        self.assertEqual((m["state"], m["last_ok"]), ("no_answer", None))


class RegisterTableTest(unittest.TestCase):
    def test_builtin_table_passes(self):
        # the firmware's built-in table, as printed by the console command "regs"
        text = """name,fc,addr,type,scale,ct,agg
v1,3,0x0000,u16,0.1,0,minmax
v2,3,0x0001,u16,0.1,0,minmax
v3,3,0x0002,u16,0.1,0,minmax
v12,3,0x0003,u16,0.1,0,minmax
v23,3,0x0004,u16,0.1,0,minmax
v31,3,0x0005,u16,0.1,0,minmax
i1,3,0x0006,u16,0.001,1,minmax
i2,3,0x0007,u16,0.001,1,minmax
i3,3,0x0008,u16,0.001,1,minmax
f,3,0x0009,u16,0.01,0,minmax
p1,3,0x000A,s16,0.001,1,minmax
p2,3,0x000B,s16,0.001,1,minmax
p3,3,0x000C,s16,0.001,1,minmax
p,3,0x000D,s16,0.001,1,minmax
q,3,0x000E,s16,0.001,1,minmax
s,3,0x000F,u16,0.001,1,minmax
pf,3,0x0010,s16,0.001,0,minmax
e,3,0x0018,u32,0.01,0,last
eq,3,0x001A,u32,0.01,0,last
"""
        rows, errors, warnings = registers.parse(text)
        self.assertEqual((len(rows), errors, warnings), (19, [], []))
        again, _, _ = registers.parse(registers.to_csv(rows))
        self.assertTrue(registers.same(rows, again))

    def test_errors_and_warnings(self):
        rows, errors, warnings = registers.parse("# comment\n\nTOOLONGNAME,3,0,u16,1,0,mean\np,3,40014,s16,1,0\n"
                                                 "x,4,0xFFFF,u32,1,0,mean\ny,3,zz,f32,abc,yes,sum\n")
        self.assertEqual(len(errors), 3)
        self.assertIn("line 3: name", errors[0])
        self.assertIn("past 0xFFFF", errors[1])
        self.assertIn("addr 'zz'", errors[2])
        self.assertTrue(any("PLC number" in w for w in warnings))
        self.assertTrue(any("not in the table" in w for w in warnings))
        self.assertEqual(rows[0]["agg"], "mean")                     # agg may be left out
        many = "\n".join(f"r{i},3,{i},u16,1,0,mean" for i in range(33))
        self.assertIn("at most 32", registers.parse(many)[1][-1])
        self.assertEqual(registers.parse("")[1], ["no register line"])
