# Tutorial 4: Modbus registers: read, change and test the meter table

Draft, 8 November 2026. For the technician or student who will check the meter's registers on site and fix the logger's register table, and for anyone who wants to practise first.
Level: beginner. Every term is explained the first time it appears, and again in the [glossary](#appendix-c-glossary).

| | |
|---|---|
| **For** | Technicians and students, with the supervisor. The meter itself is touched only by the electrician |
| **Where** | Your laptop (Windows, PowerShell, or Linux) for Parts 1 to 3; the office bench with the logger for Part 4; the hotel for Part 6 |
| **Time** | Part 3 (no hardware): about 1 hour. Part 4 (logger and simulator): about 1 hour. Part 6 (real meter): the first site visit |
| **Before** | Parts 1 to 3: nothing but the laptop. Part 4: the logger with its RS485 pins known and working ([tutorial 1](1-LOGGER-ON-SITE.md), T2) and a USB-RS485 adapter |
| **After** | The meter's registers are checked on site with [`docs/meter/README.md`](../meter/README.md) section 4, which this tutorial prepares you for |

**Status.**
- The **register table of the real meter is not verified**, and the spare meter at the office has **no Modbus port**: the check happens on site, at the first visit.
- The **simulator** (`tools/modbus_sim/`) and its `check` and `dump` modes were run and have unit tests. The `serve` mode was tested with `modbus_dump.py` through a virtual serial pair, **not yet with the logger**.
- The logger's console texts quoted here come from the firmware source (written for 0.3.0, still valid in 0.4.0), **not yet seen on the board**. Where the board prints something different, correct this tutorial.
- Outputs marked **real output** were produced by the tools on a laptop.

**Conventions.**
- Each command is in its own box. The line above the box says where it runs: **Laptop (PowerShell)**, **Logger console** (the USB serial console, 115200 baud, tutorial 1 section A5), or **SD card on the laptop**.
- `<...>` is a placeholder: replace it, brackets included.
- **Read only.** Nothing in this tutorial writes to the meter. The simulator refuses writes too.

## Contents

- [Part 0: the ideas](#part-0-the-ideas)
- [Part 1: set up the laptop](#part-1-set-up-the-laptop)
- [Part 2: read a register table](#part-2-read-a-register-table)
- [Part 3: test a table with no hardware (three exercises)](#part-3-test-a-table-with-no-hardware-three-exercises)
- [Part 4: test the real logger against the simulator](#part-4-test-the-real-logger-against-the-simulator)
- [Part 5: recipes to change a table](#part-5-recipes-to-change-a-table)
- [Part 6: the real meter at the hotel](#part-6-the-real-meter-at-the-hotel)
- [Part 7: after a change](#part-7-after-a-change)
- [Part 8: troubleshooting](#part-8-troubleshooting)
- [Appendix A: the simulator](#appendix-a-the-simulator)
- [Appendix B: cheat sheet](#appendix-b-cheat-sheet)
- [Appendix C: glossary](#appendix-c-glossary)

---

## Part 0: the ideas

### 0.1 What a register is

The meter talks **Modbus RTU** over **RS485**: the logger (the **master**) asks, the meter (the **slave**) answers. Everything the meter knows is stored in **registers**: numbered boxes of 16 bits (a number from 0 to 65535). A request says: *"slave 1, function 3, give me 17 registers starting at number 0"*.

- The **address** (number) is written 0-based in the frame: `0x0006` is the 7th register. Some manuals write **PLC addresses** instead: 40007 means "holding register, address 6". The logger always uses the 0-based address.
- The **function code (FC)** says which family of registers: **FC03** = holding registers, **FC04** = input registers. The same address can hold different things in the two families, and a meter may answer only one of them. We try both.
- One register holds a small number. A bigger number or a decimal number takes **two registers** (32 bits): a **u32/s32** integer or a **float32** (IEEE decimal number). The two words can come in two orders: **high word first** (`u32`, `f32`) or **low word first** (`u32sw`, `f32sw`, "sw" = swapped). Only the meter's documentation, or an experiment, tells.
- A register holds a plain integer, so the meter fixes a **scale**: raw `2301` means 230.1 V (scale 0.1).
- **Signed or not:** a power that can go negative (export, or a reversed CT) needs a signed type (`s16`, `s32`). An unsigned one shows a small negative number as 65000.

### 0.2 What the logger does with its table

Every 15 seconds, for each value in its table (a line of `registers.csv`), the logger does this, in this order:

1. **Groups** the table lines into few requests: registers that **touch** each other are read together (the proposed table gives two requests: 17 registers from `0x0000`, and 4 from `0x0018`).
2. **Reads** each request. If the meter answers an error to a request (for example *illegal data address*), **every value of that request is lost**, not only the bad one.
3. **Decodes** the words with the line's `type` (and word order).
4. Multiplies by the line's `scale`.
5. If the line has `ct = 1`, also multiplies by the setting `ct_mult`.
6. Writes the result in the column `EM01_<name>`.

A worked example, current I1 with the proposed table and `ct_mult = 50`:

```
raw word 1260  ->  x 0.001 (scale)  ->  1.260 A  ->  x 50 (ct = 1, ct_mult = 50)  ->  63.000 A
```

The 1.260 A is what the meter's **secondary** carries (the CT's 5 A side). The 250/5 CT turns it into 63 A in the cable. If the meter already did that multiplication itself, it would send 6300 (63.00 A) and `ct` must be 0.

### 0.3 What can go wrong, and how it looks

The logger shows one number; the LCD of the meter shows the truth. The **ratio** `LCD / logger` tells what is wrong:

| Ratio | Meaning | Fix |
|---|---|---|
| 1 (within 2 %) | right | nothing |
| **50** (the CT ratio) | the meter sends **secondary** values | `ct = 1` on the line, `ct_mult = 50` |
| 10, 100, 1000 (or 0.1, ...) | decimal point | new scale = old scale x ratio |
| 1/50 of what you expect after `ct_mult` | the meter already sends **primary** values | `ct = 0`, or `ct_mult = 1` |
| no ratio fits, 0, 65535, or huge numbers | wrong address, function code, type or word order | dump again and rebuild the line (Part 3, exercise 3) |
| no value at all, `EM01_n` = 0 | no answer: wiring, slave id, baud, or the whole request refused | Part 8 |

### 0.4 Where the table lives

- **Built into the firmware**: the proposed table ([`docs/meter/registers-proposed.csv`](../meter/registers-proposed.csv) is the same thing as a file). It works with no SD file.
- **`/config/registers.csv` on the SD card** replaces it entirely. It is read **once, at boot**. A change means: power off, edit the file on a laptop, put the card back, boot. No reflashing.
- **What can be changed remotely**, since firmware 0.4.0: the table itself and the settings `meters`, `mb_baud`, `mb_format` and `ct_mult`, from the platform's page **`/live/adab/register`** (side menu of the site page, **Meter registers**) or with `manage.py set-registers` / `set-config`. The logger takes a new table at its next settings check (every 15 minutes, or the console command `config`), checks every line again, writes it as `/config/registers.csv` (the old file becomes `registers.bak`) and restarts. Steps: [`docs/meter/README.md`](../meter/README.md#changing-the-register-table).

---

## Part 1: set up the laptop

**Laptop (PowerShell)**: check that Python 3.8 or newer is installed.

```
python --version
```

Expected: `Python 3.x.y`. If the command is not found, install Python from python.org (tick "Add python.exe to PATH"), then open a new PowerShell.

**Laptop (PowerShell)**: install the two libraries (`pyserial` talks to the serial port; `minimalmodbus` is used by the dump script).

```
pip install pyserial minimalmodbus
```

**Laptop (PowerShell)**: get the repository and go to its folder (skip the first command if you already have it).

```
git clone https://github.com/julien355/esp32-datalogging.git
```

```
cd esp32-datalogging
```

**Laptop (PowerShell)**: run the simulator's own tests, to be sure it works on your laptop.

```
python -m unittest discover -s tools/modbus_sim
```

Expected: `OK` (35 tests; one is skipped, `skipped=1`, on Windows: it needs a Linux serial terminal).

**Laptop (PowerShell)**: list the meter layouts the simulator knows.

```
python tools/modbus_sim/modbus_sim.py profiles
```

**Real output:**

```
float32-fc4    float32, low word first, on FUNCTION CODE 4, different addresses
primary-16bit  16-bit, PRIMARY values (the meter applies its CT setting), finer scales
proposed       the proposed table (docs/meter/registers-proposed.csv): 16-bit, SECONDARY values (mA, W)
```

Each is a **fake meter** with its own way of storing numbers. Part 3 gives you three exercises, one per meter. The simulated site has the CTs of Adab: **250/5**, three phases of about 60, 55 and 70 A at 231 V, power factor 0.92.

---

## Part 2: read a register table

A table is a text file, one value per line:

```
name,fc,addr,type,scale,ct,agg
i1,3,0x0006,u16,0.001,1,minmax
```

| Field | Meaning | Here |
|---|---|---|
| `name` | Column name `EM01_<name>`, 7 characters at most | `i1`: current of phase 1 |
| `fc` | Function code: 3 or 4 | 3 |
| `addr` | 0-based address, `0x..` hex or decimal. **A leading 0 means octal**: write `16`, not `016` | `0x0006` |
| `type` | `u16 s16 u32 s32 u32sw s32sw f32 f32sw` | `u16`: one register, no sign |
| `scale` | raw x scale = value in the unit of the column | 0.001: raw is milliamps |
| `ct` | `1` = also multiply by `ct_mult` | 1 |
| `agg` | `minmax` (mean + `_min` + `_max` columns), `last` (counters: kWh), `mean` | `minmax` |

Rules of the logger that surprise people (the `check` mode of Part 3 warns about each):

- Lines starting with `#` and the header line are ignored. A line with fewer than 6 fields is skipped silently.
- A line with a bad `type` or `fc` is skipped, and the log says `registers.csv: bad line skipped`.
- A scale that is not a number becomes **0** (all values 0). An address that is not a number becomes **0**.
- A mistake in `agg` becomes `mean` (no `_min`/`_max` columns).
- **At most 32 lines** are read; the rest is ignored.
- If **no** line is valid, the logger falls back to the built-in table. Always read the boot log (Part 4.4).
- The **number of decimals** in the record comes from the scale: 0.001 gives 3 decimals, 1 gives none, except for floats which always get at least 3.

**Reading the proposed table:** [`docs/meter/registers-proposed.csv`](../meter/registers-proposed.csv) has the 19 lines. Voltages `v1..v31` are 16-bit at 0.1 V. Currents `i1..i3`, powers `p1 p2 p3 p q s` have `ct = 1` (the hypothesis: secondary values). `pf` is signed. The energy counters `e` (kWh) and `eq` (kvarh) are 32-bit, high word first, at 0.01, `ct = 0`, kept as the `last` value of the minute.

**On the logger**, `regs` prints the table in use and `header` the CSV columns it produces:

**Logger console**

```
regs
```

Expected (from the firmware code): the line `name,fc,addr,type,scale,ct,agg`, then one line per value, in the format above. Copy it into a file if you want to edit it.

---

## Part 3: test a table with no hardware (three exercises)

The `check` mode of the simulator **replays what the logger does** (Part 0.2): it groups your table into requests, reads them from a fake meter, decodes, multiplies, and compares with the **true value** (what the meter's LCD would show). For each wrong value it prints a hint. It also warns about the silent rules of Part 2.

The command, in general:

```
python tools/modbus_sim/modbus_sim.py check --regs <your table> --ct-mult <the logger's ct_mult> --profile <the fake meter>
```

Make a working copy of the proposed table first, so the original stays clean.

**Laptop (PowerShell)**

```
mkdir work
```

```
copy docs\meter\registers-proposed.csv work\my_registers.csv
```

(On Linux or macOS: `mkdir work` and `cp docs/meter/registers-proposed.csv work/my_registers.csv`; use `/` in paths.)

### Exercise 1: the meter that sends secondary values (about 15 minutes)

The default fake meter (`proposed`) stores currents in mA and powers in W at the CT's secondary. The logger's `ct_mult` is still 1.

**Laptop (PowerShell)**

```
python tools/modbus_sim/modbus_sim.py check --regs work/my_registers.csv --ct-mult 1
```

**Real output** (lines shortened with `...`; the other rows say `ok`):

```
Requests the logger sends (2):
  FC03 0x0000 x17  -> ok
  FC03 0x0018 x4   -> ok

name    fc   addr type            raw     logger shows     true value true/logger  verdict
v1       3 0x0000 u16            2301        230.1 V         230.1 V        0.9999  ok
...
i1       3 0x0006 u16            1260        1.260 A        62.984 A         49.99  WRONG: needs x50 more: the meter sends SECONDARY values: ct_mult = 50
...
p        3 0x000D s16             810        0.810 kW       40.496 kW        49.99  WRONG: needs x50 more: the meter sends SECONDARY values: ct_mult = 50
...
10 of 19 values within 1 % of the true value.
```

Read it: voltage, frequency, power factor and the energy counters are right. The 9 values with `ct = 1` are **50 times too small**: the ratio column says 50 = the CT ratio. The logger multiplies them by `ct_mult`, which is 1. Now give it the right `ct_mult`:

**Laptop (PowerShell)**

```
python tools/modbus_sim/modbus_sim.py check --regs work/my_registers.csv --ct-mult 50
```

Expected: `19 of 19 values within 1 % of the true value.` On the real logger this is the setting `ct_mult` (`set ct_mult 50`, then `reboot`; Part 5, recipe 2).

**What to remember:** when the ratio equals the CT ratio, the fix is `ct_mult`, not the scale. And the energy counters were right the whole time: the meter counted them in primary units, so they stay `ct = 0`. If it had been otherwise, you would put `ct = 1` on `e` and `eq` too.

### Exercise 2: the meter that already sends primary values (about 20 minutes)

The second fake meter applies its own CT setting and sends **primary** values, with finer scales (current in 0.01 A, power in 0.01 kW). The logger's table is still the proposed one.

**Laptop (PowerShell)**

```
python tools/modbus_sim/modbus_sim.py check --profile primary-16bit --regs work/my_registers.csv --ct-mult 1
```

**Real output** (shortened):

```
i1       3 0x0006 u16            6298        6.298 A        62.984 A            10  WRONG: 10 times too small: new scale = 0.01
...
p        3 0x000D s16            4050        4.050 kW       40.496 kW        9.999  WRONG: 10 times too small: new scale = 0.01
...
10 of 19 values within 1 % of the true value.
```

This time the ratio is **10**, not 50: a decimal point. The hint gives the new scale, 0.01. **Your task:** edit `work/my_registers.csv` with a text editor (Notepad is fine): on the lines `i1 i2 i3 p1 p2 p3 p q s`, change the scale `0.001` to `0.01`, and set `ct` to `0` (the meter did the CT multiplication itself, so nothing is left for `ct_mult` to do). Save, then run the same command again.

Expected: `19 of 19 values within 1 % of the true value.`

Now make **the classic mistake**, to recognise it later. Put the original table back and try to "fix" it with `ct_mult`:

**Laptop (PowerShell)**

```
copy docs\meter\registers-proposed.csv work\my_registers.csv
```

```
python tools/modbus_sim/modbus_sim.py check --profile primary-16bit --regs work/my_registers.csv --ct-mult 50
```

**Real output** (shortened):

```
i1       3 0x0006 u16            6298      314.900 A        62.984 A           0.2  WRONG: the CT ratio is applied twice: the meter already sends PRIMARY values: ct = 0 on this line, or ct_mult = 1, and scale x10 (new scale = 0.01)
```

Now the logger shows 5 times **too much** (ratio 0.2). When a value is off by the CT ratio in either direction, ask: *does the meter already apply its CT setting?* The LCD cannot tell you; only a comparison with a known value can. That is why the on-site check starts with the numbers on the LCD.

### Exercise 3: no information at all (about 45 minutes)

The third fake meter shares nothing with the guide: other addresses, other function code, other number format. The proposed table fails completely:

**Laptop (PowerShell)**

```
python tools/modbus_sim/modbus_sim.py check --profile float32-fc4 --regs work/my_registers.csv
```

**Real output:**

```
Requests the logger sends (2):
  FC03 0x0000 x17  -> EXCEPTION 02 (illegal data address 0x0000: not in this meter): every value in this request is lost
  FC03 0x0018 x4   -> EXCEPTION 02 (illegal data address 0x0018: not in this meter): every value in this request is lost
...
0 of 19 values within 1 % of the true value.
```

This is what a table that does not match looks like on site: **no values**, not wrong values. You now do what you will do at the hotel: take a dump and rebuild the table. Without hardware, ask the simulator for the dump (with a real meter you run `modbus_dump.py`, which prints the same columns):

**Laptop (PowerShell)**: the guide's family (FC03) first.

```
python tools/modbus_sim/modbus_sim.py dump --profile float32-fc4 --fc 3 --start 0 --count 64
```

Expected: `(6 of 64 registers answered)`. Only `0x0030` to `0x0035` answer, with the values 250, 5, 1, 1, 1, 2: the CT primary and secondary, the PT primary and secondary, the slave address and the baud code (2 = 9600). They are the "configuration registers" of the guide. Nothing lives at the addresses of the table. Then the input registers:

**Laptop (PowerShell)**

```
python tools/modbus_sim/modbus_sim.py dump --profile float32-fc4 --fc 4 --start 0 --count 64
```

**Real output** (the first rows):

```
--- FC04  simulated  (38 of 64 registers answered) ---
 addr    hex     u16     s16 |  u32 hi-lo     s32 hi-lo   float hi-lo |  u32 lo-hi     float lo-hi
0x0000  0x157F   5503    5503 |   360661862    360661862     5.155e-26 |  1130763647        230.08
0x0001  0x4366  17254   17254 |  1130764364   1130764364        230.09 |   407651174      2.64e-24
0x0002  0x184C   6220    6220 |   407651175    407651175      2.64e-24 |  1130829900        231.09
0x0003  0x4367  17255   17255 |  1130859271   1130859271        231.54 |  2332509031   -2.6051e-32
...
0x000C  0xF00E  61454   -4082 |  4027466363   -267500933   -1.7611e+29 |  1115418638        62.984
```

How to read it:

1. The meter answers **FC04**, from 0x0000 to 0x0025 (38 registers, no holes).
2. In the `u16` column nothing looks like 230 or 50. Look at the **float** columns. At `0x0000` the last column (**float lo-hi**) says `230.08`: a voltage. At `0x0002` it says `231.09`, at `0x0004` `231.54`: three phase voltages, **two registers apart**. So these are 32-bit floats, **low word first**: type `f32sw`.
3. Then 399.39, 400.66, 399.78 at `0x0006`, `0x0008`, `0x000A`: line-to-line voltages. At `0x000C`: `62.984`, a current in amperes (the unit is already primary: no scale, no `ct`).
4. Continue down the dump: three more currents, the frequency (about 50), powers, the power factor (below 1), the two energy counters.
5. The scale of a float is **1**, `ct` is 0: the values are already in V, A, kW.

**Your task:** write `work/float_registers.csv` with 19 lines (`name,fc,addr,type,scale,ct,agg`), `fc` 4, type `f32sw`, scale 1, `ct` 0, using the same names as the proposed table. Use `check` to test it as you go:

```
python tools/modbus_sim/modbus_sim.py check --profile float32-fc4 --regs work/float_registers.csv
```

When it says `19 of 19`, compare with the answer in `tools/modbus_sim/profiles/float32-fc4.csv` (it describes the fake meter itself, so it is the right table). Notice what `check` shows for the requests: **one** request of 38 registers (`FC04 0x0000 x38`), because every register touches the next one.

> **Tip for a real dump.** If a dump prints `illegal data address` for whole blocks, the meter is **strict**: it refuses a request that spans a register it does not have. Dump again with one register per request (`--block 1` in `modbus_dump.py`): the answering registers show up, and the holes are normal. The logger itself avoids spanning holes, since it merges only registers that touch.

---

## Part 4: test the real logger against the simulator

Here the **laptop plays the meter** and the **logger reads it** through the real RS485 wiring. It proves that the wiring, the direction control, the SD file, the decoding and the whole chain to the VPS work **before** the site visit. It cannot prove anything about the real meter's registers.

**You need:** the logger with its RS485 pins set (`pin_rs_tx`, `pin_rs_rx`, `pin_rs_de`, tutorial 1 T2), a **USB-RS485 adapter with automatic direction control** (most dongles; if the logger always times out and the wiring is right, this is the first suspect), and the logger's console cable.

### 4.1 Wire it

Laptop adapter `A` to the logger's `A`, `B` to `B` (and `G` to `G` if the adapter has one). Swapped `A`/`B` only gives timeouts: swap and retry. The logger's `120` jumper can stay on (the cable is short).

### 4.2 Start the fake meter

Find the adapter's port: **Device Manager > Ports (COM & LPT)** on Windows (for example `COM7`), `/dev/ttyUSB0` on Linux.

**Laptop (PowerShell)**

```
python tools/modbus_sim/modbus_sim.py serve --port COM7 -v
```

**Real output:**

```
Simulated meter on COM7, slave 1, 9600 8-N-1, layout proposed, CT 250/5. Read only. Ctrl+C to stop.
```

Leave it running. With `-v` every request the logger sends is printed, for example (real output format):

```
    1.02s  FC03 0x0000 x17 -> ok
    1.07s  FC03 0x0018 x4 -> ok
```

Two lines every 15 seconds means the logger reads the table in two requests. Open a second PowerShell for the next commands. `Ctrl+C` stops the simulator.

### 4.3 Look at the raw registers from the logger

**Logger console**: read 3 registers like a technician would on site.

```
mb 1 3 0 3
```

Expected (format from the firmware; the numbers move a little each time):

```
> mb 1 3 0 3
FC03 0x0000 (    0) 0x08FD u16= 2301 s16=  2301
FC03 0x0001 (    1) 0x0907 u16= 2311 s16=  2311
FC03 0x0002 (    2) 0x090B u16= 2315 s16=  2315
```

The command is `mb [slave] [fc] [start] [count]`; it prints each register as hex, unsigned and signed. **It reads in chunks of 16 registers**: a longer range on a strict meter fails chunk by chunk with `error 0x02` (illegal data address) where there is a hole. Try:

```
mb 1 3 16 4
```

Expected: `FC03 0x0010..0x0013 error 0x02`, because address 0x0011 does not exist in this fake meter. This is the **strict meter** of Part 3. A timeout looks different: `error 0xE2 (timeout: wiring, A/B, id, baud)`.

### 4.4 Put the table on the card

1. **Logger console**: `status`, to see it is healthy, then power the logger off (unplug USB).
2. Take out the microSD card, put it in the laptop (card reader). It appears as a drive.
3. On the card, make the folder `config` if it is not there, and copy your table into it **under the exact name `registers.csv`**: `config\registers.csv` (start with the proposed table: `docs\meter\registers-proposed.csv`).
4. Eject the card in Windows, put it back in the logger, power on.
5. **Logger console**, in the boot messages: look for the table line.

Expected (format from the firmware; the pin numbers are examples, yours are the ones you verified):

```
[2026-11-08T10:15:02Z] Meter: register table from SD /config/registers.csv (19 values)
[2026-11-08T10:15:02Z] Meter: 1 meter(s), RS485 TX=17 RX=18 DE=-1 9600 8N1, 2 request(s) per read
```

**Or send it from the platform** (the logger online, firmware 0.4.0 or later): on `/live/adab/register`, **Import CSV file...** with your table, **Check**, a comment, **Send to the logger**; then type `config` on the console so the logger fetches it at once. It restarts by itself; the page goes to **Applied**. Try it once at the bench, so that you know the way before the site, then **Back to the built-in table**.

**Read these two lines every time.** The first must say *from SD* with the number of values you expect. If it says `built-in FCN300 register table (19 values, not verified)`, your file was not found, or **none** of its lines was valid. `2 request(s)` is right for the proposed table; a different number is a sign your table groups differently.

### 4.5 See the values

**Logger console**, after the next 15-second sample:

```
status
```

In the line `Last sample:` you will see `EM01_v1=230.1 EM01_v2=...` and so on (the column names are `EM01_` + the `name` of each line). With `ct_mult` still 1, the currents and powers are 50 times too small, as in exercise 1. Set it:

```
set ct_mult 50
```

```
reboot
```

Expected: `ct_mult set. Type 'reboot' to apply.` After the reboot, `status` shows `EM01_i1=63.000` (about 60 A, moving a little) and `EM01_p=40.500` (kW).

### 4.6 Check the record and the VPS

After a minute, one row per minute is written. **Logger console:**

```
tail /data/2026/11/2026-11-08.csv 2
```

(use today's UTC date). The row has `EM01_i1,EM01_i1_min,EM01_i1_max`: mean, lowest and highest of the four 15-second samples, and `EM01_n` = 4 (4 good reads in the minute). On the VPS, the live page `/live/adab/` shows the same numbers a few seconds later. Compare it with the simulator's true values (`check` prints them). **Office test rows must be removed from the VPS before the site** ([`docs/VPS-SETUP.md`](../VPS-SETUP.md) step 8, and tutorial 1 section A).

### 4.7 Break it on purpose

Each of these takes two minutes and shows a behaviour you will meet on site. Stop the simulator (`Ctrl+C`) and start it again with the option.

| Start the simulator with | What you should see on the logger and VPS |
|---|---|
| `--silent-after 60` | After a minute the meter "dies": `status` shows `EM01: no answer (n in a row)`, `EM01_n` = 0, empty values, and after about a minute **A03 Meter not answering** in the alarm log |
| `--drop-pct 30` | A third of the requests get no answer; the logger retries each request once, so most reads still succeed. `EM01_n` stays 4 or 3. Shows why a flaky cable gives noisy `EM01_n` |
| `--profile primary-16bit` | The proposed table now reads values 10 times too small (exercise 2), with the `ct_mult` of 50 even 5 times too big. Fix it with the file on the card, not with `ct_mult` |
| `--profile float32-fc4` | No values at all, `EM01_n` = 0, A03 after a minute (exercise 3). The **boot log** said nothing wrong: a table that does not match the meter is not an error for the logger |
| `--unmapped zero` | Registers that do not exist read as 0 instead of an error (some real meters do that): a table with a wrong address then gives zeros, not silence |
| `--amps 125,120,110` | A heavy load: an alarm threshold test. A37 (phase current near the PLN limit) needs the VPS site profile with 82.5 kVA / 220 V |

---

## Part 5: recipes to change a table

Always: **copy the table, change one thing at a time, `check` it, then put it on the card, then read the boot log.** Keep the old file (`registers-before.csv`) so you can go back.

**Recipe 1: a value is 10, 100 or 1000 times off** (scale). New scale = old scale x (LCD / logger). Example: current shows 6.298, LCD says 62.98: ratio 10, `0.001` becomes `0.01`.

**Recipe 2: the value is off by the CT ratio** (secondary values). Put `ct = 1` on the lines that are secondary, and `ct_mult` = CT primary / CT secondary = **50** for the 250/5 CTs.
- Console: `set ct_mult 50`, then `reboot`.
- Remotely, on the VPS (user `ai`): `cd /opt/arkan-monitoring/server && docker compose exec ingest python tools/manage.py set-config LOG-0001 ct_mult=50` (taken within 15 minutes; the logger restarts once).
- If the meter is secondary for current and power but **primary for energy**, keep `ct = 0` on `e` and `eq`. If the energy is secondary too, `ct = 1` on them. Settle this **before** leaving the logger running (Part 7).
- If current needs x50 and power x10 and ..., put the whole factor in each scale, `ct = 0` everywhere, `ct_mult = 1`: one place to look.

**Recipe 3: nothing answers on FC03.** Change `fc` to `4` on every line (the same addresses may live in the input registers). Test: `mb 1 4 0 17`.

**Recipe 4: a 32-bit value is garbage or huge.** Try the other word order: `u32` <-> `u32sw`, `s32` <-> `s32sw`, `f32` <-> `f32sw`. A float with the wrong order gives absurd values like 1.5e-33 or 1e+29. A counter with the wrong order jumps by 65536 times its step.

**Recipe 5: a value can be negative** (power with a reversed CT, export). Use `s16` or `s32`. If a power of 65000 appears where a small negative one should, the type was unsigned.

**Recipe 6: the address is different.** Change `addr`. A 32-bit value takes two addresses, so the next line starts two further (`0x0018` then `0x001A`). Test the address alone with `mb` first.

**Recipe 7: add or remove a value.** Add a line with a **new name of 7 characters or less**, no more than 32 lines in all. Names the VPS uses for alarms, the live page and the OED export are `v1 v2 v3 v12 v23 v31 i1 i2 i3 f p1 p2 p3 p q s pf e eq`: **do not rename them**. A different list of columns makes the logger start a second file that day (`..._2.csv`) and the VPS records a column change (`docs/DATA-FORMAT.md`): harmless, but keep it rare.

**Recipe 8: a second meter.** `set meters EM01:1,EM02:2` (slave 1 and 2 on the same RS485 pair). The same table is read from both; the columns are `EM02_...`.

---

## Part 6: the real meter at the hotel

The loop is the same as in Parts 3 and 4, with the meter's LCD as the truth instead of the simulator.

1. Prepare: read [`docs/meter/README.md`](../meter/README.md) sections 2 and 4 (the CT, and the on-site procedure). Bring the laptop with this repository, the USB-RS485 adapter, a clamp meter, and **a copy of the proposed table on the SD card**.
2. The **electrician** opens the panel. You photograph: the CT labels (they should say 250/5), the meter's label, its back (RS485 `A`/`B`), and the LCD settings pages (address, baud, parity, CT1/CT2).
3. Run the dump and photograph the LCD at the same moment: `python docs/install/labs/modbus_dump.py --port COM7 --fc 3 4 --start 0 --count 64 --csv dump.csv` (add `--block 1` if blocks fail). Take two, a minute apart.
4. Use your Part 3 skills: find each value by its signature, work out the ratio, fix the table (Part 5), `check` the new table on the laptop first, then put it on the card (or send it from `/live/adab/register` if the logger is online: same result, no need to open the box).
5. A load must be running: at no load, every value is 0 and proves nothing.
6. **Do not experiment on site.** If the dump contradicts everything (exercise 3 with no solution), keep the dump and the photos and send them to the supervisor: a new table is quick to build from a dump.

---

## Part 7: after a change

- **Write it down**: raw dump, LCD photos, the final table and the CT ratio in `docs/meter/fcn300-3e4y-verified.md`; commit the final `registers.csv` to this repository so the next logger starts from it.
- **The energy counter is cumulative.** If you change the scale of `e` while the logger is recording, the counter **jumps** (alarm **A19** "Energy counter went backwards" if it falls) and OED shows a false step. Fix the energy lines **first**, with the logger recording nothing that matters, and check the logged kWh against the LCD at the start and 10 minutes later.
- **Old rows keep their old numbers.** The VPS stores what the logger sent; changing the table does not change history. There is no command yet to rescale old rows. A wrong factor is a constant, so a one-off script can fix it later: write down the date and time of the change (the `boot` column of the first new row marks the restart: `sw:remote_regs@0.4.0` for a table sent from the register page, `sw:console@0.4.0` or `poweron@0.4.0` for a card changed by hand; the register page's **History** also keeps the time and the comment of every version sent).
- **Test data**: remove the office/bench data from the VPS before the site ([`docs/VPS-SETUP.md`](../VPS-SETUP.md) step 8) so the bench's fake meter does not end up in the record.
- **`ct_mult` is a setting, the table is a file.** Both can be changed remotely (firmware 0.4.0 or later): the table from the register page or `manage.py set-registers`, the settings from the same page (**Meter link settings**) or `manage.py set-config`. When I and P are off by the CT ratio, change `ct_mult`, not every scale.

---

## Part 8: troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `mb` prints `error 0xE2 (timeout: ...)` | No answer: wiring, `A`/`B` swapped, wrong slave id, wrong baud or parity, simulator not running, adapter without automatic direction | Swap `A`/`B`; check `meters` (`EM01:1`), `mb_baud`, `mb_format`; with the simulator: is it running with the right `--port`? |
| `mb` prints `error 0x02` | The meter answers, but that address does not exist (a hole, or the wrong function code) | Try the other FC; read single registers; `mb` reads 16 at a time |
| Boot log says `built-in ... register table` | No `/config/registers.csv`, wrong name or folder, or no valid line | Check the name (`registers.csv`, not `.txt`), the folder `config`, run `check` for warnings |
| Boot log says `(n values)` with a smaller n than expected | Some lines were skipped (bad type, bad fc, fewer than 6 fields) | `check` prints `WARNING` for each; the log says `registers.csv: bad line skipped` |
| All values empty, `EM01_n` = 0 | A whole request failed (a hole in a request, or no answer) | `check` shows which request got the exception |
| Values 50 times too small or too big | `ct` / `ct_mult` | Part 0.3, Recipe 2 |
| Values 10, 100, 1000 times off | Scale | Recipe 1 |
| Garbage, 65535, 1e+29 | Type, word order, address | Recipes 4 and 6; dump again |
| Power shows a huge positive value when it should be small negative | Unsigned type | Recipe 5 |
| Energy counter jumps | A scale or word-order change while recording | Part 7 |
| Edited the file, nothing changed | The file is read at boot, or the card was not put back | Power cycle; read the boot log |
| `check` says `no true value called ...` | A name the simulator does not know | Use the standard names (Recipe 7) |
| The simulator says `Install pyserial first` | Library missing | `pip install pyserial` |
| The simulator cannot open the port | Wrong name, or another program uses it | Close other serial programs; check the name in Device Manager |

---

## Appendix A: the simulator

`tools/modbus_sim/modbus_sim.py`, Python 3.8 or newer, no library except `pyserial` for `serve`.

| Command | What it does |
|---|---|
| `profiles` | List the fake meters |
| `dump --profile P --fc 3 4 --start 0 --count 64` | Print what a register dump of the fake meter looks like |
| `check --regs FILE --ct-mult N --profile P` | Replay the logger's read of FILE and compare with the truth. Exit code 0 only when every value is right and the file has no warning |
| `serve --port PORT -v` | Answer on a serial port as the meter (slave 1, 9600 8-N-1) |

Options common to `serve`, `check`, `dump`: `--profile` (`proposed`, `primary-16bit`, `float32-fc4`), `--meter-table FILE` (your own fake meter, same format as `registers.csv`, where `ct = 1` means "this meter sends secondary values"), `--ct 250/5`, `--volts`, `--amps 60,55,70`, `--pf`, `--slave`, `--seed`, `--speed N` (energy counters count N times faster: with `--speed 60`, a minute counts as an hour).
Options of `serve`: `--baud`, `--parity N|E|O`, `--unmapped error|zero`, `--drop-pct`, `--silent-after SECONDS`, `--reply-delay-ms`, `-v`.

What it simulates and what it does not:
- It is **not** the FCN300. Its layouts are inventions to practise with. The fake meter stores the CT in registers `0x0030` and `0x0031` (250 and 5), as the guide says the real one does; `mb 1 3 48 2` reads them.
- It follows the **logger's** rules, ported from the firmware: how requests are grouped, how words are decoded, how many decimals are written. Tests check that the ported constants and the built-in table still match `firmware/src/meter.cpp`.
- A value that does not fit its register (a 125 A current at 0.001 A in 16 bits) **saturates** at 65535, and the simulator prints a note: it is how a real meter's range limit shows up.
- It answers function codes 3 and 4 only. Any write gets the exception *illegal function*.

## Appendix B: cheat sheet

| I want to... | Command |
|---|---|
| See the table in use | Logger console: `regs` |
| See the CSV columns | `header` |
| Read raw registers | `mb 1 3 0 16` (slave, function, start, count; hex allowed: `mb 1 3 0x18 4`) |
| Change `ct_mult` | `set ct_mult 50`, `reboot` (or `manage.py set-config LOG-0001 ct_mult=50`) |
| Reread the table | Power off, edit `/config/registers.csv`, power on, read the boot log |
| Send a table remotely | Page `/live/adab/register` (or VPS: `manage.py set-registers LOG-0001 table.csv --comment "..."`), then `config` on the console to fetch at once |
| Test a table on the laptop | `python tools/modbus_sim/modbus_sim.py check --regs FILE --ct-mult 50 --profile P` |
| Practise reading a dump | `python tools/modbus_sim/modbus_sim.py dump --profile float32-fc4 --fc 4` |
| Be the meter for the logger | `python tools/modbus_sim/modbus_sim.py serve --port COM7 -v` |
| Dump a real meter | `python docs/install/labs/modbus_dump.py --port COM7 --fc 3 4 --start 0 --count 64 --csv dump.csv` (`--block 1` if blocks fail) |

## Appendix C: glossary

| Term | Meaning |
|---|---|
| **Modbus RTU** | A simple question-and-answer protocol over a serial line. The logger asks, the meter answers |
| **RS485** | The two-wire electrical standard (`A`, `B`) under it; many devices on one pair |
| **Master / slave** | The one that asks (logger) / the one that answers (meter, or the simulator) |
| **Slave id** | The meter's address on the bus, 1 to 247 (default 1) |
| **Register** | A 16-bit box with a number |
| **Holding / input registers** | Two families, FC03 and FC04. The same address can mean different things |
| **Word** | One register's 16 bits |
| **High word first / low word first** | The order of the two registers of a 32-bit value. "sw" = swapped = low first |
| **u16, s16, u32, s32, f32** | Unsigned or signed integer in 16 or 32 bits; 32-bit float |
| **Scale** | Raw number times scale = the value in V, A, kW... |
| **CT (current transformer)** | The ring around a cable. 250/5: 250 A in the cable gives 5 A to the meter |
| **CT ratio** | 250 / 5 = 50 |
| **Primary / secondary** | The cable side (real amps) / the meter side (5 A at full scale). A meter may send either |
| **`ct_mult`** | The logger setting that multiplies the lines marked `ct = 1`; set to the CT ratio when the meter sends secondary values |
| **Exception** | The meter's error answer: 01 illegal function, 02 illegal data address, 03 illegal data value |
| **Hole** | An address that the meter does not have. A request that spans it fails on a strict meter |
| **Truth / LCD** | The value shown on the meter's screen, assumed right: the reference for the check |
