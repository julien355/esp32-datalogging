# Office preparation: build, flash, configure and test the logger before the site

Everything here is done **at the office, on the bench**, before the logger goes to the Adab hotel. The order: VPS first (so the logger has somewhere to send), then the board, then the tests, then packing.

Reference: functions and settings [`FIRMWARE.md`](FIRMWARE.md), data format [`DATA-FORMAT.md`](DATA-FORMAT.md), VPS [`VPS-SETUP.md`](VPS-SETUP.md), questions still open [`QUESTIONS.md`](QUESTIONS.md). Hardware theory, wiring drawings and site labs: [`install/README.md`](install/README.md).

> **Status.** Firmware 0.1.0 and the ingest service are written; CI compiles the firmware and runs the server tests. **Nothing has run on the real board yet.** The pin map and the meter register map are still **to verify** (T2, T4 below). Expect small fixes during the first bench day.

---

## 0. What you need

| Item | Note |
|---|---|
| Laptop with VS Code + **PlatformIO** extension (or `pip install platformio`) | Windows, macOS or Linux. Git |
| USB-C data cable | Not a charge-only cable |
| The board, the AM2301 with its 4.7 kohm pull-up, a microSD card (8 to 32 GB, FAT32) | |
| USB-RS485 adapter | Loopback test and, at the hotel, the meter register check |
| Phone | Setup portal, WiFi analyser |
| A WiFi network at the office (2.4 GHz) | The office test network; the hotel's network is set later |
| The VPS ready (`VPS-SETUP.md` steps 1 to 7) and the device token | Or a laptop server for a first test (step 3.2) |

## 1. Build and flash

```bash
git clone https://github.com/julien355/esp32-datalogging.git
```

```bash
cd esp32-datalogging/firmware
```

```bash
pio run
```

```bash
pio run -t upload
```

```bash
pio device monitor
```
- First time on Windows: if no COM port appears, install the USB driver of the board's USB chip (CH340 or CP210x), or hold **BOOT**, press **RST**, release **BOOT** to force the download mode.
- **No text in the monitor** after flashing: the board's USB-C may go through a USB-UART chip, not the native USB. Use the other build: `pio run -e logger-uart -t upload`.
- Without PlatformIO: download `firmware.bin`, `bootloader.bin` and `partitions.bin` from the CI run's artifacts on GitHub and flash them with the Espressif web flasher (erase the flash first; offsets 0x0, 0x8000, 0x10000).

At boot the monitor shows: firmware version, boot reason, RTC, SD card, TH1 chip found, meter configuration, "Setup portal open" (no WiFi set yet). Type `help`.

## 2. First configuration (two ways)

**A. Serial console** (laptop on USB):
```
set dev_id LOG-0001
set wifi_ssid OfficeWiFi
set wifi_pass ********
set srv_url https://arkan-monitoring.duckdns.org
set dev_token <token from manage.py add-device>
reboot
```

**B. Setup portal** (phone only): join WiFi `ARKAN-LOG-0001`, password `arkan-setup`, the page http://192.168.4.1 opens. Fill in, "Save and restart".

**C. SD card file** (preparing several loggers): `manage.py add-device adab LOG-0001 --sd-settings settings.txt` writes the file; add the WiFi lines; copy it to the card as `/config/settings.txt`; power the logger: it applies it, deletes the file, restarts.

Check with `show` (secrets appear as `******`) and `status`.

## 3. Bench tests: run them in this order and record the results

Tick each line in the record sheet (section 5). Times are in UTC.

### T1. Clock
1. `time`: system and RTC time. If "invalid" (first use, or no coin cell): connect to WiFi (NTP sets both) or `time set 2026-11-07T03:15:00` (UTC, **not** WITA).
2. Unplug the board for 1 minute, plug it back: `time` must still be right (RTC on its coin cell). Log line `RTC ok, system time set to ...`.

### T2. Pins and I2C (Lab 1 of the install manual)
1. `i2c`: expect 0x68 (RTC), the TH1 chip (0x38, 0x40 or 0x44), 0x48 (ADS1115).
2. Nothing found: SDA/SCL are wrong. `set pin_sda 9`, `set pin_scl 8`, `reboot`, try again.
3. `status` line `SD: ok`. If FAILED: card FAT32? Try `set pin_sd_cs 21`, `reboot`.
4. RS485 pins: read them from the back silkscreen, then `set pin_rs_tx <n>`, `set pin_rs_rx <n>`, `set pin_rs_de <n or -1>`, `reboot`.
5. **Write the verified pins in the record sheet.** They become the new defaults in the firmware.

### T3. Sensors
1. `status`, "Last sample": `TH1=31.2C/60% TH2=...`.
2. Breathe on each sensor: the values rise within 30 s.
3. Pull the AM2301 data wire: `TH2=fault`, and the record shows `TH2_n` = 0 and empty values. Plug it back.
4. Next to a reference thermometer/hygrometer for 30 min: note the differences. They become `th1_off_t`, `th2_off_t` etc. on the install day (the office is not the site).

### T4. RS485 and meter
- **With no meter** (no spare yet): RS485 loopback with the USB-RS485 adapter as in Lab 3 part A (`labs/lab3_modbus_dump`), or simply check that the logger tries: `status` shows `EM01: no answer (n in a row)` and the records have `EM01_n` = 0 with empty values. That is the correct behaviour without a meter.
- **With a Modbus simulator** on the laptop (for example `pip install pymodbus` and its simulator, slave 1, 9600 8N1, holding registers 0 to 0x40 with test values): `mb 1 3 0 64` must show the words; `status` shows `EM01_v1=...`.
- **At the hotel** (first short visit, before the install): `mb 1 3 0 64` then `mb 1 4 0 64`, photograph the LCD pages at the same moment, and fill `docs/meter/fcn300-3e4y-verified.md`. Corrections go in `/config/registers.csv` on the card (start from the output of `regs`): **no reflashing needed**.

