# Logger firmware: functions and settings

Firmware **0.4.1** (CSV schema 3; 0.4.0 added the remote register table (2.9.2) and the OTA build marker (2.8); 0.4.1 fixes the watchdog restart on empty server replies, see [`UPDATING.md`](UPDATING.md) section 5, and moves the AM2301 default to GPIO 1), folder [`firmware/`](../firmware/). PlatformIO, Arduino framework, ESP32-S3.
Status: **written, compiled by CI, not yet run on the board.** The pin map and the meter register map are still **to verify** (Lab 1 and Lab 3 of the install manual).

How to build, flash, configure and test it: [`OFFICE-PREP.md`](OFFICE-PREP.md). The file format: [`DATA-FORMAT.md`](DATA-FORMAT.md).

---

## 1. What runs on the board

| Task | Core | Does | Under the watchdog |
|---|---|---|---|
| **sampler** | 1 | Every `sample_s` (15 s, on the clock: :00, :15, :30, :45) reads the meters (Modbus RTU), TH1 and TH2; makes the live snapshot; at each new minute writes the **1-minute record** to the SD card | yes |
| **net** | 0 | WiFi (main + backup network), NTP, **uploads the SD backlog** to the server, posts the live snapshot, OTA check | yes |
| **loop** | 1 | Serial console, setup portal, setup button, status LED, daily reboot, memory check, boot-loop guard | yes |

A task stuck for 60 s reboots the board (task watchdog with panic). Records are written to the SD card **before** any network activity, so a network problem never costs data.

## 2. Functions

### 2.1 Measurement
| Function | Detail |
|---|---|
| Meter reading | Modbus RTU master, any number of meters up to 4 (`meters` = `EM01:1,EM02:2`). Registers that touch each other are read in one request (2 for the FCN300: a meter may refuse a request that spans registers it does not have). One retry per request |
| Register table | Built in from `docs/meter/fcn300-3e4y-modbus-guide.md` (**not verified**). Replaced **without reflashing** by `/config/registers.csv` on the SD card, written by hand or sent from the platform's page `/live/<site>/register` (2.9.2): `name,fc,addr,type,scale,ct,agg` per line. Types: `u16 s16 u32 s32 u32sw s32sw f32 f32sw` (`sw` = low word first). `ct=1`: multiplied by `ct_mult`. `agg`: `mean`, `last` (counters), `minmax` (mean + `_min` + `_max` columns). Decimals written follow the scale (0.001 gives 3; floats at least 3). Practice and tests: [`tutorials/4-MODBUS-REGISTERS.md`](tutorials/4-MODBUS-REGISTERS.md), `tools/modbus_sim/` |
| TH1 (board sensor) | I2C, type found at boot: AHT1x/AHT2x (0x38), SHT3x (0x44/0x45), HTU21/SHT21/Si7021 (0x40). CRC checked where the chip has one |
| TH2 (AM2301) | DHT21 protocol on `pin_dht`. One retry after 2.1 s on a bad read |
| Calibration | Offset per sensor (`th1_off_t`, `th1_off_rh`, `th2_off_t`, `th2_off_rh`), set after the install-day comparison with a reference |
| Plausibility | Readings outside -40..85 C or 0..100 %RH are dropped (counted as a fault) |

### 2.2 The 1-minute record
- **Meter values (power quality): mean, min and max** of the 15 s samples for V L-N, V L-L, A, Hz, kW per phase and total, kvar, kVA, PF: `EM01_v1`, `EM01_v1_min`, `EM01_v1_max`... (owner, 7 November 2026). A dip or a demand peak is not hidden by the mean.
- **Sensors: a 5-minute average only** (`TH1_t`, `TH1_rh`, `TH2_t`, `TH2_rh`; owner, 7 November 2026; setting `th_avg_min`). Written on the rows at :00, :05, :10... as the mean of the 5 minutes **before** that time; empty on the other rows; `err` if the window had no valid reading (sensor fault). The sensors are still read every 15 s for the live page.
- **Last** value of the energy counters (`EM01_e` kWh, `EM01_eq` kvarh): consumption is computed on the server from the counter, so a gap never corrupts totals.
- **Meter sample count** (`EM01_n`, 0 to 4): a fault is an empty value plus a low count, never a fake zero.
- **Health**: `rssi`, `heap_kb`, `up_s`, `backlog_min`, `sd` (0 = the SD card was failing, the row came from the RAM queue), and `boot` (on the first record after a boot only: the reset reason and the firmware version, `reason@version`, for example `poweron@0.4.0`, `sw:ota@0.4.1`, `sw:ota_rollback@0.4.0`, `brownout`, `task_wdt`, `panic`, `sw:daily`, `sw:offline`...). The VPS logs firmware changes from it (A35, A36).
- **No record without a valid clock.** A timestamp the logger cannot trust is worse than a gap. With the DS3231 and its coin cell this only happens if the cell is dead and there is no internet.

