# Fort FCN300 (3E4Y and 3EH4Y): what we know and what must be checked

Meter at Adab: **FORT FCN300**, 3-phase 4-wire multifunction meter, Modbus RTU over RS485. The label will say **FCN300-3E4Y** or **FCN300-3EH4Y** (the harmonic variant).

**Decision (owner, 31 October 2026): the same register map is used for both variants.** The firmware reads the registers of the guide (`fcn300-3e4y-modbus-guide.md`) whichever variant is installed. The 3EH4Y's harmonic values, if it has extra registers for them, are not read for now. The register check below still applies to whichever meter is there.

(`arkan-cmms` calls it "Fort FC300".)

Source: `fcn300-3e4y-modbus-guide.md`, received from the owner on 30 October 2026, kept as received.

## Status: **not verified, and it can only be verified on site** (8 November 2026)

The spare meter at the office has **no Modbus port** (owner, 8 November 2026), so the register check planned on the bench (`docs/OFFICE-PREP.md` T4) is not possible. The register map is **a proposal to test on site**, at the first visit with the laptop and the USB-RS485 adapter, before the logger is left running (section 4). No manufacturer manual was found: the web search found only retailer pages, and the manual of the sibling model (Scribd, FCN300-E13ZY-D) could not be opened from the cloud session.

The guide is the starting point for the firmware's register table. It is not a manufacturer document, and several lines in it do not hold together:

| # | Issue in the guide | Why it matters | How we settle it |
|---|---|---|---|
| 1 | No official manual found. The Scribd link is for a **different model** (FCN300-E13ZY-D). The fortindo.id and distributor pages could not be read from the cloud session (network allow-list) | The register map may be for a sibling model | Get the manual from the supplier, or read the registers on site (section 4) |
| 2 | Data types say "16-bit / 32-bit INT" for the same register, and addresses run one by one (0x0000, 0x0001, ...) | A 32-bit value takes two registers, so consecutive addresses mean 16-bit, or the map is wrong | Register dump: compare the raw words with the LCD |
| 3 | Current scale "x0.001 or x0.01"; power "Direct / Scaling" with no factor | Wrong scale = readings off by 10x or 1000x | Compare with the LCD at a known load |
| 4 | kVARh "32-bit" at a single address (0x001A) | A 32-bit value cannot fit in one register | Dump 0x0018 to 0x001F, watch which words count up |
| 5 | Section 4 of the guide: values may be **secondary** (before the CT ratio) | Currents and powers could be 1/40 of the real value (200/5 CT) | Compare with the LCD (section 4 below) |
| 6 | Both FC03 and FC04 listed for the same addresses | Only one may answer | Try both in the dump |
| 7 | RS485 port: resellers list Modbus RS485 for both 3E4Y and 3EH4Y | No port, no data | **Check for A/B (485) terminals on the back of the meter. Photo needed** |

## 1. The proposed table

File: [`registers-proposed.csv`](registers-proposed.csv). It is the register table **already built into the firmware** (`firmware/src/meter.cpp`), so the logger works with or without it; on site it is the file you copy to the SD card as `/config/registers.csv` and edit. A bad line is skipped and logged. Format: `docs/FIRMWARE.md` §2.1.

| Value | Register (0-based) | Type | Scale | `ct` |
|---|---|---|---|---|
| V1, V2, V3 (L-N) | `0x0000` to `0x0002` | u16 | x 0.1 V | 0 |
| V12, V23, V31 (L-L) | `0x0003` to `0x0005` | u16 | x 0.1 V | 0 |
| I1, I2, I3 | `0x0006` to `0x0008` | u16 | x 0.001 A | **1** |
| Frequency | `0x0009` | u16 | x 0.01 Hz | 0 |
| P1, P2, P3 | `0x000A` to `0x000C` | s16 | x 0.001 kW | **1** |
| P total, Q total | `0x000D`, `0x000E` | s16 | x 0.001 kW, kvar | **1** |
| S total | `0x000F` | u16 | x 0.001 kVA | **1** |
| Power factor | `0x0010` | s16 | x 0.001 | 0 |
| Active energy | `0x0018`, `0x0019` (high word first) | u32 | x 0.01 kWh | 0 |
| Reactive energy | `0x001A`, `0x001B` (high word first) | u32 | x 0.01 kvarh | 0 |

