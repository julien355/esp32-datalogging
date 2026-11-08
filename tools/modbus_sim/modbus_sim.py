#!/usr/bin/env python3
"""Modbus RTU slave simulator of a 3-phase power meter (a stand-in for the FORT FCN300).

NOT a copy of the real meter: nobody has seen the real register map yet (docs/meter/README.md).
It answers with the register LAYOUT you give it, so the logger, its registers.csv and the
whole chain to the VPS can be tested before the site visit. Read only: it never accepts writes.

Two modes (Python 3.8+; `serve` also needs `pip install pyserial`):

  serve  Answer the logger (or modbus_dump.py) on a serial port, here an RS485 adapter.
         python modbus_sim.py serve --port COM7                      # Windows
         python modbus_sim.py serve --port /dev/ttyUSB0 -v           # Linux, log every request
         python modbus_sim.py serve --port COM7 --profile primary-16bit --amps 80,75,90

  check  No hardware at all. Replays what the logger does with a registers.csv: builds its
         requests, reads them from the simulated meter, decodes the words, and compares with
         the true values. Prints a hint for each wrong value.
         python modbus_sim.py check --regs my_registers.csv --ct-mult 50

  dump   No hardware either. Prints what docs/install/labs/modbus_dump.py would show for the simulated
         meter (one register per request): the practice for reading a real dump.
         python modbus_sim.py dump --profile float32-fc4 --fc 4 --start 0 --count 40

  profiles  List the meter layouts.

The simulated meter has two parts:
  * the PHYSICS: three phases (volts, amps, power factor) that move a little, and kWh/kvarh
    counters that keep counting (--speed 60 counts 60 times faster);
  * the LAYOUT: a table in the same format as the logger's registers.csv
    (name,fc,addr,type,scale,ct,agg), chosen with --profile or --meter-table. Here `ct` = 1
    means the simulated meter sends SECONDARY values (divided by the CT ratio, --ct 250/5),
    exactly the case the logger's ct_mult is for. `agg` is ignored.
"""
import argparse
import math
import os
import random
import re
import struct
import sys
import time
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PROFILES = {
    "proposed": os.path.join(REPO, "docs", "meter", "registers-proposed.csv"),
    "primary-16bit": os.path.join(HERE, "profiles", "primary-16bit.csv"),
    "float32-fc4": os.path.join(HERE, "profiles", "float32-fc4.csv"),
}
PROFILE_INFO = {
    "proposed": "the proposed table (docs/meter/registers-proposed.csv): 16-bit, SECONDARY values (mA, W)",
    "primary-16bit": "16-bit, PRIMARY values (the meter applies its CT setting), finer scales",
    "float32-fc4": "float32, low word first, on FUNCTION CODE 4, different addresses",
}
DEFAULT_LOGGER_TABLE = PROFILES["proposed"]

TYPES = ["u16", "s16", "u32", "s32", "u32sw", "s32sw", "f32", "f32sw"]
RANGES = {"u16": (0, 0xFFFF), "s16": (-0x8000, 0x7FFF), "u32": (0, 0xFFFFFFFF), "s32": (-0x80000000, 0x7FFFFFFF),
          "u32sw": (0, 0xFFFFFFFF), "s32sw": (-0x80000000, 0x7FFFFFFF)}

# Same limits as firmware/src/meter.cpp (buildBlocks) and firmware/include/config.h. A test checks them.
MAX_REGS = 32
MERGE_GAP = 0       # registers further apart than this are read in separate requests
MAX_SPAN = 60       # registers per request

CONFIG_REGS = {0x30: "ct1", 0x31: "ct2", 0x32: "pt1", 0x33: "pt2", 0x34: "address", 0x35: "baud"}
BAUD_CODE = {2400: 0, 4800: 1, 9600: 2, 19200: 3}


@dataclass
class Reg:
    name: str
    fc: int
    addr: int
    type: str
    scale: float
    ct: bool
    agg: str = "minmax"

    @property
    def words(self):
        return 1 if self.type in ("u16", "s16") else 2


def unit_of(name):
    if name == "pf":
        return ""
    if name == "eq":
        return "kvarh"
    for prefix, unit in (("v", "V"), ("i", "A"), ("f", "Hz"), ("p", "kW"), ("q", "kvar"), ("s", "kVA"), ("e", "kWh")):
        if name.startswith(prefix):
            return unit
    return ""


