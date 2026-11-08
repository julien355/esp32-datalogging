"""Tests of tools/modbus_sim/modbus_sim.py.  Run: python -m unittest discover -s tools/modbus_sim -v

The serial test needs pyserial and a POSIX pty; it is skipped otherwise.
"""
import io
import os
import re
import select
import struct
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modbus_sim as ms  # noqa: E402

FIRMWARE_METER = os.path.join(ms.REPO, "firmware", "src", "meter.cpp")
FIRMWARE_CONFIG = os.path.join(ms.REPO, "firmware", "include", "config.h")


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def make_meter(profile="proposed", amps=(60.0, 55.0, 70.0), table=None, warn=None):
    layout = ms.load_table(table or ms.PROFILES[profile])
    return ms.SimMeter(layout, ms.Physics(amps=amps), (250, 5), warn=warn)


def check(logger_regs, meter, ct_mult):
    out = io.StringIO()
    n_ok, n = ms.run_check(logger_regs, meter, ct_mult, out=lambda s="": out.write(s + "\n"))
    return n_ok, n, out.getvalue()


class SameAsFirmware(unittest.TestCase):
    """The simulator ports the logger's rules; these fail when the firmware moves away from them."""

    def test_limits(self):
        src = read_text(FIRMWARE_METER)
        m = re.search(r"r\.addr <= b\.start \+ b\.count(?: \+ (\d+))? && end - b\.start <= (\d+)", src)
        self.assertIsNotNone(m, "buildBlocks() changed: update build_blocks() in modbus_sim.py")
        self.assertEqual(int(m.group(1) or 0), ms.MERGE_GAP)
        self.assertEqual(int(m.group(2)), ms.MAX_SPAN)
        cfg = read_text(FIRMWARE_CONFIG)
        self.assertEqual(int(re.search(r"#define MAX_REGS (\d+)", cfg).group(1)), ms.MAX_REGS)

    def test_proposed_table_is_the_built_in_table(self):
        src = read_text(FIRMWARE_METER)
        block = src.split("DEFAULT_TABLE[] = {")[1].split("};")[0]
        built = []
        for n, fc, a, t, sc, ct, agg in re.findall(
                r'\{"(\w+)", (\d), (0x[0-9A-Fa-f]+), (\w+), ([\d.]+), (true|false), (\w+)\}', block):
            built.append((n, int(fc), int(a, 16), t.lower(), float(sc), ct == "true",
                          {"MINMAX": "minmax", "LAST": "last", "MEAN": "mean"}[agg]))
        proposed = [(r.name, r.fc, r.addr, r.type, r.scale, r.ct, r.agg) for r in ms.load_table(ms.PROFILES["proposed"])]
        self.assertEqual(len(built), 19)
        self.assertEqual(built, proposed)


