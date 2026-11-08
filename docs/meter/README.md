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
| 5 | Section 4 of the guide: values may be **secondary** (before the CT ratio) | Currents and powers could be 1/50 of the real value (250/5 CT) | Compare with the LCD (section 4 below) |
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

**Why these numbers, and the working hypothesis.** A 16-bit register holds at most 65,535. With "I x 0.001" the largest current is 65.5 A, and with "P x 0.001" the largest power is 32.8 kW, below what this site draws (up to 125 A per phase, 82.5 kVA). The guide's own numbers therefore fit only if the registers carry **secondary values**: current in mA at the CT's 5 A secondary (5,000 = full scale) and power in W at that secondary (a few kW at most). That is also what section 4 of the guide says ("apply CT and PT ratios"). So the table marks currents and powers `ct = 1`, and **if the site test shows it**, `ct_mult` (a setting that can also be changed remotely) is set to the CT ratio: 50 for a 250/5 CT. Until the site test, `ct_mult` stays 1. The alternative (the meter applies its own CT setting and sends primary values in a finer or wider format) is settled by the same test: the correction rule in the file header covers both.

## 2. CT ratio: 250/5 A (owner, 8 November 2026)

**Decision: the CTs are 250/5 A, ratio 50.** Site facts (`docs/QUESTIONS.md`): 200 A main breaker; 82.5 kVA PLN contract = 3 x 125 A limiter per phase.

- 250 A covers the 200 A main (80 % of the primary) with room above, and the 125 A PLN limit sits at 50 % of the primary.
- **Resolution:** 1 mA on the 5 A secondary is 0.05 A in the cable, and 1 W on the secondary is 50 W in the cable. Fine for a hotel (tens of kW); the logger prints more decimals than the meter really has.
- **Low load:** at night the hotel may draw 10 A per phase, 4 % of the primary. CTs are least accurate at the bottom of their range (a class 1 CT is typically specified to +/-3 % at 5 % of the rated current, a class 0.5 to +/-1.5 %): look at the class on the label. It affects the kWh a little, not the alarms.
- Other sizes you may meet on a label, for reference: 200/5 (ratio 40), 150/5 (30), 300/5 (60). PLN's own CTs for 82.5 kVA are often 150/5 (one paper quoting a 2012 PLN standard; not checked). They are PLN's: do not clamp onto them or share their circuit.

**Do not trust the number, read it:**