# ---------------------------------------------------------------- the register table (same rules as the logger)

def _strtol0(s):
    """C strtol(s, 0, 0): 0x.. hex, a leading 0 is OCTAL, else decimal; garbage gives 0."""
    m = re.match(r"\s*([+-]?)(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)", s)
    if not m:
        return 0
    sign, body = m.groups()
    n = int(body, 16) if body[:2] in ("0x", "0X") else int(body, 8) if body.startswith("0") else int(body)
    return -n if sign == "-" else n


def _toint(s):
    """Arduino String.toInt(): the leading integer, else 0."""
    m = re.match(r"\s*[+-]?\d+", s)
    return int(m.group(0)) if m else 0


def _tofloat(s):
    m = re.match(r"\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s)
    return float(m.group(0)) if m else 0.0


def parse_table(text, warnings=None):
    """Parse registers.csv the way firmware/src/meter.cpp loadOverride() does, including its silent defaults."""
    warn = warnings if warnings is not None else []
    regs = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] == "#" or line.startswith("name,"):
            continue
        if len(regs) >= MAX_REGS:
            warn.append(f"line {lineno}: more than {MAX_REGS} values: this line and the next ones are ignored by the logger")
            break
        p = line.split(",")
        if len(p) < 6:
            warn.append(f"line {lineno}: fewer than 6 fields, skipped by the logger: {line}")
            continue
        name = p[0].strip()[:7]
        fc = _toint(p[1])
        t = p[3].strip().lower()
        if t not in TYPES or fc not in (3, 4):
            warn.append(f"line {lineno}: bad type or function code, logged as 'bad line skipped': {line}")
            continue
        if not re.fullmatch(r"\s*(0[xX][0-9a-fA-F]+|\d+)\s*", p[2]):
            warn.append(f"line {lineno}: address '{p[2].strip()}' is not a number: the logger reads it as {_strtol0(p[2])}")
        elif re.fullmatch(r"\s*0[0-9]+\s*", p[2]):
            warn.append(f"line {lineno}: address '{p[2].strip()}' starts with 0: the logger reads it as OCTAL ({_strtol0(p[2])}); write 0x.. or no leading zero")
        if not re.fullmatch(r"\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*", p[4]):
            warn.append(f"line {lineno}: scale '{p[4].strip()}' is not a number: the logger reads it as {_tofloat(p[4])}")
        agg_word = p[6].strip() if len(p) > 6 else ""
        agg = "last" if agg_word == "last" else "minmax" if agg_word in ("minmax", "meanmax") else "mean"
        if agg_word not in ("last", "minmax", "meanmax", "mean"):
            warn.append(f"line {lineno}: agg '{agg_word}' is not last, minmax or mean: the logger uses mean")
        ct = _toint(p[5]) == 1
        regs.append(Reg(name, fc, _strtol0(p[2]), t, _tofloat(p[4]), ct, agg))
    seen = set()
    for r in regs:
        if r.name in seen:
            warn.append(f"name '{r.name}' appears twice: the CSV would get two columns with the same name")
        seen.add(r.name)
    return regs


def load_table(path, warnings=None):
    with open(path, encoding="utf-8") as f:
        return parse_table(f.read(), warnings)


def build_blocks(regs):
    """Port of buildBlocks() in firmware/src/meter.cpp: the requests the logger sends. [(fc, start, count)]"""
    order = sorted(range(len(regs)), key=lambda i: (regs[i].fc, regs[i].addr, i))
    blocks = []
    for i in order:
        r = regs[i]
        end = r.addr + r.words
        if blocks:
            b = blocks[-1]
            if b[0] == r.fc and r.addr <= b[1] + b[2] + MERGE_GAP and end - b[1] <= MAX_SPAN:
                if end > b[1] + b[2]:
                    b[2] = end - b[1]
                continue
        blocks.append([r.fc, r.addr, end - r.addr])
    return [tuple(b) for b in blocks]


# ---------------------------------------------------------------- words <-> values