class Basics(unittest.TestCase):
    def test_crc_known_frame(self):
        self.assertEqual(ms.with_crc(bytes([1, 3, 0, 0, 0, 10])), bytes([1, 3, 0, 0, 0, 10, 0xC5, 0xCD]))

    def test_blocks_of_the_proposed_table(self):
        regs = ms.load_table(ms.PROFILES["proposed"])
        self.assertEqual(ms.build_blocks(regs), [(3, 0x0000, 17), (3, 0x0018, 4)])

    def test_blocks_do_not_span_holes_or_function_codes(self):
        # a (0) and b (2) have a hole between them; b (2) and d (3..4) touch; c is on another function code
        regs = ms.parse_table("a,3,0,u16,1,0,mean\nb,3,2,u16,1,0,mean\nc,4,3,u16,1,0,mean\nd,3,3,u32,1,0,mean\n")
        self.assertEqual(ms.build_blocks(regs), [(3, 0, 1), (3, 2, 3), (4, 3, 1)])

    def test_types_round_trip(self):
        cases = [("u16", 1234.5), ("s16", -1234.5), ("u32", 123456.7), ("s32", -123456.7),
                 ("u32sw", 123456.7), ("s32sw", -123456.7), ("f32", -12345.678), ("f32sw", 0.0125)]
        for t, v in cases:
            reg = ms.Reg("x", 3, 0, t, 0.1 if t != "f32" and t != "f32sw" else 1.0, False)
            words = ms.encode(reg, v, 50.0)
            self.assertEqual(len(words), reg.words, t)
            got = ms.decode(reg, words, 1.0)
            self.assertAlmostEqual(got, v, delta=0.06 if reg.scale == 0.1 else abs(v) * 1e-6, msg=t)

    def test_word_order_differs(self):
        a = ms.encode(ms.Reg("x", 3, 0, "u32", 1, False), 0x00010002, 1)
        b = ms.encode(ms.Reg("x", 3, 0, "u32sw", 1, False), 0x00010002, 1)
        self.assertEqual(a, [1, 2])
        self.assertEqual(b, [2, 1])

    def test_ct_flag_divides_in_the_meter_and_multiplies_in_the_logger(self):
        reg = ms.Reg("i1", 3, 6, "u16", 0.001, True)
        words = ms.encode(reg, 60.0, 50.0)
        self.assertEqual(words, [1200])
        self.assertAlmostEqual(ms.decode(reg, words, 50.0), 60.0)

    def test_saturation_is_reported(self):
        warns = []
        reg = ms.Reg("i1", 3, 6, "u16", 0.001, False)
        self.assertEqual(ms.encode(reg, 125.0, 50.0, warns.append), [65535])
        self.assertTrue(warns and "does not fit" in warns[0])

    def test_decimals_like_the_logger(self):
        def dec(scale, t="u16", mean=False):
            return ms.decimals_for(ms.Reg("x", 3, 0, t, scale, False), mean)
        self.assertEqual([dec(x) for x in (1, 0.1, 0.01, 0.001, 0.0001, 0.00001)], [0, 1, 2, 3, 4, 4])
        self.assertEqual(dec(0.001, mean=True), 4)
        self.assertEqual((dec(1, "f32"), dec(1, "f32sw"), dec(0.0001, "f32")), (3, 3, 4))   # floats: at least 3
        self.assertEqual(dec(1, "u32"), 0)

    def test_energy_counts_up_and_speed_scales_it(self):
        p1, p60 = ms.Physics(speed=1), ms.Physics(speed=60)
        for p in (p1, p60):
            p.snapshot(0.0)
        e1, e60 = p1.snapshot(60.0)["e"] - 12345.67, p60.snapshot(60.0)["e"] - 12345.67
        self.assertGreater(e1, 0)
        self.assertAlmostEqual(e60 / e1, 60.0, places=6)


class Table(unittest.TestCase):
    def test_warnings_for_what_the_logger_does_silently(self):
        w = []
        regs = ms.parse_table("\n".join([
            "name,fc,addr,type,scale,ct,agg",
            "# comment",
            "a,3,0x0000,u16,0.1,0,minmax",
            "a,3,0x0001,u16,0.1,0,minmax",       # duplicate name
            "b,3,0016,u16,0.1,0,minmax",         # octal
            "c,3,0x0003,u16,zero,0,minmax",      # scale not a number
            "d,3,0x0004,u99,1,0,minmax",         # bad type
            "e,5,0x0005,u16,1,0,minmax",         # bad function code
            "f,3,0x0006,u16",                    # too few fields
            "g,3,0x0007,u16,1,0,median",         # unknown agg
        ]), w)
        self.assertEqual([r.name for r in regs], ["a", "a", "b", "c", "g"])
        self.assertEqual(regs[2].addr, 14)        # 0016 octal
        self.assertEqual(regs[3].scale, 0.0)
        self.assertEqual(regs[4].agg, "mean")
        text = "\n".join(w)
        for needle in ("appears twice", "OCTAL", "not a number", "bad type", "fewer than 6", "uses mean"):
            self.assertIn(needle, text)

    def test_more_than_max_regs_are_ignored(self):
        w = []
        text = "\n".join(f"r{i},3,{i},u16,1,0,mean" for i in range(40))
        self.assertEqual(len(ms.parse_table(text, w)), ms.MAX_REGS)
        self.assertTrue(any("ignored" in m for m in w))

    def test_name_is_cut_at_seven_characters(self):
        self.assertEqual(ms.parse_table("abcdefghij,3,0,u16,1,0,mean")[0].name, "abcdefg")


