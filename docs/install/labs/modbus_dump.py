#!/usr/bin/env python3
"""Lab 3: Modbus RTU register dump of the FORT FCN300 meter from a laptop.

NOT YET TESTED ON THE HARDWARE. The register map is NOT VERIFIED
(docs/meter/README.md). This script only READS: it never writes to the meter.

Needs: Python 3.8+, `pip install minimalmodbus pyserial`, a USB-RS485 adapter.

Examples:
    python modbus_dump.py --port COM5                  # Windows
    python modbus_dump.py --port /dev/ttyUSB0          # Linux
    python modbus_dump.py --port COM5 --fc 3 --start 0x18 --count 8 --repeat 10
    python modbus_dump.py --port COM5 --csv dump.csv   # also save to a file

For each register it prints the word as hex, u16 and s16. For each pair of
registers (n, n+1) it prints u32, s32 and float32 in both word orders:
  "hi-lo": register n is the high word (big-endian, ABCD)
  "lo-hi": register n is the low word (word-swapped, CDAB)
Compare with the meter's LCD to find the type, word order and scale of each value.
"""
import argparse
import csv
import struct
import sys
import time

try:
    import minimalmodbus
    import serial
except ImportError:
    sys.exit("Install the libraries first: pip install minimalmodbus pyserial")


def read_block(inst, fc, start, count):
    """Return a list of words, or None if the block does not answer."""
    try:
        return inst.read_registers(start, count, functioncode=fc)
    except (minimalmodbus.ModbusException, OSError, ValueError) as exc:
        print(f"  FC{fc:02d} 0x{start:04X}..0x{start + count - 1:04X}: {type(exc).__name__}: {exc}")
        return None


def as_s16(w):
    return w - 0x10000 if w & 0x8000 else w


def pair_values(hi, lo):
    raw = struct.pack(">HH", hi, lo)
    return (struct.unpack(">I", raw)[0], struct.unpack(">i", raw)[0], struct.unpack(">f", raw)[0])


def dump(inst, fc, start, count, block, writer):
    words = {}
    for s in range(start, start + count, block):
        n = min(block, start + count - s)
        got = read_block(inst, fc, s, n)
        if got is not None:
            for i, w in enumerate(got):
                words[s + i] = w
        time.sleep(0.05)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n--- FC{fc:02d}  {stamp}  ({len(words)} of {count} registers answered) ---")
    print(" addr    hex     u16     s16 |  u32 hi-lo     s32 hi-lo   float hi-lo |  u32 lo-hi     float lo-hi")
    for a in range(start, start + count):
        if a not in words:
            continue
        w = words[a]
        line = f"0x{a:04X}  0x{w:04X} {w:6d} {as_s16(w):7d} |"
        row = [stamp, fc, f"0x{a:04X}", f"0x{w:04X}", w, as_s16(w)]
        if a + 1 in words:
            u_hl, s_hl, f_hl = pair_values(w, words[a + 1])
            u_lh, _s_lh, f_lh = pair_values(words[a + 1], w)
            line += f" {u_hl:11d} {s_hl:12d} {f_hl:13.5g} | {u_lh:11d} {f_lh:13.5g}"
            row += [u_hl, s_hl, f"{f_hl:.6g}", u_lh, f"{f_lh:.6g}"]
        print(line)
        if writer:
            writer.writerow(row)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", required=True, help="serial port, e.g. COM5 or /dev/ttyUSB0")
    p.add_argument("--slave", type=int, default=1, help="Modbus slave id (default 1, to verify)")
    p.add_argument("--baud", type=int, default=9600, help="baud rate (default 9600, to verify)")
    p.add_argument("--parity", choices="NEO", default="N", help="parity (default N for 8-N-1)")
    p.add_argument("--fc", type=int, choices=[3, 4], nargs="*", default=[3, 4], help="function code(s) to try")
    p.add_argument("--start", type=lambda x: int(x, 0), default=0x0000, help="first register (default 0x0000)")
    p.add_argument("--count", type=int, default=0x40, help="number of registers (default 64)")
    p.add_argument("--block", type=int, default=16, help="registers per request (default 16)")
    p.add_argument("--repeat", type=int, default=1, help="number of dumps (watch counters move)")
    p.add_argument("--interval", type=float, default=5.0, help="seconds between dumps")
    p.add_argument("--csv", help="also append the rows to this CSV file")
    a = p.parse_args()

    inst = minimalmodbus.Instrument(a.port, a.slave, mode=minimalmodbus.MODE_RTU)
    inst.serial.baudrate = a.baud
    inst.serial.bytesize = 8
    inst.serial.parity = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}[a.parity]
    inst.serial.stopbits = 1
    inst.serial.timeout = 0.5
    inst.clear_buffers_before_each_transaction = True

    print(f"Port {a.port}, slave {a.slave}, {a.baud} baud 8-{a.parity}-1. Read only.")
    fh = open(a.csv, "a", newline="") if a.csv else None
    writer = csv.writer(fh) if fh else None
    if writer and fh.tell() == 0:
        writer.writerow(["time", "fc", "addr", "hex", "u16", "s16",
                         "u32_hilo", "s32_hilo", "float_hilo", "u32_lohi", "float_lohi"])
    try:
        for i in range(a.repeat):
            for fc in a.fc:
                dump(inst, fc, a.start, a.count, a.block, writer)
            if i + 1 < a.repeat:
                time.sleep(a.interval)
    finally:
        if fh:
            fh.close()


if __name__ == "__main__":
    main()