def encode(reg, phys, ct_ratio, warn=None):
    """Words a meter with this layout puts in its registers for the physical (primary) value."""
    v = phys / ct_ratio if reg.ct else phys
    x = v / reg.scale if reg.scale else 0.0
    if reg.type in ("f32", "f32sw"):
        try:
            hi, lo = struct.unpack(">HH", struct.pack(">f", x))
        except OverflowError:
            hi, lo = 0x7F80, 0
    else:
        n = int(round(x))
        lo_lim, hi_lim = RANGES[reg.type]
        if n < lo_lim or n > hi_lim:
            if warn:
                warn(f"{reg.name} (0x{reg.addr:04X}) = {phys:g} does not fit {reg.type} at scale {reg.scale:g}: the register saturates")
            n = max(lo_lim, min(hi_lim, n))
        if reg.words == 1:
            return [n & 0xFFFF]
        u = n & 0xFFFFFFFF
        hi, lo = u >> 16, u & 0xFFFF
    return [lo, hi] if reg.type.endswith("sw") else [hi, lo]


def decode(reg, words, ct_mult):
    """Port of decode() in firmware/src/meter.cpp. Returns the value the logger puts in the column."""
    w0 = words[0]
    w1 = words[1] if len(words) > 1 else 0
    t = reg.type
    s16 = lambda w: w - 0x10000 if w & 0x8000 else w
    s32 = lambda u: u - 0x100000000 if u & 0x80000000 else u
    if t == "u16":
        v = float(w0)
    elif t == "s16":
        v = float(s16(w0))
    elif t == "u32":
        v = float((w0 << 16) | w1)
    elif t == "s32":
        v = float(s32((w0 << 16) | w1))
    elif t == "u32sw":
        v = float((w1 << 16) | w0)
    elif t == "s32sw":
        v = float(s32((w1 << 16) | w0))
    elif t == "f32":
        v = struct.unpack(">f", struct.pack(">HH", w0, w1))[0]
    else:
        v = struct.unpack(">f", struct.pack(">HH", w1, w0))[0]
    v *= reg.scale
    if reg.ct:
        v *= ct_mult
    return v


def decimals_for(reg, mean=False):
    """Port of decimalsFor() in firmware/src/sampler.cpp: how many decimals the logger writes."""
    scale = reg.scale
    if reg.type in ("f32", "f32sw") and scale > 0.001:
        scale = 0.001                     # floats usually have scale 1: still write 3 decimals
    d = 0
    while d < 4 and scale < 0.999:
        scale *= 10
        d += 1
    return min(4, d + (1 if mean else 0))


# ---------------------------------------------------------------- the simulated meter

class Physics:
    """Three phases that wander a little, and energy counters that keep counting."""

    def __init__(self, volts=231.0, amps=(60.0, 55.0, 70.0), pf=0.92, seed=1, speed=1.0, e0=12345.67, eq0=2345.67):
        rnd = random.Random(seed)
        self.volts, self.amps, self.pf, self.speed = volts, tuple(amps), pf, speed
        self.ph = [rnd.uniform(0, 6.28) for _ in range(9)]
        self.e, self.eq, self.t_last = e0, eq0, None

    def snapshot(self, t):
        w = math.sin
        v = [self.volts * (1 + 0.004 * w(t / 15.0 + self.ph[k])) for k in range(3)]
        i = [self.amps[k] * (1 + 0.05 * w(t / 9.7 + self.ph[3 + k]) + 0.002 * w(t * 12.9898 + self.ph[3 + k] * 78.233)) for k in range(3)]
        pf = min(1.0, max(0.0, self.pf + 0.01 * w(t / 23.0 + self.ph[6])))
        sin_phi = math.sqrt(1 - pf * pf)
        s_ph = [v[k] * i[k] / 1000.0 for k in range(3)]
        p_ph = [s * pf for s in s_ph]
        q_ph = [s * sin_phi for s in s_ph]
        out = {"v1": v[0], "v2": v[1], "v3": v[2],
               "v12": math.sqrt(v[0] ** 2 + v[1] ** 2 + v[0] * v[1]),
               "v23": math.sqrt(v[1] ** 2 + v[2] ** 2 + v[1] * v[2]),
               "v31": math.sqrt(v[2] ** 2 + v[0] ** 2 + v[2] * v[0]),
               "i1": i[0], "i2": i[1], "i3": i[2], "f": 50 + 0.03 * w(t / 31.0 + self.ph[7]),
               "p1": p_ph[0], "p2": p_ph[1], "p3": p_ph[2], "p": sum(p_ph), "q": sum(q_ph), "s": sum(s_ph),
               "pf": sum(p_ph) / sum(s_ph)}
        if self.t_last is not None and t > self.t_last:
            self.e += out["p"] * (t - self.t_last) * self.speed / 3600.0
            self.eq += out["q"] * (t - self.t_last) * self.speed / 3600.0
        self.t_last = t
        out["e"], out["eq"] = self.e, self.eq
        return out