### 2.2.1 Alarms and warnings
The logger does not decide alarms: the VPS checks every record against the alarm register (`docs/alarms/`) and keeps the alarm log, including for the backlog after an outage, at the times found in the records. Thresholds are then changed in Excel on the VPS without touching the logger, and the whole log can be rebuilt from the SD card's records. The logger's own health problems reach the log through the record columns (`EM01_n`, `err` sensor values, `sd`, `backlog_min`, `rssi`, `boot` with the firmware version); details stay in its event log `/log/YYYY-MM.log`.

### 2.3 Local storage (SD card)
One CSV file per UTC day, same columns as the server's files. **The day files are the upload queue**: an upload pointer (`/state/upload.txt`: day, part, byte offset) says how far the server has confirmed. Nothing is written twice. Details and the reasons in [`DATA-FORMAT.md`](DATA-FORMAT.md).
- Append, then close, every minute: a power cut loses at most the minute being written. A half-written last line is closed at the next boot and refused by the server.
- If the columns change during a day (new meter, sensor switched off), a new file `YYYY-MM-DD_2.csv` starts: never two layouts in one file.
- **SD card failure:** records go to a RAM queue (180 rows = 3 h) and are uploaded from there; the card is re-mounted every minute; when it is back, the RAM rows **not yet uploaded** are written to it (rows uploaded from RAM while the card was out are on the VPS only, so the card copy has a gap there). There is no eject command: switch the power off before removing the card.
- **Card nearly full** (below `sd_min_free` %): the oldest day files **already uploaded** are deleted. Unsent data is never deleted. A 16 GB card holds over 50 years at about 260 MB a year, so this is a safety net only.
- **Event log** `/log/YYYY-MM.log`: boots and their reason, WiFi up/down, NTP corrections, settings changed, upload errors, SD errors, OTA.

### 2.4 Lost connections
| Situation | What the logger does |
|---|---|
| WiFi drops | Records go on to the SD card. Reconnects with back-off: 10, 20, 40, 80, 160 s, then every 5 min |
| Backup network | If `wifi_ssid2` is set (for example a 4G router), attempts alternate between the two networks |
| Offline 30 min | Restarts the WiFi driver (fixes most stuck radios), then every 30 min |
| Offline `offline_rbt_h` hours (6) | Full reboot. Harmless: the data is on the SD card |
| Link back | Uploads at once, then **catch-up**: up to 20 batches of 60 records back to back per minute (1,200 records a minute, so a 3-day outage is cleared in about 4 minutes) |
| Server down or 5xx | Retries every `upload_s`; every 5th failure opens a new TLS connection |
| Server refuses a batch (400) 3 times | Skips it (logged with its time range); the rows stay on the SD card for `manage.py backfill` |
| Token refused (401/403) | Logged; retries every 10 min. Data stays on the card |
| Live snapshot fails | Dropped (the next one comes 15 s later); after 3 failures live pauses 2 min so it does not hold up uploads |
| Duplicates | The server drops rows it already has (same timestamp): resending is always safe |