### T5. Records on the SD card
1. Wait 3 minutes. `ls /data/2026/11` (this month), `tail /data/2026/11/2026-11-07.csv 3`.
2. One row per minute, timestamps on the minute, `TH1_n` = 4.
3. `header` shows the columns.

### T6. WiFi and upload
1. `status`: `WiFi: up, <ssid> <ip> rssi -55 dBm`, `Uploads: ok n`.
2. On the VPS (or the laptop server): the day file `sites/adab/LOG-0001/raw/YYYY/MM/YYYY-MM-DD.csv` grows every minute.
3. Browser: `https://arkan-monitoring.duckdns.org/live/adab/`: tiles refresh every 15 s, "Live, updated n s ago".

### T7. Lost connection (the important one)
1. Switch the office WiFi off (or `set wifi_ssid wrong` + `reboot`) for **at least 1 hour**.
2. During the outage: `status` shows `Backlog: n min` growing; rows keep being added on the card; the live page shows "No data".
3. Switch WiFi back on. Within a few minutes: `Backlog: 0 min`.
4. On the VPS: the day file has **every minute of the outage, each once** (`manage.py list`, then count the rows of the hour: 60).
5. Also try a long outage overnight (12 h+): the logger reboots after 6 h offline (`boot=sw:offline` in the data), and still sends everything once back.

### T8. Power cuts
1. Pull the power for 5 minutes, then plug it back.
2. Expected: the data has a 5-minute gap, the first record after it has `boot=poweron`, `events.jsonl` on the VPS has a `boot` line. No broken line in the day file.
3. Pull the power **10 times quickly** (every 20 s): the logger must not end in a boot loop; after 10 min stable, `status` shows no "SAFE MODE".

### T9. SD card removed
1. Pull the SD card while running. `status`: `SD: FAILED`, `RAM queue n rows`; uploads go on from RAM.
2. Put it back: within a minute, "SD card back", the RAM rows are written to the card.

### T10. Server down / wrong token
1. On the VPS: `docker compose stop ingest` for 10 minutes, then `start`: same result as T7, no loss.
2. `set dev_token wrong`, `reboot`: `status` shows the token refused; data stays on the card. Put the right token back: everything arrives.

### T11. Setup portal and button
1. Hold **BOOT** 3 s: WiFi `ARKAN-LOG-0001` appears. Change `live_on` to 0 from the phone, save: the logger restarts with it. Set it back.
2. Logging goes on while the portal is open (check the day file).

### T12. Daily reboot and watchdog
1. `set reboot_hr <current UTC hour + 1>`, `reboot`, wait: at hh:05 a reboot with `boot=sw:daily`. Set it back to 19.
2. Optional (OTA test, needs `ota_on=1`): build version 0.1.1, `manage.py publish-fw`, `ota` on the console: the logger updates and reports the new version. Then publish a broken build: it must come back to the previous version by itself.

### T13. 48-hour soak (plan exit criterion P2)
Leave it running 48 h with the office WiFi switched off for 1 hour in the middle. Then on the VPS:
```bash
docker compose exec ingest python tools/manage.py daily adab
```
`coverage_pct` should be 100 (except the first and last day), no duplicates, `heap_kb` stable (a falling heap means a leak: report it).

## 4. Before leaving for the site
- [ ] Verified pins in the settings (and reported, so they become firmware defaults)
- [ ] `wifi_ssid` / `wifi_pass` of the **hotel staff network** set (console or portal); the office network as `wifi_ssid2` is useless on site: clear it, or set the 4G router if there is one
- [ ] `portal_pass` changed from the default
- [ ] `tls_verify` = 1, `srv_url` = `https://arkan-monitoring.duckdns.org`
- [ ] Simulated or office test data removed from the VPS (`VPS-SETUP.md` step 8)
- [ ] SD card: `/data` emptied on a laptop (the office rows would be resent, harmless but confusing), `/state/upload.txt` deleted
- [ ] RTC set (UTC), coin cell in place
- [ ] Labels: logger code on the box, WiFi `ARKAN-LOG-0001`
- [ ] USB-RS485 adapter + laptop with this repository, for the register check on site

## 5. Bench record sheet

| Test | Result | By / date (UTC) |
|---|---|---|
| T1 clock, survives power-off | | |
| T2 I2C addresses found | | |
| T2 SD CS pin verified | | |
| T2 RS485 TX / RX / DE verified | | |
| T3 TH1 chip, TH2 reading, fault shown | | |
| T4 meter / simulator / loopback | | |
| T5 one row per minute on the card | | |
| T6 day file on the VPS, live page | | |
| T7 1 h outage: rows received, each once | | |
| T7 12 h outage: `sw:offline` reboot, all rows | | |
| T8 power cut gap and `boot=poweron` | | |
| T8 10 quick power cuts: no safe mode left | | |
| T9 SD removed and back | | |
| T10 server down / wrong token | | |
| T11 portal and button | | |
| T12 daily reboot | | |
| T13 48 h soak: coverage, heap | | |

## 6. On site (summary, details in install manual Labs 5 to 7)
1. RSSI survey at the box position (better than -70 dBm).
2. Power the logger: it joins the staff WiFi. If the WiFi was not set: BOOT 3 s, portal from the phone.
3. Meter: Modbus address and baud read on the meter's menu = `meters` and `mb_baud`. `status` shows `EM01_...` values: compare with the LCD (within 1 %).
4. Sensor offsets from the reference instruments: `th1_off_t`, `th2_off_t`, ... then `reboot`.
5. Live page on the phone: values updating. The day file on the VPS growing.