class SlaveAnswers(unittest.TestCase):
    def request(self, fc, start, count, slave=1):
        return ms.with_crc(bytes([slave, fc]) + struct.pack(">HH", start, count))

    def test_read_holding_registers(self):
        s = ms.Slave(make_meter())
        resp = s.handle(self.request(3, 0, 3), 1.0)
        self.assertTrue(ms.crc_ok(resp))
        self.assertEqual(resp[:3], bytes([1, 3, 6]))
        v1, v2, v3 = struct.unpack(">3H", resp[3:9])
        self.assertTrue(all(2250 < v < 2370 for v in (v1, v2, v3)), (v1, v2, v3))     # 0.1 V

    def test_config_registers_hold_the_ct(self):
        s = ms.Slave(make_meter())
        resp = s.handle(self.request(3, 0x30, 2), 1.0)
        self.assertEqual(struct.unpack(">2H", resp[3:7]), (250, 5))

    def test_address_not_in_the_meter(self):
        resp = ms.Slave(make_meter()).handle(self.request(3, 0x0011, 1), 1.0)
        self.assertEqual(resp[1:3], bytes([0x83, 0x02]))
        self.assertTrue(ms.crc_ok(resp))

    def test_unmapped_as_zero(self):
        resp = ms.Slave(make_meter(), unmapped="zero").handle(self.request(3, 0x0011, 2), 1.0)
        self.assertEqual(struct.unpack(">2H", resp[3:7]), (0, 0))

    def test_function_code_4_not_in_this_layout(self):
        resp = ms.Slave(make_meter()).handle(self.request(4, 0, 1), 1.0)
        self.assertEqual(resp[1:3], bytes([0x84, 0x02]))

    def test_function_code_4_in_the_float_layout(self):
        resp = ms.Slave(make_meter("float32-fc4")).handle(self.request(4, 0, 2), 1.0)
        self.assertEqual(resp[1], 4)
        lo, hi = struct.unpack(">2H", resp[3:7])                     # low word first
        v1 = struct.unpack(">f", struct.pack(">HH", hi, lo))[0]
        self.assertTrue(225 < v1 < 237, v1)

    def test_writes_and_unknown_functions_are_refused(self):
        s = ms.Slave(make_meter())
        for fc in (5, 6, 16, 8):
            body = bytes([1, fc]) + struct.pack(">HH", 0x30, 1)
            resp = s.handle(ms.with_crc(body), 1.0)
            self.assertEqual(resp[1:3], bytes([fc | 0x80, 0x01]), fc)

    def test_bad_counts(self):
        s = ms.Slave(make_meter())
        for count in (0, 126):
            self.assertEqual(s.handle(self.request(3, 0, count), 1.0)[1:3], bytes([0x83, 0x03]))

    def test_silence_for_other_slaves_and_bad_crc(self):
        s = ms.Slave(make_meter())
        self.assertIsNone(s.handle(self.request(3, 0, 1, slave=2), 1.0))
        bad = bytearray(self.request(3, 0, 1))
        bad[-1] ^= 0xFF
        self.assertIsNone(s.handle(bytes(bad), 1.0))

    def test_frame_extraction(self):
        req = self.request(3, 0, 10)
        self.assertEqual(ms.extract_frame(bytearray(req[:5])), 0)           # not complete yet
        self.assertEqual(ms.extract_frame(bytearray(req)), 8)
        self.assertEqual(ms.extract_frame(bytearray(b"\x00" + req)), 0)     # junk in front
        self.assertEqual(ms.extract_frame(bytearray(req + req[:3])), 8)     # a second frame starts


class DumpMode(unittest.TestCase):
    def dump(self, profile, fcs, start, count):
        lines = []
        ms.run_dump(make_meter(profile), fcs, start, count, out=lines.append)
        return "\n".join(lines)

    def test_float_layout_shows_the_value_as_a_float_low_word_first(self):
        text = self.dump("float32-fc4", [4], 0, 4)
        self.assertIn("(4 of 4 registers answered)", text)
        row = [l for l in text.splitlines() if l.startswith("0x0000")][0]
        self.assertTrue(225 < float(row.split("|")[2].split()[1]) < 237, row)        # float lo-hi column

    def test_function_codes_hold_different_registers(self):
        self.assertIn("(0 of 8 registers answered)", self.dump("float32-fc4", [3], 0, 8))
        self.assertIn("(8 of 8 registers answered)", self.dump("float32-fc4", [4], 0, 8))

    def test_the_guide_layout_has_its_holes(self):
        text = self.dump("proposed", [3], 0, 28)
        self.assertIn("(21 of 28 registers answered)", text)
        self.assertNotIn("0x0011", text)