### 2.5 Auto restart and self-protection
| Guard | Trigger | Action |
|---|---|---|
| Task watchdog | Any task stuck 60 s | Reboot (`task_wdt`) |
| Daily reboot | `reboot_hr`:05:02 UTC (default 19 = 03:05 WITA), after 1 h of uptime | Clean reboot, just after a record is written; at most one record has 2 samples instead of 4 |
| Offline reboot | `offline_rbt_h` hours without WiFi | Reboot (`sw:offline`) |
| Memory | Free heap below `min_heap_kb` three minutes in a row | Reboot (`sw:lowheap`) |
| Brown-out | Supply drops | Hardware reset (`brownout`), logged |
| Boot loop | 5 boots in a row that do not reach 10 min of uptime | Safe mode: no OTA until stable |
| Bad OTA firmware | The new firmware reboots 3 times before 10 min of uptime | Goes back to the previous firmware (`sw:ota_rollback`) |
| Clean restarts | Every software restart | Waits for any SD write in progress, records the reason |
| Power cut | No UPS for the trial | RTC keeps the time; logging restarts with correct timestamps; the gap shows in the data and as `boot=poweron` |

### 2.6 Time
- System clock in **UTC only**. Set from the DS3231 at boot; NTP (`ntp1`, `ntp2`) once online, re-synced every hour; the RTC is corrected when it drifts by 2 s or more (and every 6 h).
- WITA (UTC+8) is applied by the server and the dashboards, never by the logger.