class SimMeter:
    def __init__(self, layout, physics, ct=(250, 5), slave=1, baud=9600, warn=None):
        self.layout, self.physics, self.ct, self.slave, self.baud = layout, physics, ct, slave, baud
        self.ct_ratio = ct[0] / ct[1]
        self.warn = warn
        self.warned = set()

    def _warn(self, msg):
        if msg not in self.warned:
            self.warned.add(msg)
            if self.warn:
                self.warn(msg)

    def image(self, t):
        """{fc: {address: word}} and the true values, at time t."""
        snap = self.physics.snapshot(t)
        img = {3: {}, 4: {}}
        cfg = {"ct1": self.ct[0], "ct2": self.ct[1], "pt1": 1, "pt2": 1, "address": self.slave, "baud": BAUD_CODE.get(self.baud, 2)}
        for a, k in CONFIG_REGS.items():
            img[3][a] = cfg[k]
        for r in self.layout:
            if r.name not in snap:
                self._warn(f"meter layout: '{r.name}' is not a quantity of the simulator, skipped")
                continue
            for k, word in enumerate(encode(r, snap[r.name], self.ct_ratio, self._warn)):
                img[r.fc][r.addr + k] = word
        return img, snap


# ---------------------------------------------------------------- Modbus RTU

def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(body):
    c = crc16(body)
    return bytes(body) + bytes([c & 0xFF, c >> 8])


def crc_ok(frame):
    return len(frame) >= 4 and crc16(frame[:-2]) == frame[-2] | (frame[-1] << 8)


def extract_frame(buf):
    """Length of the first complete, CRC-valid request at the start of buf, or 0."""
    if len(buf) < 8:
        return 0
    n = 9 + buf[6] if buf[1] in (15, 16) and len(buf) > 6 else 8
    return n if len(buf) >= n and crc_ok(bytes(buf[:n])) else 0


class Slave:
    def __init__(self, meter, unmapped="error"):
        self.meter, self.unmapped = meter, unmapped
        self.last = ""

    def _exc(self, fc, code, why):
        self.last = f"FC{fc:02d} -> exception {code:02d} ({why})"
        return with_crc(bytes([self.meter.slave, fc | 0x80, code]))

    def handle(self, frame, t):
        """Response bytes for a request, or None when a real slave would stay silent."""
        if not crc_ok(frame) or frame[0] != self.meter.slave:
            return None
        fc = frame[1]
        if fc in (3, 4):
            if len(frame) != 8:
                return self._exc(fc, 3, "bad length")
            start, count = struct.unpack(">HH", frame[2:6])
            if not 1 <= count <= 125:
                return self._exc(fc, 3, "illegal data value: count must be 1 to 125")
            img, _ = self.meter.image(t)
            words = []
            for a in range(start, start + count):
                if a in img[fc]:
                    words.append(img[fc][a])
                elif self.unmapped == "zero":
                    words.append(0)
                else:
                    return self._exc(fc, 2, f"illegal data address 0x{a:04X}: not in this meter")
            self.last = f"FC{fc:02d} 0x{start:04X} x{count} -> ok"
            return with_crc(bytes([self.meter.slave, fc, 2 * count]) + b"".join(struct.pack(">H", w) for w in words))
        return self._exc(fc, 1, "illegal function: this simulator is read only")


