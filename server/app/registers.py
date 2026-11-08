"""Meter register table: parse, check and write the CSV the logger reads (/config/registers.csv).

One line per value:  name,fc,addr,type,scale,ct,agg
    name   column suffix (EM01_<name>): 1 to 7 characters, a-z and 0-9
    fc     3 = holding registers, 4 = input registers
    addr   0-based register address, hex (0x0018) or decimal (24)
    type   u16 s16 u32 s32 f32 (high word first), u32sw s32sw f32sw (low word first)
    scale  raw x scale = value in the column's unit (V, A, Hz, kW, kvar, kVA, kWh, kvarh)
    ct     1 = also multiplied by the logger's ct_mult setting, else 0
    agg    minmax (mean + _min + _max columns), mean, last (energy counters); empty = mean

The firmware (firmware/src/meter.cpp) applies the same rules and refuses a table that breaks them,
so a table checked here is a table the logger takes.
"""

import math
import re

TYPES = ("u16", "s16", "u32", "s32", "u32sw", "s32sw", "f32", "f32sw")
AGGS = ("mean", "last", "minmax")
MAX_REGS = 32                       # firmware/include/config.h MAX_REGS
MAX_CSV_BYTES = 4096                # the logger reads at most this much
NAME_RE = re.compile(r"^[a-z0-9]{1,7}$")
HEADER = "name,fc,addr,type,scale,ct,agg"
# Names the alarms, the daily report and the OED export look for (docs/DATA-FORMAT.md).
STANDARD = ("v1", "v2", "v3", "v12", "v23", "v31", "i1", "i2", "i3", "f",
            "p1", "p2", "p3", "p", "q", "s", "pf", "e", "eq")


def words(type_):
    return 1 if type_ in ("u16", "s16") else 2


def _int(text):
    t = text.strip().lower()
    if re.fullmatch(r"0x[0-9a-f]{1,4}", t):
        return int(t, 16)
    if re.fullmatch(r"\d{1,5}", t):
        return int(t)
    raise ValueError


def parse(text):
    """Returns (rows, errors, warnings). rows: list of dicts; errors and warnings: lists of text."""
    rows, errors, warnings = [], [], []
    if text.startswith("﻿"):
        text = text[1:]
    if len(text.encode("utf-8")) > 64 * 1024:
        return [], ["file too large (a register table is a few kB)"], []
    seen = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.lower().replace(" ", "").startswith("name,"):
            continue
        f = [x.strip() for x in line.split(",")]
        if len(f) == 6:
            f.append("")
        if len(f) != 7:
            errors.append(f"line {n}: {len(f)} fields, expected 7 (name,fc,addr,type,scale,ct,agg)")
            continue
        name, fc, addr, typ, scale, ct, agg = f
        bad = []
        name = name.lower()
        if not NAME_RE.match(name):
            bad.append(f"name '{name}' must be 1 to 7 characters a-z, 0-9")
        elif name in seen:
            bad.append(f"name '{name}' already on line {seen[name]} (each column must be unique)")
        if fc not in ("3", "4"):
            bad.append(f"fc '{fc}' must be 3 or 4")
        try:
            a = _int(addr)
        except ValueError:
            a = None
            bad.append(f"addr '{addr}' must be 0x0000 to 0xFFFF or 0 to 65535")
        typ = typ.lower()
        if typ not in TYPES:
            bad.append(f"type '{typ}' must be one of {' '.join(TYPES)}")
        try:
            sc = float(scale)
            if not math.isfinite(sc) or sc == 0:
                raise ValueError
        except ValueError:
            sc = None
            bad.append(f"scale '{scale}' must be a number, not 0")
        ctl = ct.lower()
        if ctl not in ("0", "1"):
            bad.append(f"ct '{ct}' must be 0 or 1")
        agg = agg.lower() or "mean"
        if agg not in AGGS:
            bad.append(f"agg '{agg}' must be mean, last or minmax")
        if a is not None and typ in TYPES and a + words(typ) > 0x10000:
            bad.append("register past 0xFFFF")
        if bad:
            errors.append(f"line {n}: " + "; ".join(bad))
            continue
        seen[name] = n
        rows.append({"name": name, "fc": int(fc), "addr": a, "type": typ, "scale": sc,
                     "ct": ctl == "1", "agg": agg})
        if 30001 <= a <= 49999:
            warnings.append(f"line {n}: addr {a} looks like a PLC number (40001 = 0x0000 with fc 3, "
                            "30001 = 0x0000 with fc 4): the table wants the 0-based address")
    if not rows and not errors:
        errors.append("no register line")
    if len(rows) > MAX_REGS:
        errors.append(f"{len(rows)} values: the logger reads at most {MAX_REGS} per meter")
    if rows:
        missing = [s for s in STANDARD if s not in seen]
        if missing:
            warnings.append("not in the table: " + " ".join(missing) + ". The alarms, the daily report and the "
                            "OED export use these names: their checks on the missing values stop")
        for r in rows:
            if r["name"] in ("e", "eq") and r["agg"] != "last":
                warnings.append(f"{r['name']} is an energy counter: agg should be 'last'")
    if not errors and len(to_csv(rows).encode()) > MAX_CSV_BYTES:
        errors.append(f"table larger than {MAX_CSV_BYTES} bytes")
    return rows, errors, warnings


def fmt_scale(x):
    return format(x, ".10g")


def to_csv(rows):
    out = [HEADER]
    for r in rows:
        out.append(f"{r['name']},{r['fc']},0x{r['addr']:04X},{r['type']},{fmt_scale(r['scale'])},"
                   f"{1 if r['ct'] else 0},{r['agg']}")
    return "\n".join(out) + "\n"


def same(rows_a, rows_b):
    """Same table, in the same order (the order is the column order of the records)."""
    if len(rows_a) != len(rows_b):
        return False
    for a, b in zip(rows_a, rows_b):
        for k in ("name", "fc", "addr", "type", "ct", "agg"):
            if a[k] != b[k]:
                return False
        # The logger prints the scale with 6 significant digits (%g).
        if not math.isclose(a["scale"], b["scale"], rel_tol=1e-5):
            return False
    return True