class CheckMode(unittest.TestCase):
    def test_proposed_table_needs_ct_mult_when_the_meter_sends_secondary_values(self):
        regs = ms.load_table(ms.PROFILES["proposed"])
        n_ok, n, out = check(regs, make_meter(), 50.0)
        self.assertEqual((n_ok, n), (19, 19), out)
        n_ok, n, out = check(regs, make_meter(), 1.0)
        self.assertEqual(n_ok, 10, out)                      # currents and powers (9 values) are 50 times too small
        self.assertIn("ct_mult = 50", out)

    def test_primary_meter_is_fixed_by_scales_not_by_ct_mult(self):
        regs = ms.load_table(ms.PROFILES["proposed"])
        n_ok, n, out = check(regs, make_meter("primary-16bit"), 1.0)
        self.assertEqual(n_ok, 10, out)
        self.assertIn("new scale = 0.01", out)
        fixed = ms.load_table(ms.PROFILES["primary-16bit"])   # the meter's own layout is the right answer
        self.assertEqual(check(fixed, make_meter("primary-16bit"), 1.0)[:2], (19, 19))
        n_ok, n, out = check(regs, make_meter("primary-16bit"), 50.0)     # the wrong fix: multiplying twice
        self.assertLess(n_ok, 19)
        self.assertIn("applied twice", out)

    def test_wrong_addresses_lose_the_whole_request(self):
        regs = ms.load_table(ms.PROFILES["proposed"])
        n_ok, n, out = check(regs, make_meter("float32-fc4"), 1.0)
        self.assertEqual(n_ok, 0)
        self.assertIn("EXCEPTION 02", out)
        self.assertIn("NO ANSWER", out)

    def test_float_layout_with_a_matching_table(self):
        regs = ms.load_table(ms.PROFILES["float32-fc4"])
        self.assertEqual(check(regs, make_meter("float32-fc4"), 1.0)[:2], (19, 19))

    def test_hole_in_the_meter_does_not_hurt_separate_requests(self):
        # The old merge rule (gap 8) would have read 0x0011..0x0017 and lost everything on a strict meter.
        regs = ms.load_table(ms.PROFILES["proposed"])
        n_ok, n, out = check(regs, make_meter(), 50.0)
        self.assertNotIn("EXCEPTION", out)

    def test_unknown_name_is_reported(self):
        regs = ms.parse_table("nonsense,3,0,u16,1,0,mean")
        n_ok, n, out = check(regs, make_meter(), 1.0)
        self.assertEqual(n_ok, 0)
        self.assertIn("no true value", out)

    def test_current_that_does_not_fit_16_bits_is_noticed(self):
        warns = []
        meter = make_meter(amps=(125.0, 120.0, 110.0),
                           table=ms.PROFILES["primary-16bit"], warn=warns.append)
        # make the meter's current scale 0.001 primary: 125 A needs 125000, a 16-bit register stops at 65535
        for r in meter.layout:
            if r.name.startswith("i"):
                r.scale = 0.001
        regs = ms.load_table(ms.PROFILES["proposed"])
        for r in regs:
            r.ct = False
        n_ok, n, out = check(regs, meter, 1.0)
        self.assertTrue(any("does not fit" in w for w in warns), warns)
        self.assertLess(n_ok, 19)


@unittest.skipUnless(os.name == "posix", "needs a pty")
class OverASerialLine(unittest.TestCase):
    def test_serve_loop_on_a_pty(self):
        try:
            import serial
        except ImportError:
            self.skipTest("pyserial not installed")
        import pty
        master, slave_fd = pty.openpty()
        ser = serial.Serial(os.ttyname(slave_fd), 9600, timeout=0.005)
        stop = threading.Event()
        slave = ms.Slave(make_meter())
        t = threading.Thread(target=ms.serve_loop, args=(ser, slave),
                             kwargs=dict(stop=stop.is_set, reply_delay=0.001), daemon=True)
        t.start()
        try:
            def ask(frame):
                os.write(master, frame)
                buf = b""
                while True:
                    r, _, _ = select.select([master], [], [], 1.0)
                    if not r:
                        return buf
                    buf += os.read(master, 256)
                    if len(buf) >= 5 and ms.crc_ok(buf) and (buf[1] & 0x80 or len(buf) == 5 + buf[2]):
                        return buf
            ok = ask(ms.with_crc(bytes([1, 3]) + struct.pack(">HH", 0, 17)))
            self.assertEqual(ok[:3], bytes([1, 3, 34]))
            self.assertTrue(ms.crc_ok(ok))
            exc = ask(ms.with_crc(bytes([1, 3]) + struct.pack(">HH", 0x11, 1)))
            self.assertEqual(exc[1:3], bytes([0x83, 0x02]))
            # a request sent in two pieces, as a slow UART may do
            req = ms.with_crc(bytes([1, 3]) + struct.pack(">HH", 0x30, 2))
            os.write(master, req[:3])
            threading.Event().wait(0.03)
            self.assertEqual(ask(req[3:])[:3], bytes([1, 3, 4]))
        finally:
            stop.set()
            t.join(2)
            ser.close()
            os.close(master)
            os.close(slave_fd)


if __name__ == "__main__":
    unittest.main()