def serve_loop(ser, slave, stop=None, drop_pct=0.0, silent_after=None, reply_delay=0.003, verbose=False, log=print):
    """Answer requests on an open pyserial port until stop() is true or Ctrl+C."""
    buf = bytearray()
    t0 = time.monotonic()
    last_rx = t0
    asked = answered = 0
    last_report = t0
    rnd = random.Random(7)
    while not (stop and stop()):
        data = ser.read(ser.in_waiting or 1)
        now = time.monotonic()
        if data:
            buf += data
            last_rx = now
        elif buf and now - last_rx > 0.1:
            buf.clear()                       # junk or a frame for another slave: drop it
        while True:
            n = extract_frame(buf)
            if not n:
                break
            frame, buf = bytes(buf[:n]), buf[n:]
            asked += 1
            if silent_after is not None and now - t0 > silent_after:
                continue
            if drop_pct and rnd.random() * 100 < drop_pct:
                if verbose:
                    log(f"{now - t0:8.2f}s  request dropped on purpose")
                continue
            resp = slave.handle(frame, now - t0)
            if resp is None:
                continue
            time.sleep(reply_delay)
            ser.write(resp)
            ser.flush()
            answered += 1
            if verbose:
                log(f"{now - t0:8.2f}s  {slave.last}")
        if not verbose and now - last_report > 10:
            last_report = now
            log(f"{now - t0:8.0f}s  requests {asked}, answered {answered}")
    return asked, answered


# ---------------------------------------------------------------- check: what the logger does with a table

def _hint(reg, logged, truth, ct_mult, ct_ratio):
    if not math.isfinite(logged):
        return "not a number: wrong type or word order"
    if logged == 0:
        return "logged 0: wrong address, or the scale is 0 or very small"
    r = truth / logged
    if r <= 0:
        return "wrong sign or wrong register (is the type signed: s16, s32?)"

    def pow10(x):
        n = round(math.log10(x))
        return n if abs(x / 10 ** n - 1) < 0.03 else None

    for kind, f in (("plain", 1.0), ("ct", ct_ratio), ("twice", 1.0 / ct_ratio)):
        n = pow10(r / f)
        if n is None:
            continue
        scale_part = "" if n == 0 else f"scale x{10 ** n:g} (new scale = {reg.scale * 10 ** n:.6g})"
        if kind == "plain":
            if n == 0:
                return f"{(r - 1) * 100:+.1f} % off: rounding of a small value, or a slightly wrong scale"
            size = f"{10 ** n:g} times too small" if n > 0 else f"{10 ** -n:g} times too big"
            return f"{size}: new scale = {reg.scale * 10 ** n:.6g}"
        if kind == "ct":
            how = f"ct_mult = {ct_ratio * ct_mult:g}" if reg.ct else f"ct = 1 on this line and ct_mult = {ct_ratio * ct_mult:g}"
            return f"needs x{ct_ratio:g} more: the meter sends SECONDARY values: {how}" + (f", and {scale_part}" if scale_part else "")
        return "the CT ratio is applied twice: the meter already sends PRIMARY values: ct = 0 on this line, or ct_mult = 1" + \
               (f", and {scale_part}" if scale_part else "")
    return "no simple ratio: wrong register, type, word order or function code"


def run_check(logger_regs, meter, ct_mult, out=print):
    """Replay one logger read against the simulated meter. Returns (n_ok, n_total)."""
    slave = Slave(meter)
    t = 60.0
    img, truth = meter.image(t)
    blocks = build_blocks(logger_regs)
    out(f"Requests the logger sends ({len(blocks)}):")
    got = {}
    for fc, start, count in blocks:
        req = with_crc(bytes([meter.slave, fc]) + struct.pack(">HH", start, count))
        resp = slave.handle(req, t)
        if resp[1] & 0x80:
            out(f"  FC{fc:02d} 0x{start:04X} x{count:<3d} -> EXCEPTION {resp[2]:02d} ({slave.last.split('(')[-1].rstrip(')')}): every value in this request is lost")
            continue
        out(f"  FC{fc:02d} 0x{start:04X} x{count:<3d} -> ok")
        words = [struct.unpack(">H", resp[3 + 2 * k:5 + 2 * k])[0] for k in range(count)]
        for k, w in enumerate(words):
            got[(fc, start + k)] = w
    out("")
    out(f"{'name':7} {'fc':>2} {'addr':>6} {'type':5} {'raw':>13} {'logger shows':>16} {'true value':>14} {'true/logger':>11}  verdict")
    n_ok = 0
    for r in logger_regs:
        unit = unit_of(r.name)
        tv = truth.get(r.name)
        ws = [got.get((r.fc, r.addr + k)) for k in range(r.words)]
        if tv is None:
            out(f"{r.name:7} {r.fc:>2} 0x{r.addr:04X} {r.type:5}  (the simulator has no true value called '{r.name}': use v1 v2 v3 v12 v23 v31 i1 i2 i3 f p1 p2 p3 p q s pf e eq)")
            continue
        if None in ws:
            out(f"{r.name:7} {r.fc:>2} 0x{r.addr:04X} {r.type:5} {'-':>13} {'(no value)':>16} {tv:>11.3f} {unit:<3} {'':>11}  NO ANSWER: its request failed")
            continue
        v = decode(r, ws, ct_mult)
        dec = decimals_for(r)
        res = r.scale * (ct_mult if r.ct else 1)
        ok = math.isfinite(v) and abs(v - tv) <= max(0.01 * abs(tv), 0.5 * res)
        n_ok += ok
        raw = " ".join(f"{w}" for w in ws)
        ratio = f"{tv / v:11.4g}" if v else f"{'':>11}"
        verdict = "ok" if ok else "WRONG: " + _hint(r, v, tv, ct_mult, meter.ct_ratio)
        out(f"{r.name:7} {r.fc:>2} 0x{r.addr:04X} {r.type:5} {raw:>13} {v:>12.{dec}f} {unit:<3} {tv:>11.{dec}f} {unit:<3} {ratio}  {verdict}")
    out("")
    out(f"{n_ok} of {len(logger_regs)} values within 1 % of the true value.")
    return n_ok, len(logger_regs)


