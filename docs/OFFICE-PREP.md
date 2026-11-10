# Office preparation: build, flash, configure and test the logger before the site

Everything here is done **at the office, on the bench**, before the logger goes to the Adab hotel. The order: VPS first (so the logger has somewhere to send), then the board, then the tests, then packing.

Reference: functions and settings [`FIRMWARE.md`](FIRMWARE.md), data format [`DATA-FORMAT.md`](DATA-FORMAT.md), VPS [`VPS-SETUP.md`](VPS-SETUP.md), questions still open [`QUESTIONS.md`](QUESTIONS.md). Hardware theory, wiring drawings and site labs: [`install/README.md`](install/README.md).

> **Status (9 November 2026).** Firmware 0.4.1 (power quality min/max, sensors every 5 min, firmware version logged, remote settings, OTA on with the build marker, register table sent from the platform) and the ingest service with the alarm log are written; CI compiles the firmware and runs the server tests. The bench board `LOG-0001` has run firmware 0.3.0 since 8 November (online, uploading; AM2301 on **GPIO 1** confirmed); 0.4.1 is still to test on it (T1 below, by cable). Do not use 0.4.0: it restarts every minute ([`UPDATING.md`](UPDATING.md) section 5). The rest of the pin map is still **to verify** (T2 below); the meter register map is verified **on site** (T4 below, `docs/meter/README.md`). Expect small fixes during the first bench day.

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

**C. SD card file** (preparing several loggers): on the VPS, `manage.py add-device adab LOG-0001 --sd-settings /data/export/settings-LOG-0001.txt` writes the file into the data folder (`/srv/arkan-monitoring/data/export/` on the host; the container is read-only elsewhere); copy it to the laptop and delete it from the VPS; add the WiFi lines; copy it to the card as `/config/settings.txt`; power the logger: it applies it, deletes the file, restarts.

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
3. Pull the AM2301 data wire: `TH2=fault` on the console; the next 5-minute rows have `err` in `TH2_t`, `TH2_rh`. Within 15 min the alarm log on the VPS shows **A14 start**; plug it back: **A14 clear** at the next 5-minute row.
4. Next to a reference thermometer/hygrometer for 30 min: note the differences. They become `th1_off_t`, `th2_off_t` etc. on the install day (the office is not the site).