### 2.7 Upload and live
- `POST {srv_url}/api/v1/ingest`, `Content-Type: text/csv`, `Authorization: Bearer <dev_token>`: the day file's header line + up to 60 rows. Answer 200 with `stored`, `duplicates`, `rejected_rows`.
- `POST {srv_url}/api/v1/live`: JSON snapshot after every sample (15 s), not stored on the card, about 2 MB a day. Since 0.5.0 it carries `sys.mb`, the Modbus link of each meter (answering or not, since when, last answer, last error), shown at the top of the open alarms on the site page: [`LIVE.md`](LIVE.md#meter-link-modbus-connection-state).
- HTTPS with certificate check (Let's Encrypt and ZeroSSL roots built in). `tls_verify=0` only on the bench. `http://` URLs work for an office test against a laptop.
- Connection kept open between requests (keep-alive).

### 2.8 OTA (on by default since 0.2.0)
With `ota_on=1` (default), every `ota_check_h` hours the logger asks `GET /api/v1/ota?fw=<version>`. If the server offers another version (**Firmware update** in the site page's menu, or `manage.py publish-fw`), it downloads it, checks the MD5, writes it to the other flash slot and restarts. Rollback as in 2.5.
- **Check now:** when a firmware waits for it, the server answers the live snapshot with `{"ota":1}` and the logger checks at once (at most once per 5 min), so an online logger updates within about a minute.
- **Build marker:** every build carries `ARKAN-LOGGER-FW;ver=<FW_VERSION>;env=<usb|uart>;` (`FW_TAG`, `config.h`; the variant comes from the env in `platformio.ini`). The server refuses a file without it, for another chip or for the other variant. The boot report sends `env` too.
- **A version that rolled back** is remembered (counter `ota_bad`) and never installed again by itself; the console command `ota` tries it again on purpose.
- Releases, the panel and its checks: [`OTA.md`](OTA.md).

### 2.9 Setup without a laptop: the portal
- Opens when **no WiFi is set**, when the **BOOT button is held 3 s**, or with the console command `portal`.
- WiFi name **`ARKAN-<dev_id>`** (for example `ARKAN-LOG-0001`), password **`portal_pass`** (default `arkan-setup`: change it).
- Page **http://192.168.4.1** (a phone usually opens it by itself): status (with one line per meter: answering or not, since when, last answer; since 0.5.0), WiFi networks seen with their RSSI, and every setting. Secrets are never displayed; an empty secret field keeps the stored value. "Save and restart".
- Logging goes on while the portal is open. It closes after `portal_min` minutes without activity.

### 2.9.1 Remote settings (on by default since 0.2.0)
- After each boot the logger **reports** its firmware, settings (secrets only as "(set)"), CSV columns and TH1 chip to the platform (`POST /api/v1/config/report`). `manage.py show-config LOG-0001` shows them.
- Every `rcfg_check_m` minutes (15) it asks `GET /api/v1/config`. When `manage.py set-config LOG-0001 th1_off_t=-1.2 ...` has made a newer version, it applies the keys, logs each change, and restarts if anything changed. `key=@default` puts a default back.
- **Never changed remotely** (a wrong value would cut the logger off for good): `dev_id`, `dev_token`, `srv_url`, `tls_verify`, the four WiFi keys, `portal_pass`. These need the setup portal or the console, on site.
- The version applied is kept, so a setting is applied once even if the logger asks again.

### 2.9.2 Remote register table (since 0.4.0)
- The meter register table can be sent from the platform's page **`/live/<site>/register`** (link "Meter registers" on the site's live page; `?device=LOG-0002` if the site has several loggers) (or `manage.py set-registers LOG-0001 table.csv`). The page shows the table the logger reports, lets you edit it line by line, import a CSV file, check it, and send it. `docs/meter/README.md`, "Changing the register table", explains the steps.
- At the same check as the remote settings (every `rcfg_check_m` minutes, or the console command `config`), the logger asks `GET /api/v1/registers`. When the version is newer than the one it applied (counter `reg_ver`), it checks the whole table (every line valid, names `a-z0-9` of 1 to 7 characters and unique, at most 32 values). It then writes `/config/registers.csv` through `/config/registers.new`, keeps the previous file as `/config/registers.bak`, and restarts (`boot=sw:remote_regs`).
- "Back to the built-in table" renames `/config/registers.csv` to `registers.bak`, so the firmware's table is used.
- A table that fails the checks, or a logger with no working SD card, **refuses** the version: the reason goes to the event log and to the platform (`reg_refused`, `reg_error`), and the page shows "Refused". It is not tried again until the next boot. Send a corrected table (a new version).
- After each boot the report also carries `reg_version`, `reg_source` (`sd` or `builtin`) and the table in use (`registers`, as printed by `regs`). The page compares that with what was sent: "Applied", "Waiting", "Differs" (the card was changed by hand or swapped) or "Refused".
- `rcfg_on=0` also turns this off. Firmware before 0.4.0 does not ask for the table (the page says "Firmware too old").

### 2.10 Serial console (USB, 115200 baud)
`help`, `status`, `show`, `set <key> <value>`, `unset <key>`, `reboot`, `factory`, `portal`, `time`, `time set 2026-11-07T03:15:00`, `i2c`, `wifi`, `mb [slave] [fc] [start] [count]`, `regs`, `header`, `ls [dir]`, `cat <file>`, `tail <file> [n]`, `upload`, `resend <YYYY-MM-DD>`, `ota`, `config`.

### 2.11 Office preparation from the SD card
A file `/config/settings.txt` with `key=value` lines is applied at boot, **then deleted from the card** (it holds the token and the WiFi password), then the logger restarts. `manage.py add-device ... --sd-settings settings.txt` writes one with the device code, token and server URL.

---

## 3. All settings

Stored in NVS (survive power cuts and reflashing; erased only by `factory`). Change with the console (`set`), the portal, `/config/settings.txt`, or from the VPS (`manage.py set-config`, applied and rebooted by itself), then **reboot**.

| Group | Key | Default | Meaning |
|---|---|---|---|
| Identity | `dev_id` | `LOG-0001` | Logger code, as registered on the platform Not changeable remotely. |
| WiFi | `wifi_ssid` | (empty) | Main WiFi network (2.4 GHz) Not changeable remotely. |
|  | `wifi_pass` | (empty) | Main WiFi password **Secret**: never shown. Not changeable remotely. |
|  | `wifi_ssid2` | (empty) | Backup WiFi network (for example a 4G router), empty = none Not changeable remotely. |
|  | `wifi_pass2` | (empty) | Backup WiFi password **Secret**: never shown. Not changeable remotely. |
| Server | `srv_url` | `https://arkan-monitoring.duckdns.org` | Platform base URL (http://IP:8800 for an office test) Not changeable remotely. |
|  | `dev_token` | (empty) | Device token given by tools/manage.py add-device **Secret**: never shown. Not changeable remotely. |
|  | `tls_verify` | `1` | 1 = check the server certificate, 0 = do not (bench only) Not changeable remotely. |
|  | `upload_s` | `60` | Seconds between upload attempts |
|  | `batch_rows` | `60` | Records per upload request |
|  | `live_on` | `1` | 1 = send a live snapshot after every sample |
|  | `ota_on` | `1` | 1 = check the platform for firmware updates |
|  | `ota_check_h` | `6` | Hours between firmware update checks |
|  | `rcfg_on` | `1` | 1 = take settings from the platform (manage.py set-config) |
|  | `rcfg_check_m` | `15` | Minutes between remote settings checks |
| Sampling | `sample_s` | `15` | Seconds between samples (meter and sensors), divides 60 |
| Meter | `meters` | `EM01:1` | Meters on RS485 as id:slave, comma separated (EM01:1,EM02:2) |
|  | `mb_baud` | `9600` | RS485 baud rate |
|  | `mb_format` | `8N1` | RS485 frame: 8N1, 8E1, 8O1 or 8N2 |
|  | `ct_mult` | `1` | Multiplier for currents and powers if the meter gives secondary values (CT ratio), else 1 |
| Sensors | `th_avg_min` | `5` | Minutes averaged per temperature/humidity record (1, 5, 10, 15, 30 or 60) |
|  | `th1_type` | `auto` | TH1 on-board I2C sensor: auto, aht, sht3x, htu21, none |
|  | `th1_off_t` | `0` | TH1 temperature offset (C), from the install-day calibration |
|  | `th1_off_rh` | `0` | TH1 humidity offset (%RH) |
|  | `th2_on` | `1` | 1 = AM2301 (TH2) connected |
|  | `th2_off_t` | `0` | TH2 temperature offset (C) |
|  | `th2_off_rh` | `0` | TH2 humidity offset (%RH) |
| Pins | `pin_sda` | `8` | I2C SDA |
|  | `pin_scl` | `9` | I2C SCL |
|  | `pin_sd_sck` | `12` | SD card SCK |
|  | `pin_sd_miso` | `13` | SD card MISO |
|  | `pin_sd_mosi` | `11` | SD card MOSI |
|  | `pin_sd_cs` | `10` | SD card CS (10 or 21) |
|  | `pin_rs_tx` | `-1` | RS485 TX (to verify, -1 = not set) |
|  | `pin_rs_rx` | `-1` | RS485 RX (to verify, -1 = not set) |
|  | `pin_rs_de` | `-1` | RS485 DE/RE, -1 if the board switches by itself |
|  | `pin_dht` | `1` | AM2301 data |
|  | `pin_led` | `-1` | Status LED, -1 = none |
|  | `pin_btn` | `0` | Setup button (BOOT = 0): hold 3 s to open the setup portal |
| Robustness | `reboot_hr` | `19` | Daily reboot at this UTC hour, minute 05 (19 = 03:05 WITA), -1 = never |
|  | `offline_rbt_h` | `6` | Reboot after this many hours without WiFi, 0 = never |
|  | `min_heap_kb` | `30` | Reboot if free memory stays below this (kB) |
|  | `sd_min_free` | `5` | Below this % free on the SD card, delete the oldest uploaded day files |
| Portal | `portal_pass` | `arkan-setup` | Password of the setup WiFi (8 characters at least) **Secret**: never shown. Not changeable remotely. |
|  | `portal_min` | `15` | Minutes the setup portal stays open without activity |
| Time | `ntp1` | `pool.ntp.org` | First NTP server |
|  | `ntp2` | `time.google.com` | Second NTP server |

---

## 4. Files of the firmware

| File | Role |
|---|---|
| `platformio.ini` | Board, libraries, two builds: `logger` (native USB) and `logger-uart` (USB-UART chip) |
| `include/config.h` | Version, limits, SD paths |
| `include/certs.h` | Root certificates (`tools/make_certs.sh`) |
| `src/main.cpp` | Boot, reset reason, boot-loop guard, OTA rollback, loop checks |
| `src/settings.*` | The settings table and NVS |
| `src/app.*` | Shared status, event log, clean restart, UTC helpers |
| `src/rtclock.*` | DS3231 and NTP |
| `src/sensors.*` | TH1 (I2C, auto-detect), TH2 (AM2301) |
| `src/meter.*` | Modbus master and register table |
| `src/sampler.*` | 15 s samples, 1-minute record, live snapshot |
| `src/storage.*` | SD day files, upload pointer, RAM queue, free space |
| `src/net.*` | WiFi, uploads, live, remote settings, OTA |
| `src/portal.*` | Setup WiFi and page |
| `src/console.*` | Serial commands |

Libraries: ModbusMaster, Adafruit DHT sensor library, ArduinoJson. The RTC and the I2C sensors are driven directly (no library).