def run_dump(meter, fcs, start, count, out=print, t=60.0):
    """Same columns as docs/install/labs/modbus_dump.py, for the simulated meter."""
    img, _ = meter.image(t)
    s16 = lambda w: w - 0x10000 if w & 0x8000 else w
    pair = lambda hi, lo: (struct.unpack(">I", struct.pack(">HH", hi, lo))[0],
                           struct.unpack(">i", struct.pack(">HH", hi, lo))[0],
                           struct.unpack(">f", struct.pack(">HH", hi, lo))[0])
    for fc in fcs:
        words = {a: w for a, w in img[fc].items() if start <= a < start + count}
        out(f"\n--- FC{fc:02d}  simulated  ({len(words)} of {count} registers answered) ---")
        out(" addr    hex     u16     s16 |  u32 hi-lo     s32 hi-lo   float hi-lo |  u32 lo-hi     float lo-hi")
        for a in range(start, start + count):
            if a not in words:
                continue
            w = words[a]
            line = f"0x{a:04X}  0x{w:04X} {w:6d} {s16(w):7d} |"
            if a + 1 in words:
                u_hl, s_hl, f_hl = pair(w, words[a + 1])
                u_lh, _, f_lh = pair(words[a + 1], w)
                line += f" {u_hl:11d} {s_hl:12d} {f_hl:13.5g} | {u_lh:11d} {f_lh:13.5g}"
            out(line)


# ---------------------------------------------------------------- command line

def _ct(s):
    m = re.fullmatch(r"(\d+)/(\d+)", s)
    if not m or int(m.group(2)) == 0:
        raise argparse.ArgumentTypeError("use primary/secondary, for example 250/5")
    return int(m.group(1)), int(m.group(2))


def _amps(s):
    try:
        a = [float(x) for x in s.split(",")]
    except ValueError:
        a = []
    if len(a) != 3:
        raise argparse.ArgumentTypeError("three currents in A, for example 60,55,70")
    return tuple(a)


def _meter_args(p):
    p.add_argument("--profile", default="proposed", choices=sorted(PROFILES), help="meter layout (default proposed)")
    p.add_argument("--meter-table", help="a layout file of your own (same format as registers.csv); replaces --profile")
    p.add_argument("--ct", type=_ct, default=(250, 5), help="the CT of the site, primary/secondary (default 250/5)")
    p.add_argument("--volts", type=float, default=231.0, help="phase voltage (default 231)")
    p.add_argument("--amps", type=_amps, default=(60.0, 55.0, 70.0), help="primary current per phase (default 60,55,70)")
    p.add_argument("--pf", type=float, default=0.92, help="power factor (default 0.92)")
    p.add_argument("--speed", type=float, default=1.0, help="energy counters count this many times faster (default 1)")
    p.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    p.add_argument("--slave", type=int, default=1, help="Modbus slave address (default 1)")