### T4. RS485 wiring and the meter-off test (the register check moves to the site)
The spare FCN300 at the office has **no Modbus port** (owner, 8 November 2026), so the meter's registers **cannot be read on the bench**. The register check, the CT-direction check (A30) and the power quality check are done **on site** at the first visit: `docs/meter/README.md` section 4, with the proposed table `docs/meter/registers-proposed.csv`. The bench still tests the wiring and the "meter not answering" path:
1. RS485 wiring: A to A, B to B, shielded twisted pair, 120 ohm termination jumper on at the logger end. The pins (TX, RX, DE) are verified in T2.
2. With no meter answering, `mb 1 3 0 64` on the console prints a timeout with the hint "wiring, A/B, id, baud".
3. **Meter not answering:** `status` shows `Meter EM01 (id 1): NO ANSWER for n reads` (firmware 0.5.0; `EM01: no answer` on the `Last sample` line), the site page's open alarms card shows `Meter EM01 · Modbus not connected` in red within 15 s, the record has `EM01_n` = 0 and empty meter values, and after a minute the alarm log has **A03 Meter not answering**.
4. Put the proposed table on the card as `/config/registers.csv`, boot, and read the boot log: `Meter: register table from SD /config/registers.csv (19 values)`. This proves the file is read; it does not verify any value.
5. **Rehearse with the simulator** ([tutorial 4](tutorials/4-MODBUS-REGISTERS.md), Parts 3 and 4): the laptop plays a meter on the RS485 pair (`tools/modbus_sim/`, three different layouts). Expected: the logger reads the proposed table (2 requests, `EM01_n` = 4), the currents and powers are right once `ct_mult` = 50, and a layout that does not match gives no values and A03. This proves the wiring, the direction control, the SD file, the decoding and the path to the VPS. It proves nothing about the real meter. Remove the simulated data from the VPS before the site.
6. **Try the register page once** (firmware 0.4.0 or later, logger online): on `/live/adab/register` (link "Meter registers" on the site's live page) send the proposed table, wait for **Applied** (the logger restarts, `boot=sw:remote_regs`), then **Back to the built-in table**. `meters`, `mb_baud`, `mb_format` and `ct_mult` can be sent from the same page. See `docs/meter/README.md`, "Changing the register table".

### T5. Records on the SD card
1. Wait 6 minutes (the sensor values appear on the rows at :00, :05, ... only). `ls /data/2026/11` (this month), `tail /data/2026/11/2026-11-07.csv 3`.
2. One row per minute, timestamps on the minute, `EM01_n` = 0 (no meter answers at the office; 4 = all reads good, on site), `TH1_t` filled every 5th row. The first row after the boot has `boot` = `poweron@0.4.0`.
3. `header` shows the columns.

### T6. WiFi and upload
1. `status`: `WiFi: up, <ssid> <ip> rssi -55 dBm`, `Uploads: ok n`.
2. On the VPS (or the laptop server): the day file `sites/adab/LOG-0001/raw/YYYY/MM/YYYY-MM-DD.csv` grows every minute.
3. Browser: `https://arkan-monitoring.duckdns.org/live/adab/`: the cards refresh every 15 s, "Live · updated n s ago".

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
2. Put it back: within a minute, "SD card back"; the RAM rows not yet uploaded are written to the card (rows already uploaded from RAM are on the VPS only). Always switch the power off before removing the card in normal use: there is no eject command.

### T10. Server down / wrong token
1. On the VPS: `docker compose stop ingest` for 10 minutes, then `start`: same result as T7, no loss.
2. `set dev_token wrong`, `reboot`: `status` shows the token refused; data stays on the card. Put the right token back: everything arrives.

### T11. Setup portal and button
1. Hold **BOOT** 3 s: WiFi `ARKAN-LOG-0001` appears. Change `live_on` to 0 from the phone, save: the logger restarts with it. Set it back.
2. Logging goes on while the portal is open (check the day file).

### T12. Daily reboot and watchdog
1. `set reboot_hr <current UTC hour + 1>`, `reboot`, wait: at hh:05 a reboot with `boot=sw:daily`. Set it back to 19.
2. **OTA** (on by default): change `FW_VERSION` to the test number **0.4.90** (test numbers are never used for a release: the VPS keeps every file it offered, and a version number must never get other content), build, send it from **Firmware update** in the site page's menu ([`OTA.md`](OTA.md); your login must be in `ADMIN_USERS`) or with `manage.py publish-fw /data/firmware.bin`; an online logger takes it within a minute (or `ota` on the console): the logger updates, `manage.py list` shows 0.4.90, and the alarm log has **A35 Firmware updated** "0.4.0 -> 0.4.90, by remote update (OTA)". Then send a build that crashes at boot (test only, version 0.4.91): it must come back to the previous version by itself (`boot=sw:ota_rollback@0.4.90`, **A36** in the alarm log). Afterwards, flash the released firmware back by cable (A4): the logger would otherwise refuse every 0.4.x release as "not newer".

### T12b. Remote settings
1. After a boot, `manage.py show-config LOG-0001` shows what the logger reported (firmware, settings, TH1 chip).
2. `manage.py set-config LOG-0001 th1_off_t=-0.5`, then `config` on the console (or wait 15 min): the logger logs the change and restarts; `show` has the new value; `show-config` reports the new version.
3. `manage.py set-config LOG-0001 wifi_ssid=x` is refused (network settings only on site).
4. Put it back: `manage.py set-config LOG-0001 th1_off_t=@default`.

### T12c. Alarm log
1. On the VPS: `manage.py alarms adab` lists the open alarms and the last log lines; `/live/adab/` shows them too.
2. Check that T3, T4, T7, T8, T9 left their lines: A14, A03, A01 (start and clear), A02 with the outage length, A15.
3. Before the site: `manage.py alarms adab --rebuild` after deleting the office data, so the site starts with an empty log.

### T13. 48-hour soak (plan exit criterion P2)
Leave it running 48 h with the office WiFi switched off for 1 hour in the middle. Then on the VPS:
```bash
docker compose exec ingest python tools/manage.py daily adab
```
`coverage_pct` should be 100 (except the first and last day), no duplicates, `heap_kb` stable (a falling heap means a leak: report it).

## 4. Before leaving for the site
- [ ] Verified pins in the settings (and reported, so they become firmware defaults)
- [ ] `wifi_ssid` / `wifi_pass` of the **hotel staff network** set (console or portal); the office network as `wifi_ssid2` is useless on site: clear it, or set the 4G router if there is one
- [ ] `portal_pass` = the logger's own setup WiFi password from `manage.py add-device` (in the password manager)
- [ ] **A small hole in the box lid over the BOOT button**, labelled "Setup: hold 3 s" (reachable with the box closed, owner 7 November 2026)
- [ ] Site profile on the VPS: 82.5 kVA, 200 A, 230 V in `site.json` (`add-site ... --contracted-kva 82.5 --rated-a 200`), so A08, A29 and A37 work
- [ ] Register table on the card: `docs/meter/registers-proposed.csv` as `/config/registers.csv` (**proposal, not verified**: edited and confirmed on site, `docs/meter/README.md` section 4)
- [ ] Laptop with `docs/install/labs/modbus_dump.py`, the USB-RS485 adapter and a clamp meter, for the on-site register and CT check
- [ ] `tls_verify` = 1, `srv_url` = `https://arkan-monitoring.duckdns.org`
- [ ] Simulated or office test data removed from the VPS (`VPS-SETUP.md` step 8)
- [ ] SD card: `/data` emptied on a laptop (the office rows would be resent, harmless but confusing), `/state/upload.txt` deleted
- [ ] RTC set (UTC), coin cell in place
- [ ] Labels: logger code on the box, WiFi `ARKAN-LOG-0001`
- [ ] USB-RS485 adapter + laptop with this repository, for debugging on site

## 5. Bench record sheet

| Test | Result | By / date (UTC) |
|---|---|---|
| T1 clock, survives power-off | | |
| T2 I2C addresses found | | |
| T2 SD CS pin verified | | |
| T2 RS485 TX / RX / DE verified | | |
| T3 TH1 chip, TH2 reading, fault shown | | |
| T4 meter not answering: A03 logged | | |
| T4 `registers.csv` read at boot | | |
| T4 simulator: logger reads 2 requests, values right with `ct_mult` 50 | | |
| T4 simulator stopped: A03 logged | | |
| On site: registers verified, within 1 % of the LCD | | |
| On site: CT reversed: A30 logged | | |
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
| T12 OTA update and rollback (A35, A36 logged) | | |
| T12b remote settings | | |
| T12c alarm log lines present | | |
| T13 48 h soak: coverage, heap | | |

## 6. On site (summary, details in install manual Labs 5 to 7)
1. RSSI survey at the box position (better than -70 dBm).
2. Power the logger: it joins the staff WiFi. If the WiFi was not set: BOOT 3 s, portal from the phone.
3. Meter: Modbus address and baud read on the meter's menu = `meters` and `mb_baud`. `status` shows `EM01_...` values: compare with the LCD (within 1 %).
4. Sensor offsets from the reference instruments: `th1_off_t`, `th2_off_t`, ... then `reboot`.
5. Live page on the phone: values updating. The day file on the VPS growing.
