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

    def req(self, method, path, body=None, token=None, ctype="text/csv"):
        headers = {"Content-Type": ctype}
        if token:
            headers["Authorization"] = "Bearer " + token
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                   data=body.encode() if body is not None else None, headers=headers)
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
        code, body = self.req("GET", "/api/v1/status")
        self.assertEqual(json.loads(body)["sites"]["adab"]["LOG-0001"]["last_record"], ts(1))
        code, body = self.req("GET", "/live/adab/")
        self.assertEqual(code, 200)
        self.assertIn("<title>Live</title>", body)

    def test_ota(self):
        code, _ = self.req("GET", "/api/v1/ota?fw=0.1.0", token=self.token)
        self.assertEqual(code, 204)
        fw = os.path.join(self.data, "fw.bin")
        with open(fw, "wb") as f:
            f.write(b"\xe9" + b"x" * 1000)
        self.manage("publish-fw", fw, "--version", "0.1.1")
        code, body = self.req("GET", "/api/v1/ota?fw=0.1.0", token=self.token)
        self.assertEqual(code, 200)
        url = json.loads(body)["url"]
        code, body = self.req("GET", url, token=self.token)
        self.assertEqual(code, 200)
        code, _ = self.req("GET", "/api/v1/ota?fw=0.1.1", token=self.token)
        self.assertEqual(code, 204)
        code, _ = self.req("GET", "/api/v1/ota?fw=0.2.0", token=self.token)   # newer, flashed by hand
        self.assertEqual(code, 204)                                           # never downgraded
        with self.assertRaises(subprocess.CalledProcessError):
            self.manage("publish-fw", fw, "--version", "0.1.1")               # no silent overwrite
        self.manage("publish-fw", fw, "--version", "0.1.1", "--force")        # deliberate step back
        code, _ = self.req("GET", "/api/v1/ota?fw=0.2.0", token=self.token)
        self.assertEqual(code, 200)

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

    def test_register_table_page_to_logger(self):
        good = "name,fc,addr,type,scale,ct,agg\nv1,3,0x0000,u16,0.1,0,minmax\ne,3,24,U32,0.01,0,last\n"
        code, _ = self.req("GET", "/api/v1/registers", token=self.token)
        self.assertEqual(code, 204)                                         # nothing sent yet
        code, body = self.req("GET", "/registers/LOG-0001/")
        self.assertEqual(code, 200)
        self.assertIn("<title>Meter registers</title>", body)
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


if __name__ == "__main__":
    unittest.main()


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