1. **Read the label on each of the three CTs** and photograph it (it should say `250/5A`, with the class 0.5 or 1 and the burden in VA). All three must be the same. The FCN300 takes `/5A` and `/1A` secondaries: a CT marked in mV (for example 0.333 V) or 0.1 A does not work with it. A label that says something else: stop and tell the owner, everything below changes with the ratio.
2. **Enter it in the meter's menu** (CT1 = 250, CT2 = 5), by the electrician or the supervisor, so the LCD shows primary amps and kW. The logger and its scripts only **read** the meter: nobody writes to its configuration registers (`docs/install/README.md`).
3. **Cross-check** with a clamp meter on one phase cable at a steady load: the LCD current within about 2 %. If a label is unreadable, the ratio is (clamp on the primary cable) / (clamp on the CT's secondary lead): **electrician only**; never open a CT's secondary while the primary carries current, and short its terminals first.
4. **Write the ratio down** (Q30 and the as-built sheet).
5. A wrong ratio scales every ampere, kW and kWh by the **same factor**, in the meter and in our data. It is recoverable: once the true ratio is known, the history is multiplied by a constant. Settle it on day one anyway.

## 3. Defaults to start with (from the guide)

- Slave ID 1, 9600 baud, 8-N-1
- Readings: 0x0000 to 0x0010 (V, V L-L, I, Hz, P per phase, P/Q/S total, PF)
- Energy: 0x0018 (high word) + 0x0019 (low word), kWh = (high x 65536 + low) / 100
- CT ratio: 0x0030 / 0x0031 (read only; do not write)

Everything above sits in a **register table**: address, function code, type (u16, s16, u32, s32, float), word order, scale, whether `ct_mult` applies. A correction found on site is a file change on the SD card, not a firmware change. Since firmware 0.4.0 the table can also be sent remotely, from the platform's page `/live/<site>/register` (see "Changing the register table" below), as can `ct_mult`.

## 4. On-site register check (first visit, supervisor with the laptop)

**Rehearse it first, without any meter:** [`../tutorials/4-MODBUS-REGISTERS.md`](../tutorials/4-MODBUS-REGISTERS.md) explains every step below, and the simulator `tools/modbus_sim/` plays a meter on the laptop (three different layouts, so you practise reading a dump, fixing scales and `ct_mult`, and rebuilding a table from scratch).

**You need:** the meter with RS485 A/B terminals (issue 7), the laptop with `docs/install/labs/modbus_dump.py` (read only) and a USB-RS485 adapter, a load running on the three phases (**10 A or more per phase is best; at no load every value is 0 and proves nothing**), the electrician for anything inside the panel. Do not change the meter's settings.

1. **Photograph the LCD settings pages:** Modbus address, baud rate, parity, CT1/CT2, PT1/PT2. Use them for `--slave`, `--baud`, `--parity`.
2. **Dump:** `python modbus_dump.py --port COMx --slave 1 --baud 9600 --fc 3 4 --start 0 --count 64 --csv dump.csv`. Which function code answers? If neither: swap A/B, check address, baud, parity. Take **two dumps one minute apart** (the loads and the energy counter move). **If whole blocks fail with "illegal data address", the meter is strict about registers it does not have: dump again with `--block 1`** (one register per request) to see which addresses really exist; the holes are normal.
3. **At the same moment, photograph the LCD pages** (V per phase and line to line, A per phase, kW per phase and total, kvar, kVA, PF, Hz, kWh, kvarh).
4. **Find each value by its signature** in the dump (the script prints u16, s16, and 32-bit pairs in both word orders):

   | Quantity | Looks like (u16) if the scale is... |
   |---|---|
   | Voltage 231 V | 2310 (x 0.1), 231 (x 1), 23100 (x 0.01) |
   | Frequency 50.0 Hz | 5000 (x 0.01), 500 (x 0.1) |
   | Power factor 0.95 | 950 (x 0.001), 95 (x 0.01) |
   | Current 30 A on a 250/5 CT | 600 (secondary, mA), 3000 (primary x 0.01), 300 (primary x 0.1) |
   | Power 15 kW on a 250/5 CT | 300 (secondary, W), 1500 (primary, x 0.01 kW), 150 (primary, x 0.1 kW). Above 32.7 kW in W, a 16-bit register cannot hold it: expect a 32-bit pair |
   | Energy | a 32-bit pair: the low word moves, the high word rarely |

   Nothing matches in 0x0000 to 0x003F: dump wider (`--count 256`), on both function codes, and look at the float columns (a pair near 231.0 or 50.0 is a float32 map; try both word orders).
5. **Apply the correction rule per value** (also in the header of the CSV): new scale = old scale x (LCD value / value the logger shows).
   - ratio 1 (within 2 %): keep;
   - ratio = the CT ratio (50): the meter sends secondary values. Keep `ct = 1` and set `ct_mult` to the ratio (console `set ct_mult 50` then `reboot`, or remotely from the register page's **Meter link settings** or with `manage.py set-config LOG-0001 ct_mult=50`: applied within 15 minutes, the logger restarts once); if the energy counters are off by the same ratio, set `ct = 1` on `e` and `eq`;
   - ratio 10, 100, 1000 (or 0.1, ...): wrong decimal point: change the scale in `registers.csv`;
   - a value that is its own special case (a power in a 32-bit pair, a word-swapped pair): change `type` (`u32`, `s32`, `u32sw`, `s32sw`, `f32`, `f32sw`) and the number of registers it takes; a 32-bit value uses two addresses, so move the neighbours.
   One place to look is easier than two: when I and P need different factors, set `ct = 0` on them and put the whole factor in each scale.
6. **Copy the result to the card** as `/config/registers.csv`, boot, and check the boot log (`Meter: register table from SD ... (n values), ... n request(s) per read`) and `status`: every value within **1 %** of the LCD; switch a load on and off: kW and A follow; `EM01_e` counts up.
7. **Settle the energy counters before the logger is left running.** A later change of the `e` scale makes the counter jump (alarm A19) and puts a false energy step into the OED import. Compare the logged kWh with the LCD at the start and 10 minutes later, and later with the PLN meter over a few days.
8. **Also on site, with the electrician:** reverse one CT on purpose for 6 minutes and look for **A30** (negative power on a phase), then put it back; unplug A or B for a minute and look for **A03**.
9. **Write it down:** `docs/meter/fcn300-3e4y-verified.md` (raw dump, LCD photos, final table, CT ratio) and commit the final `registers.csv` here so the next logger starts from it.

If the dump contradicts the guide and no scale or type fixes it, **do not stay on site experimenting**: keep the dump and the photos, send them (a new table is quick to build from a dump), and ask the supplier or FORT for the "communication protocol" sheet of the exact model.

## Changing the register table

A wrong register, a wrong scale, or a different meter: the table changes, the firmware does not.

**Where the table lives**

| Place | What |
|---|---|
| `firmware/src/meter.cpp` (`DEFAULT_TABLE`) | Built into the firmware. Used when the SD card has no `/config/registers.csv` |
| SD card `/config/registers.csv` | Replaces the whole built-in table when present. `registers.bak` next to it is the previous one |
| Platform, `sites/<site>/<device>/registers.json` | The table last sent from the page `/live/<site>/register`. `registers-history.jsonl`: every version sent |
| Logger's report (`settings-reported.json`) | The table the logger actually reads, its source (`sd` or `builtin`) and the version applied |

**From the page `https://arkan-monitoring.duckdns.org/live/adab/register`** (link "Meter registers" at the top of the site's live page; Arkan login; logger firmware 0.4.0 or later). If the site has several loggers, a list at the top right chooses one (`?device=LOG-0002`).

1. The top box shows the table **on the logger** and what was **last sent**, with a state: *No table sent*, *Waiting*, *Applied*, *Differs*, *Refused*, *Firmware too old*.
2. The editor opens with the logger's table. Change a line, add or delete lines, or load one: *Table on the logger*, *Last sent*, any version in the **History**, or **Import CSV file...** (for example the table written during the on-site check, section 4). *Edit as text* takes a pasted table. *Download CSV* saves the table being edited. Yellow lines differ from the logger's, green lines are not on the logger.
3. **Check** shows the errors (nothing can be sent until they are fixed) and the warnings (for example a standard name missing: the alarms that use it stop).
4. Write why in the comment box, then **Send to the logger**. The logger takes it at its next check (every 15 min, or the console command `config`), checks it again, writes `/config/registers.csv` (the old file becomes `registers.bak`) and restarts. Click **Refresh**: the state goes to **Applied** once the logger has reported after its restart.
5. **Back to the built-in table** makes the logger rename its file to `registers.bak` and use the firmware's table.
6. **Meter link settings** (same page): `meters` (id and Modbus address), `mb_baud`, `mb_format`, `ct_mult`. They are sent as remote settings; the logger applies them and restarts. A new meter usually needs both the table and these settings.

From the VPS command line, the same: `manage.py set-registers LOG-0001 table.csv --comment "..."`, `manage.py set-registers LOG-0001 --builtin`, `manage.py show-registers LOG-0001`.

**Rules** (checked by the page and again by the logger): one line per value `name,fc,addr,type,scale,ct,agg`; `name` 1 to 7 characters `a-z 0-9`, unique; `fc` 3 or 4; `addr` 0-based (`0x0018` or `24`); `type` `u16 s16 u32 s32 u32sw s32sw f32 f32sw`; `scale` not 0; `ct` 0 or 1; `agg` `mean`, `last` or `minmax`; at most 32 lines. **Keep the standard names** (`v1 v2 v3 v12 v23 v31 i1 i2 i3 f p1 p2 p3 p q s pf e eq`) and units (V, A, Hz, kW, kvar, kVA, kWh, kvarh): the alarms, the daily report and the OED export use them. A changed table changes the record's columns: the platform starts a `_2` day file that day.

**After any change**, check the values against the meter's LCD (within 1 %, tutorial 1 step B10), then commit the verified table to this folder (for example `registers-fcn300.csv`) through a pull request. Once a table is final, also put it in `DEFAULT_TABLE` and release a firmware, so that a new SD card does not bring back the wrong table.
