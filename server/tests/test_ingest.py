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

    def test_daily_backfill_export(self):
        base = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)   # 23:00 WITA
        rows = [row((base + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ"), e=1000 + m * 0.5)
                for m in range(120)]                                 # until 00:59 WITA on the 7th
        sd = os.path.join(self.data, "sdcopy", "data", "2026", "11")
        os.makedirs(sd)
        with open(os.path.join(sd, "2026-11-06.csv"), "w") as f:
            f.write(HEADER + "\n" + "\n".join(rows) + "\n")
        out = self.manage("backfill", "adab", "LOG-0001", os.path.join(self.data, "sdcopy"))
        self.assertIn("120 new row(s)", out)
        self.manage("daily", "adab")
        with open(os.path.join(self.data, "sites", "adab", "daily.csv")) as f:
            lines = f.read().splitlines()
        hdr = lines[0].split(",")
        d7 = dict(zip(hdr, lines[2].split(",")))
        self.assertEqual(d7["date"], "2026-11-07")
        self.assertEqual(d7["minutes"], "60")
        self.assertEqual(float(d7["EM01_e_delta"]), 30.0)   # 60 minutes x 0.5 kWh, from the 6th's last reading
        out = self.manage("export-oed", "adab", "--out", os.path.join(self.data, "oed"))
        with open(os.path.join(self.data, "oed", "adab-EM01-energy.csv")) as f:
            oed = f.read().splitlines()
        self.assertEqual(oed[0], "reading,start_timestamp,end_timestamp")
        self.assertEqual(oed[1], "1000.00,2026-11-06 23:00:00,2026-11-06 23:01:00")


if __name__ == "__main__":
    unittest.main()