Function code 3. Slave 1, 9600 baud, 8-N-1 (read the real values on the meter's LCD menu).

**Why these numbers, and the working hypothesis.** A 16-bit register holds at most 65,535. With "I x 0.001" the largest current is 65.5 A, and with "P x 0.001" the largest power is 32.8 kW, below what this site draws (up to 125 A per phase, 82.5 kVA). The guide's own numbers therefore fit only if the registers carry **secondary values**: current in mA at the CT's 5 A secondary (5,000 = full scale) and power in W at that secondary (a few kW at most). That is also what section 4 of the guide says ("apply CT and PT ratios"). So the table marks currents and powers `ct = 1`, and **if the site test shows it**, `ct_mult` (a setting that can also be changed remotely) is set to the CT ratio: 40 for a 200/5 CT. Until the site test, `ct_mult` stays 1. The alternative (the meter applies its own CT setting and sends primary values in a finer or wider format) is settled by the same test: the correction rule in the file header covers both.

## 2. CT ratio (CTs on hand, ratio not known yet)

Site facts (`docs/QUESTIONS.md`): 200 A main breaker; 82.5 kVA PLN contract = 3 x 125 A limiter per phase; the CT ratio is entered in the meter's menu.

| CT | Ratio | Remark |
|---|---|---|
| **200/5 A** | 40 | **The usual choice for a 200 A main**: the primary is at least the breaker rating, 5 A secondary is what the FCN300 and most meters expect. Most likely what you hold |
| 150/5 A | 30 | Covers the 125 A PLN limit. PLN's own CTs for 82.5 kVA are often this size (one paper quoting a 2012 PLN standard; not checked against the current rule). Better resolution at night load |
| 250/5, 300/5 A | 50, 60 | Headroom; coarser at low load |
| 100/5 A | 20 | Too small: saturates above 100 A |

Common CT primaries are 100, 150, 200, 250, 300, 400 A; the secondary is 5 A or 1 A. **Do not guess the ratio: read it.**

1. **Read the label on each of the three CTs** and photograph it (for example `200/5A`, class 0.5 or 1, burden in VA). All three must be the same. The FCN300 takes `/5A` and `/1A` secondaries: a CT marked in mV (for example 0.333 V) or 0.1 A does not work with it.
2. **Enter it in the meter's menu** (CT1 = primary, CT2 = secondary), by the electrician or the supervisor, so the LCD shows primary amps and kW. The logger and its scripts only **read** the meter: nobody writes to its configuration registers (`docs/install/README.md`).
3. **Cross-check** with a clamp meter on one phase cable at a steady load: the LCD current within about 2 %. If a label is unreadable, the ratio is (clamp on the primary cable) / (clamp on the CT's secondary lead): **electrician only**; never open a CT's secondary while the primary carries current, and short its terminals first.
4. **Write the ratio down** (Q30 and the as-built sheet).
5. A wrong ratio scales every ampere, kW and kWh by the **same factor**, in the meter and in our data. It is recoverable: once the true ratio is known, the history is multiplied by a constant. Settle it on day one anyway.

The logger's CTs are its own. Do not clamp onto, or share a circuit with, PLN's metering CTs.

## 3. Defaults to start with (from the guide)

- Slave ID 1, 9600 baud, 8-N-1
- Readings: 0x0000 to 0x0010 (V, V L-L, I, Hz, P per phase, P/Q/S total, PF)
- Energy: 0x0018 (high word) + 0x0019 (low word), kWh = (high x 65536 + low) / 100
- CT ratio: 0x0030 / 0x0031 (read only; do not write)

Everything above sits in a **register table**: address, function code, type (u16, s16, u32, s32, float), word order, scale, whether `ct_mult` applies. A correction found on site is a file change on the SD card, not a firmware change. **Remote settings cannot change the table; they can change `ct_mult`.**

## 4. On-site register check (first visit, supervisor with the laptop)

**You need:** the meter with RS485 A/B terminals (issue 7), the laptop with `docs/install/labs/modbus_dump.py` (read only) and a USB-RS485 adapter, a load running on the three phases (**10 A or more per phase is best; at no load every value is 0 and proves nothing**), the electrician for anything inside the panel. Do not change the meter's settings.

1. **Photograph the LCD settings pages:** Modbus address, baud rate, parity, CT1/CT2, PT1/PT2. Use them for `--slave`, `--baud`, `--parity`.
2. **Dump:** `python modbus_dump.py --port COMx --slave 1 --baud 9600 --fc 3 4 --start 0 --count 64 --csv dump.csv`. Which function code answers? If neither: swap A/B, check address, baud, parity. Take **two dumps one minute apart** (the loads and the energy counter move).
3. **At the same moment, photograph the LCD pages** (V per phase and line to line, A per phase, kW per phase and total, kvar, kVA, PF, Hz, kWh, kvarh).
4. **Find each value by its signature** in the dump (the script prints u16, s16, and 32-bit pairs in both word orders):

   | Quantity | Looks like (u16) if the scale is... |
   |---|---|
   | Voltage 231 V | 2310 (x 0.1), 231 (x 1), 23100 (x 0.01) |
   | Frequency 50.0 Hz | 5000 (x 0.01), 500 (x 0.1) |
   | Power factor 0.95 | 950 (x 0.001), 95 (x 0.01) |
   | Current 30 A on a 200/5 CT | 750 (secondary, mA), 3000 (primary x 0.01), 300 (primary x 0.1) |
   | Power 15 kW on a 200/5 CT | 375 (secondary, W), 1500 (primary, x 0.01 kW), 150 (primary, x 0.1 kW). Above 32.7 kW in W, a 16-bit register cannot hold it: expect a 32-bit pair |
   | Energy | a 32-bit pair: the low word moves, the high word rarely |

   Nothing matches in 0x0000 to 0x003F: dump wider (`--count 256`), on both function codes, and look at the float columns (a pair near 231.0 or 50.0 is a float32 map; try both word orders).
5. **Apply the correction rule per value** (also in the header of the CSV): new scale = old scale x (LCD value / value the logger shows).
   - ratio 1 (within 2 %): keep;
   - ratio = the CT ratio (40, 30, ...): the meter sends secondary values. Keep `ct = 1` and set `ct_mult` to the ratio (console `set ct_mult 40` then `reboot`, or remotely with `manage.py set-config LOG-0001 ct_mult=40`: applied within 15 minutes, the logger restarts once); if the energy counters are off by the same ratio, set `ct = 1` on `e` and `eq`;
   - ratio 10, 100, 1000 (or 0.1, ...): wrong decimal point: change the scale in `registers.csv`;
   - a value that is its own special case (a power in a 32-bit pair, a word-swapped pair): change `type` (`u32`, `s32`, `u32sw`, `s32sw`, `f32`, `f32sw`) and the number of registers it takes; a 32-bit value uses two addresses, so move the neighbours.
   One place to look is easier than two: when I and P need different factors, set `ct = 0` on them and put the whole factor in each scale.
6. **Copy the result to the card** as `/config/registers.csv`, boot, and check `status`: every value within **1 %** of the LCD; switch a load on and off: kW and A follow; `EM01_e` counts up.
7. **Settle the energy counters before the logger is left running.** A later change of the `e` scale makes the counter jump (alarm A19) and puts a false energy step into the OED import. Compare the logged kWh with the LCD at the start and 10 minutes later, and later with the PLN meter over a few days.
8. **Also on site, with the electrician:** reverse one CT on purpose for 6 minutes and look for **A30** (negative power on a phase), then put it back; unplug A or B for a minute and look for **A03**.
9. **Write it down:** `docs/meter/fcn300-3e4y-verified.md` (raw dump, LCD photos, final table, CT ratio) and commit the final `registers.csv` here so the next logger starts from it.

If the dump contradicts the guide and no scale or type fixes it, **do not stay on site experimenting**: keep the dump and the photos, send them (a new table is quick to build from a dump), and ask the supplier or FORT for the "communication protocol" sheet of the exact model.