def _make_meter(a, baud=9600):
    path = a.meter_table or PROFILES[a.profile]
    if not os.path.exists(path):
        sys.exit(f"Layout file not found: {path} (run from a clone of the repository)")
    w = []
    layout = load_table(path, w)
    for m in w:
        print("layout warning:", m, file=sys.stderr)
    phys = Physics(a.volts, a.amps, a.pf, a.seed, a.speed)
    return SimMeter(layout, phys, a.ct, a.slave, baud, warn=lambda m: print("note:", m, file=sys.stderr)), path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="answer on a serial port")
    s.add_argument("--port", required=True, help="serial port, e.g. COM7 or /dev/ttyUSB0")
    s.add_argument("--baud", type=int, default=9600)
    s.add_argument("--parity", choices="NEO", default="N", help="N = 8-N-1 (default)")
    s.add_argument("--unmapped", choices=["error", "zero"], default="error",
                   help="what a register that is not in the layout does: exception 02 (default) or reads as 0")
    s.add_argument("--drop-pct", type=float, default=0.0, help="ignore this %% of requests (tests the logger's retry)")
    s.add_argument("--silent-after", type=float, help="stop answering after this many seconds (tests alarm A03)")
    s.add_argument("--reply-delay-ms", type=float, default=3.0, help="wait before answering (default 3)")
    s.add_argument("-v", "--verbose", action="store_true", help="log every request")
    _meter_args(s)
    c = sub.add_parser("check", help="replay the logger's read of a registers.csv, no hardware")
    c.add_argument("--regs", default=DEFAULT_LOGGER_TABLE, help="the logger's table (default docs/meter/registers-proposed.csv)")
    c.add_argument("--ct-mult", type=float, default=1.0, help="the logger's ct_mult setting (default 1)")
    _meter_args(c)
    d = sub.add_parser("dump", help="print a register dump of the simulated meter, no hardware")
    d.add_argument("--fc", type=int, choices=[3, 4], nargs="*", default=[3, 4], help="function code(s) (default 3 4)")
    d.add_argument("--start", type=lambda x: int(x, 0), default=0, help="first register (default 0)")
    d.add_argument("--count", type=int, default=64, help="number of registers (default 64)")
    _meter_args(d)
    sub.add_parser("profiles", help="list the meter layouts")
    a = ap.parse_args(argv)

    if a.cmd == "profiles":
        for k in sorted(PROFILES):
            print(f"{k:14} {PROFILE_INFO[k]}")
        return 0

    if a.cmd == "dump":
        meter, path = _make_meter(a)
        print(f"Simulated meter: {a.meter_table or a.profile}, CT {a.ct[0]}/{a.ct[1]}, slave {a.slave}")
        run_dump(meter, a.fc, a.start, a.count)
        return 0

    if a.cmd == "check":
        meter, path = _make_meter(a)
        w = []
        if not os.path.exists(a.regs):
            sys.exit(f"Logger table not found: {a.regs}")
        regs = load_table(a.regs, w)
        print(f"Logger table : {a.regs} ({len(regs)} values), ct_mult = {a.ct_mult:g}")
        print(f"Simulated meter: {a.meter_table or a.profile}, CT {a.ct[0]}/{a.ct[1]} (x{meter.ct_ratio:g}), "
              f"{a.volts:g} V, {a.amps[0]:g}/{a.amps[1]:g}/{a.amps[2]:g} A, PF {a.pf:g}")
        for m in w:
            print("WARNING:", m)
        n_ok, n = run_check(regs, meter, a.ct_mult)
        return 0 if n_ok == n and not w else 1

    try:
        import serial
    except ImportError:
        sys.exit("Install pyserial first: pip install pyserial")
    meter, path = _make_meter(a, a.baud)
    parity = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}[a.parity]
    ser = serial.Serial(a.port, a.baud, bytesize=8, parity=parity, stopbits=1, timeout=0.005)
    print(f"Simulated meter on {a.port}, slave {a.slave}, {a.baud} 8-{a.parity}-1, layout {a.meter_table or a.profile}, "
          f"CT {a.ct[0]}/{a.ct[1]}. Read only. Ctrl+C to stop.")
    try:
        serve_loop(ser, Slave(meter, a.unmapped), drop_pct=a.drop_pct, silent_after=a.silent_after,
                   reply_delay=a.reply_delay_ms / 1000.0, verbose=a.verbose)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
