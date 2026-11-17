"""Tests of the meters read by hand (app/manual.py, the /api/v1/manual/ routes, manage.py manual-meter and import-readings).
Run: python3 -m unittest discover -s server/tests"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import manual  # noqa: E402
import server as server_mod  # noqa: E402
from server import make_server  # noqa: E402
from store import DataStore, atomic_write  # noqa: E402

server_mod.Handler.log_message = lambda *a: None
MANAGE = os.path.join(HERE, "..", "tools", "manage.py")
NOW = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)      # Tue 10 Nov 13:00 hotel time (UTC+8)
WATER = {"id": "water", "name": "Water", "kind": "water", "unit": "m³", "decimals": 3, "due_h": 26}
PM2 = {"id": "pm2", "name": "Power meter 2", "kind": "power", "unit": "kWh", "decimals": 1, "compare": "EM01"}


def site(store, meters=(WATER, PM2)):
    os.makedirs(store.site_dir("adab"), exist_ok=True)
    atomic_write(os.path.join(store.site_dir("adab"), "site.json"),
                 json.dumps({"name": "Adab hotel", "utc_offset_h": 8, "manual_meters": list(meters)}))


class ManualRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = DataStore(self.tmp.name)
        site(self.s)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, time, value, user="wayan", meter="water", **kw):
        return manual.add(self.s, "adab", meter, dict(kw, time=time, value=value), user, now=NOW)

    def days(self, meter="water", n=14):
        return {d["date"]: d for d in manual.view(self.s, "adab", n, now=NOW, only=meter)["meters"][0]["days"]}

    def test_values_as_typed(self):
        for typed in ("18921.334", "18921,334", "18 921,334", "18.921,334", "18,921.334", "18 921.334"):
            self.assertEqual(manual.parse_value(typed)[0], 18921.334, typed)
        self.assertEqual(manual.parse_value("1.234.567"), (1234567.0, 0, "1234567"))
        self.assertIsNone(manual.parse_value("  "))
        self.assertEqual(manual.parse_value("1.035,250")[0], 1035.25)
        for bad in ("12a", "-5", "1..2", "abc", "1.23.456", "12,34,567", "1,2.3", "1.2345,6"):
            with self.assertRaises(manual.ReadingError):
                manual.parse_value(bad)
        self.assertEqual(manual.fv(20096.87, 3), "20 096.870")

    def test_meters_from_site_json(self):
        prof = {"manual_meters": [WATER, {"id": "now"}, {"id": "Bad id"}, dict(WATER), {"id": "gas", "kind": "gas"}, "x"]}
        ms = manual.meters(prof)
        self.assertEqual([m["id"] for m in ms], ["water", "gas"])           # page names, bad ids, duplicates left out
        self.assertEqual((ms[1]["unit"], ms[1]["decimals"], ms[1]["due_h"]), ("kWh", 1, 26.0))

    def test_measured_spread_and_today(self):
        # A round about 08:00, none on Sunday 1 November: Saturday to Monday is spread (the mockup's example)
        for t, v in [("2026-10-30T08:11", "19654.146"), ("2026-10-31T07:54", "19692.179"), ("2026-11-02T07:42", "19770.740"),
                     ("2026-11-03T07:48", "19806.842"), ("2026-11-04T07:55", "19845.461"), ("2026-11-10T07:44", "20096.870")]:
            self.assertEqual(self.add(t, v)[0], 200, t)
        d = self.days()
        self.assertEqual(d["2026-10-30"]["how"], "none")                     # before the first reading: part of the day only
        self.assertEqual(d["2026-10-31"]["how"], "spread")                   # its evening is in the Saturday-Monday interval
        self.assertEqual((d["2026-11-01"]["how"], d["2026-11-01"]["use"]), ("spread", 39.445))
        self.assertEqual(d["2026-11-03"]["how"], "measured")
        self.assertAlmostEqual(d["2026-11-03"]["use"], 37.626, places=3)
        self.assertEqual(d["2026-11-04"]["how"], "spread")                   # 4 to 10 November: 6 days apart, spread
        self.assertEqual(d["2026-11-10"]["how"], "so_far")                   # today, 00:00 to 07:44
        self.assertEqual(d["2026-11-10"]["until"], "2026-11-10 07:44")
        self.assertEqual(sum(1 for x in d.values() if x["how"] == "none"), 3)   # 28, 29, 30 October
        # The days add up to the readings: 31 Oct 00:00 (on the line between 30 Oct 08:11 and 31 Oct 07:54) to today 07:44
        at_midnight = 19654.146 + (19692.179 - 19654.146) * (15 * 60 + 49) / (23 * 60 + 43)
        total = sum(x["use"] for k, x in d.items() if k >= "2026-10-31")
        self.assertAlmostEqual(total, 20096.870 - at_midnight, places=2)

    def test_gap_and_reset(self):
        self.add("2026-10-20T08:00", "100")
        self.add("2026-10-30T08:00", "500")                                  # 10 days apart: no figure per day
        self.add("2026-10-31T08:00", "540")
        self.add("2026-11-01T08:00", "12", reset=True)                       # meter replaced, old figure unknown
        self.add("2026-11-02T08:00", "52")
        self.add("2026-11-03T08:00", "5", reset=True, old="95")              # replaced again, old figure known: counted
        self.add("2026-11-04T08:00", "45")
        d = self.days(n=31)
        self.assertEqual(d["2026-10-25"]["how"], "none")
        self.assertEqual(d["2026-10-31"]["how"], "none")                     # the interval up to the reset is not known
        self.assertEqual(d["2026-11-02"]["how"], "measured")
        self.assertAlmostEqual(d["2026-11-02"]["use"], 40 * 8 / 24 + 43 * 16 / 24, places=3)
        self.assertEqual(d["2026-11-03"]["how"], "measured")
        self.assertAlmostEqual(d["2026-11-03"]["use"], 43 * 8 / 24 + 40 * 16 / 24, places=3)
        rs = {r["id"]: r for r in manual.view(self.s, "adab", 31, now=NOW)["meters"][0]["readings"]}
        self.assertTrue(rs["r4"]["reset"] and rs["r4"]["use"] is None and rs["r6"]["old"] == 95)

    def test_checks(self):
        self.assertEqual(self.add("2026-11-08T08:00", "1000.000")[0], 200)
        self.assertEqual(self.add("2026-11-09T08:00", "1040.000")[0], 200)
        code, res = self.add("2026-11-10T08:00", "999.5")
        self.assertEqual(code, 400)
        self.assertIn("Lower than the reading of Mon 9 Nov 08:00", res["error"])
        self.assertIn("in the future", self.add("2026-11-10T14:00", "1100")[1]["error"])
        self.assertIn("already a reading", self.add("2026-11-09T08:00", "1041")[1]["error"])
        self.assertIn("Higher than the later reading", self.add("2026-11-08T20:00", "1050")[1]["error"])
        self.assertEqual(self.add("2026-11-08T20:00", "1020")[0], 200)       # a missed reading, in between: fine
        self.assertEqual(self.add("2026-11-10T09:00", "")[1]["error"], "no figure")
        self.assertIn("more than 31 days", self.add("2026-09-01T08:00", "10")[1]["error"])
        self.assertEqual(manual.add(self.s, "adab", "water", {"time": "2026-09-01T08:00", "value": "10"}, "x", now=NOW,
                                    source="import")[0], 200)                # the import has no such limit
        self.assertTrue(self.add("2026-11-10T08:00", "1080.0001")[1]["warning"].endswith("The meter shows 3 decimals: check the figure."))
        self.assertEqual(manual.add(self.s, "adab", "gas", {"time": "2026-11-10T08:00", "value": "1"}, "x", now=NOW)[0], 404)

    def test_usual_and_high(self):
        v = 5000.0
        for i in range(20, 0, -1):                                          # 20 days of about 40 m³
            v += 40 + (i % 3)
            self.add((NOW + timedelta(hours=8) - timedelta(days=i)).strftime("%Y-%m-%dT08:00"), f"{v:.3f}")
        m = manual.view(self.s, "adab", 14, now=NOW, only="water")["meters"][0]
        self.assertTrue(m["usual"] and 40 <= m["usual"]["lo"] <= m["usual"]["hi"] <= 43)
        code, res = self.add("2026-11-10T08:00", f"{v + 95:.3f}")            # 95 m³ in a day: amber, saved
        self.assertEqual(code, 200)
        self.assertIn("× the usual", res["warning"])
        m = manual.view(self.s, "adab", 14, now=NOW, only="water")["meters"][0]
        self.assertTrue(m["readings"][0]["high"])
        self.assertFalse(m["due"])

    def test_corrections_rights_and_history(self):
        self.add("2026-11-08T08:00", "1000")
        self.add("2026-11-09T08:00", "2040")                                 # typing error, 2040 for 1040
        code, res = manual.change(self.s, "adab", "water", "r2", {"value": "1040", "reason": "typo"}, "tech-adab", False, now=NOW)
        self.assertEqual(code, 403)                                         # someone else, not an admin
        self.assertEqual(manual.change(self.s, "adab", "water", "r2", {"value": "1040"}, "wayan", False, now=NOW)[0], 400)
        self.assertEqual(manual.change(self.s, "adab", "water", "r2", {"value": "1040", "reason": "typo"}, "wayan", False, now=NOW)[0], 200)
        code, _ = manual.change(self.s, "adab", "water", "r1", {"time": "2026-11-08T07:30", "value": "1000", "reason": "time"},
                                "julien", True, now=NOW)                    # an admin corrects someone else's
        self.assertEqual(code, 200)
        rs = {r["id"]: r for r in manual.readings(self.s, "adab", "water")}
        self.assertEqual((rs["r2"]["value"], rs["r1"]["t"]), (1040.0, datetime(2026, 11, 7, 23, 30, tzinfo=timezone.utc)))
        h = rs["r2"]["hist"]
        self.assertEqual([(x["what"], x.get("value"), x["user"]) for x in h], [("entered", 2040.0, "wayan"), ("corrected", 1040.0, "wayan")])
        self.assertEqual(manual.change(self.s, "adab", "water", "r2", {"delete": True, "reason": "double"}, "wayan", False, now=NOW)[0], 200)
        self.assertEqual([r["id"] for r in manual.readings(self.s, "adab", "water")], ["r1"])
        self.assertEqual(manual.change(self.s, "adab", "water", "r2", {"value": "1", "reason": "x"}, "wayan", True, now=NOW)[0], 404)
        with open(manual.path(self.s, "adab", "water"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], ",".join(manual.COLS))
        self.assertEqual([ln.split(",")[3] for ln in lines[1:]], ["add", "add", "correct", "correct", "delete"])   # never rewritten

    def test_half_written_line_is_skipped(self):
        self.add("2026-11-08T08:00", "1000")
        with open(manual.path(self.s, "adab", "water"), "a", encoding="utf-8") as f:
            f.write("9,2026-11-10T05:00:00Z,x,add,r9,2026-11-09T00:00:00Z,10")   # no newline yet
        self.assertEqual(len(manual.readings(self.s, "adab", "water")), 1)

    def test_csv(self):
        self.add("2026-11-08T08:00", "1000", note="first, with a comma")
        self.add("2026-11-09T08:00", "1040")
        v = manual.view(self.s, "adab", 7, now=NOW, only="water")
        days = manual.csv_text(v, "days").splitlines()
        self.assertEqual(days[0], "date,use_m³,how,readings,until")
        self.assertEqual(len(days), 8)
        rd = manual.csv_text(v, "readings").splitlines()
        self.assertEqual(rd[1].split(",")[:3], ["2026-11-08 08:00", "2026-11-08T00:00:00Z", "1000.000"])
        self.assertIn('"first, with a comma"', rd[1])


class ManualHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = self.tmp.name
        self.manage("init")
        self.manage("add-site", "adab", "--name", "Adab hotel")
        self.manage("add-site", "villa", "--name", "Villa")
        self.srv = make_server(self.data, "127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        server_mod.Handler.admin_users = "julien"
        self.addCleanup(setattr, server_mod.Handler, "admin_users", "")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def manage(self, *args, check=True):
        return subprocess.run([sys.executable, MANAGE, "--data", self.data, *args], check=check, capture_output=True, text=True)

    def req(self, method, path, body=None, user="wayan", headers=None):
        h = {"X-Auth-User": user, "X-Requested-With": "arkan", "Content-Type": "application/json"} if user else {}
        h.update(headers or {})
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=data, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                text = resp.read().decode()
                return resp.status, json.loads(text) if resp.headers.get_content_type() == "application/json" else text
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def local(self, hours_ago):
        return (datetime.now(timezone.utc) + timedelta(hours=8) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M")

    def test_manage_meter_and_profile(self):
        self.assertIn("no meter read by hand", self.manage("manual-meter", "adab").stdout)
        self.assertEqual(self.manage("manual-meter", "adab", "readings", check=False).returncode, 1)   # a page name
        out = self.manage("manual-meter", "adab", "water", "--kind", "water", "--unit", "m3", "--long", "Water meter").stdout
        self.assertIn('"unit": "m³"', out)
        self.manage("manual-meter", "adab", "water", "--decimals", "2", "--where", "street side")
        prof = self.req("GET", "/api/v1/live/adab")[1]["profile"]
        self.assertEqual(prof["manual_meters"], [{"id": "water", "name": "Water", "long": "Water meter", "kind": "water",
                                                  "unit": "m³", "decimals": 2, "due_h": 26.0, "where": "street side"}])
        self.assertEqual(self.req("GET", "/api/v1/live/villa")[1]["profile"]["manual_meters"], [])
        self.manage("manual-meter", "adab", "water", "--remove")
        self.assertEqual(self.req("GET", "/api/v1/live/adab")[1]["profile"]["manual_meters"], [])

    def test_enter_view_correct_csv(self):
        self.manage("manual-meter", "adab", "water", "--kind", "water")
        url = "/api/v1/manual/adab/water"
        code, res = self.req("POST", url, {"time": self.local(26), "value": "1000.000", "note": "first"})
        self.assertEqual((code, res["reading"]["id"]), (200, "r1"))
        code, res = self.req("POST", url, {"time": self.local(2), "value": "1.039,5"})
        self.assertEqual((code, res["reading"]["value"]), (200, 1039.5))
        self.assertEqual(self.req("POST", url, {"time": self.local(1), "value": "900"})[0], 400)
        code, j = self.req("GET", "/api/v1/manual/adab?days=7")
        m = j["meters"][0]
        self.assertEqual((code, m["id"], len(m["readings"]), m["last"]["user"], m["due"]), (200, "water", 2, "wayan", False))
        self.assertEqual(len(m["days"]), 7)
        # corrections: not someone else's, but an admin's
        self.assertEqual(self.req("POST", url + "/r2", {"value": "1039.6", "reason": "x"}, user="tech-adab")[0], 403)
        self.assertEqual(self.req("POST", url + "/r2", {"value": "1039.6", "reason": "checked"}, user="julien")[0], 200)
        self.assertEqual(self.req("POST", url + "/r1", {"delete": True, "reason": "test"})[0], 200)
        m = self.req("GET", "/api/v1/manual/adab?days=7")[1]["meters"][0]
        self.assertEqual([(r["id"], r["value"]) for r in m["readings"]], [("r2", 1039.6)])
        self.assertEqual(m["readings"][0]["hist"][-1]["user"], "julien")
        code, text = self.req("GET", "/api/v1/manual/adab/water.csv?what=readings&days=7")
        self.assertEqual(code, 200)
        self.assertTrue(text.startswith("time_local,time_utc,reading_m³"))
        self.assertEqual(self.req("GET", "/api/v1/manual/adab/gas.csv")[0], 404)
        self.assertEqual(self.req("GET", "/api/v1/manual/adab?from=2026-11-10&to=2026-01-01")[0], 400)

    def test_post_protection_and_sites(self):
        self.manage("manual-meter", "adab", "water", "--kind", "water")
        url, body = "/api/v1/manual/adab/water", {"time": self.local(1), "value": "5"}
        self.assertEqual(self.req("POST", url, body, headers={"X-Requested-With": ""})[0], 403)
        self.assertEqual(self.req("POST", url, json.dumps(body).encode(), headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("POST", url, body, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", url, body, user="", headers={"X-Requested-With": "arkan",
                                                                       "Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.req("POST", "/api/v1/manual/nosite/water", body)[0], 404)
        server_mod.Handler.user_sites = server_mod.parse_user_sites("tech-villa:villa")
        self.addCleanup(setattr, server_mod.Handler, "user_sites", {})
        self.assertEqual(self.req("POST", url, body, user="tech-villa")[0], 403)
        self.assertEqual(self.req("GET", "/api/v1/manual/adab", user="tech-villa")[0], 403)
        self.assertEqual(self.req("GET", "/api/v1/manual/villa", user="tech-villa")[0], 200)
        self.assertEqual(self.req("POST", url, body)[0], 200)

    def test_import(self):
        self.manage("manual-meter", "adab", "water", "--kind", "water")
        p = os.path.join(self.data, "sheet.csv")
        with open(p, "w") as f:
            f.write("Date;Time;Reading;Note\n2026-10-01;08:00;500,000;\n2026-10-02;08:05;540,250;leak?\n")
        out = self.manage("import-readings", "adab", "water", p, "--user", "wayan")
        self.assertIn("imported as wayan", out.stdout)
        rs = manual.readings(DataStore(self.data), "adab", "water")
        self.assertEqual([(r["value"], r["user"], r["note"]) for r in rs], [(500.0, "wayan", ""), (540.25, "wayan", "leak?")])
        with open(p, "w") as f:
            f.write("2026-10-03,08:00,600\n2026-10-04,08:00,550\n")
        r = self.manage("import-readings", "adab", "water", p, check=False)
        self.assertEqual(r.returncode, 1)
        r2 = subprocess.run([sys.executable, MANAGE, "--data", self.data, "import-readings", "adab", "water", "-", "--dry-run"],
                            input="2026-10-05,08:00,610\n", capture_output=True, text=True)   # from stdin, as on the VPS
        self.assertIn("1 reading(s) checked", r2.stdout)
        self.assertIn("line 2", r.stderr)
        self.assertEqual(len(manual.readings(DataStore(self.data), "adab", "water")), 2)   # nothing of the bad file


if __name__ == "__main__":
    unittest.main()
