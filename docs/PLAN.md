# Adab Hotel Energy Logger: Installation Plan

Status: **DRAFT v0.14, 8 November 2026.** Review answers of 30 October are in §3; the choice of base repository is in §4 and the full search of what can be reused is in **`docs/REUSE.md`**.
v0.14 (8 November, the day's work merged): **firmware 0.4.0**: the meter register table can be sent from the platform's page `/live/<site>/register` (with `meters`, `mb_baud`, `mb_format`, `ct_mult`); **firmware update per logger from the site page** (GitHub release made by CI from a `fw-v` tag, or a `.bin`; logins in `ADMIN_USERS`, `docs/OTA.md`); **Modbus meter simulator** and tutorial 4; CT **250/5** (ratio 50); OED deploy files tested on a test machine. How the VPS and the loggers are updated: `docs/UPDATING.md`.
v0.13 (owner, 8 November): **site page design approved** from the dashboard mockup (`docs/mockup/`): `/live/<site>/` gets a side menu with Live now and **history pages** (power, one day, energy per day, this week vs last, temperature, humidity) read from the day files (`docs/LIVE.md`). OED stays for groups, export, maps and any-period comparison.
v0.12 (owner, 7 November, second round): **sensors as 5-minute averages** (logger 0.3.0); **firmware updates in the alarm log** (A35, A36); PLN 3-phase supply 230/400 V, **82.5 kVA contract** (new A37 per-phase limit 3 x 125 A), **200 A main breaker**; CT ratio set in the meter; **daily count of dips and swells**.
v0.11 (owner's answers, 7 November): **CSV upload agreed**; **min and max per minute for every meter value** (power quality), sensors averaged only; **alarm and warning log** on the VPS from the register (`docs/alarms/`, 34 alarms incl. new power quality ones); **OTA and remote settings on**; setup WiFi password per logger, BOOT reachable through the box; **spare meter at the office**: the register check moves to the bench (S4); no 4G router; UPS maybe later (A32 ready, off); the platform stays in `server/` until OED is installed. Decisions and open points: `docs/QUESTIONS.md`.
v0.10: **firmware 0.1.0 and the ingest service written** (`firmware/`, `server/`; `docs/FIRMWARE.md`, `docs/VPS-SETUP.md`, `docs/OFFICE-PREP.md`). Storage: one CSV per UTC day, the day files are the upload queue (`docs/DATA-FORMAT.md`). Upload proposed as **CSV lines instead of JSON** (§5.2, `docs/QUESTIONS.md` Q1). The ingest service sits in `server/` here until `arkan-monitoring` exists (Q12).
v0.9: the AM2301 (`TH2`) is **outdoors, beside the panel room, on 1 m of cable**, to monitor outdoor temperature and humidity; outdoor alarm limits proposed (A22 to A25), including the electrical room compared with outdoors.
v0.8: the AM2301 (`TH2`) goes **outdoors or in another room**, not in the electrical room: longer cable, outdoor protection if outside, its own alarm lines (A22, A23).
v0.7: a **second temperature and humidity sensor, AM2301**, on a cable (§2, §5); the sensors become a list (`TH1`, `TH2`) in the data, OED, the live page and the alarms (`applies_to` column, new A21).
v0.6: **live data every 15 s** on a live page beside OED (`docs/LIVE.md`); **alarm register** with a WhatsApp yes/no column (`docs/alarms/`); **RAM plan** for hermes-vps (`docs/VPS-MEMORY.md`); one register map for the 3E4Y and 3EH4Y.
v0.5: **Open Energy Dashboard (OED) is the platform's dashboard** (§4.2, §5.3); the Arkan design (CMMS, Hub) is left for a later integration. Meter variant to confirm (3E4Y or 3EH4Y). No spare meter yet. Alerts to the owner's WhatsApp group.
v0.4: site code `adab`; meter FCN300-3E4Y with its register guide (`docs/meter/`, not yet verified); WhatsApp alerts through Hermes; search of reusable repositories and dashboards (`docs/REUSE.md`).
v0.3: the platform gets **its own repository** (§4.2), and the recorded data lives in **one dedicated folder with a subfolder per site** (§5.3).
Sources: `docs/img/sketch-adab-logger.jpg` (hand sketch), `docs/img/board-top.jpg`, `docs/img/board-bottom.jpg`,
and the repositories `arkan-cmms`, `arkan-hub`, `arkan-solar-desk`, `arkan-skills-V1` (read on 30 October 2026).

---

## 1. What the sketch says (confirmed in review)

**On site (Adab hotel, main distribution panel in the back-of-house area)**
- The **Bluino ESP32-S3 TMP/RH RS485 RTC AI** board, with its built-in temperature and humidity sensor (it reads the **electrical room's air**), an SD card, a real-time clock and WiFi.
- A **second temperature and humidity sensor, AM2301** (also sold as DHT21), on a cable from the board (added 5 November 2026). It is mounted **outdoors, beside the panel room, on about 1 m of cable**, to monitor outdoor temperature and humidity (owner, 5 November 2026).
- It reads **one Fort FCN300-3E4Y power meter** over RS485 (Modbus RTU). More meters may be added later.
- **5 V** from an adapter plugged into a socket in the panel. **No UPS for the trial.**
- It goes online through the hotel's **staff WiFi network** (WPA2 password, no login page).

**On the VPS (`hermes-vps`, Hostinger, Ubuntu)**
- The ingest script and the dashboard, at **`https://arkan-monitoring.duckdns.org/`**, with the same logins as the other Arkan dashboards.
- The laptop (Claude, Codex, PowerShell) reaches both the data and the server over SSH.

**What it leads to**
1. The Monitoring page in `arkan-cmms` for this hotel. That page already exists, with simulated data.
2. The **full monitoring platform** for many sites and devices. Adab is its pilot. It is built in its own repository (`arkan-monitoring`, §4.2); this repository holds the logger.

```
 [FCN300-3E4Y] --RS485/Modbus--> [ESP32-S3 logger] --staff WiFi--> internet
                                  | T/RH (room air), RTC, SD                 |
 panel socket -> 5V adapter ------+                                          v  HTTPS POST, device token
                                     hermes-vps: native Caddy -> monitoring container (Python)
                                       |  data: /srv/arkan-monitoring/data/sites/<site>/   one folder per site
                                       |  https://arkan-monitoring.duckdns.org/          all sites (Arkan login)
                                       |  https://arkan-monitoring.duckdns.org/<site>/   one site
                                       +--> arkan-cmms Monitoring page reads the real feed (later)
                                       ^
                       laptop: ssh hermes-vps, CSV export, SD backfill, Claude / Codex / PowerShell
```

## 2. The hardware (from the photos)

| Block | What I see | Notes |
|---|---|---|
| MCU | ESP32-S3-WROOM module, **PCB antenna** | No external antenna. Mount it outside the steel panel (confirmed possible). |
| Power in | USB-C (5 V), **DC jack marked 7 to 15 V**, 5V/3V3 pins on the header | **The 5 V adapter goes to USB-C (or the 5V pin), never to the DC jack.** |
| RTC | SOIC-16 chip (likely DS3231) + CR1220 coin cell | Keeps time through power cuts. |
| Storage | microSD slot (SPI) | Header "SPI INTERFACE": GND 3V3 12 13 11 21 |
| Temp/RH 1 (`TH1`) | Blue I2C breakout module on the board (AHT/HTU/SHT family) | Reads room air plus some board self-heat; check against a reference thermometer on site. |
| Temp/RH 2 (`TH2`) | **AM2301 (DHT21)**, added by the owner, on a cable | Single-wire digital sensor, not I2C. Details below. |
| Analog in | ADS1115 (16-bit, 4 ch, I2C) | Spare for now. |
| RS485 | 8-pin transceiver, **120 ohm termination jumper**, TX/RX LEDs, screw terminals | Modbus RTU master to the meter. |
| I2C header | "I2C (OLED)" 4-pin | Optional local display. |

**Provisional pin map.** Read from the mirrored, blurry back silkscreen. **Not verified**: confirm in bench bring-up (session S4).

| Function | GPIO (provisional) |
|---|---|
| I2C SDA / SCL | 8 / 9 |
| SD SCK / MISO / MOSI / CS | 12 / 13 / 11 / 10 or 21 |
| RS485 TX / RX / DE-RE | top 3 rows of the back table, to verify |
| AM2301 data | **GPIO 1** (free on the header, not a strapping pin); confirmed on the board 8 Nov 2026 |

**The AM2301 (`TH2`)**
- **Signal:** one data wire with its own timing protocol (DHT family), not I2C or Modbus. It needs one free GPIO and a **pull-up resistor of 4.7 to 10 kohm from the data line to 3.3 V**. Many cased AM2301 have no pull-up inside; fit one at the board end.
- **Power and the ESP32's 3.3 V limit:** the ESP32-S3 pins are **not 5 V tolerant**.
  - Short cable (up to about 3 m): power the sensor from **3V3**.
  - Longer cable (up to about 20 m): power it from **5V**, but keep the pull-up to **3.3 V**, never 5 V. The sensor pulls the line low, so the ESP32 only ever sees 3.3 V.
- **Wiring:** red VCC, black GND, yellow DATA (the usual colours; check the sensor's label). Use a shielded or twisted cable, away from power cables.
- **Reading:** at most once every 2 s; the logger reads it every 15 s with the meter. One retry on a checksum error. A bad read is logged and counted (alarm A14).
- **Accuracy (maker's figures):** about plus or minus 0.5 C and 3 % RH. It has no self-heating from the board, so it is the better reference for the room air.
- **Placement: outdoors, beside the panel room, about 1 m of cable** (owner, 5 November 2026):
  - With 1 m of cable, power it from **3V3**, with a **4.7 kohm pull-up to 3.3 V** at the board end. No 5 V needed.
  - The cable goes out through a **cable gland** in the logger box and through the wall or frame of the panel room, sealed.
  - The AM2301's case is not waterproof and direct sun distorts the reading. Mount it in a **radiation shield** (louvred screen), **in permanent shade** (north or east face if possible, under the eaves), **sensor opening down**, about 1.5 m above the ground, away from AC condenser outlets, the genset exhaust and hot walls in the sun.
  - Leave a **drip loop** in the cable below the shield so water runs off before the gland.
  - Outdoors in the tropics, a reading of 99 to 100 % RH for hours after rain is normal; days at 100 % mean a wet sensor (alarm A25).
  - **Calibration:** on the install day, note both sensors against a reference thermometer and hygrometer, and set an **offset per sensor** in the logger's settings (`th1_off_t`, `th1_off_rh`, `th2_off_t`, `th2_off_rh`; console, portal or `manage.py set-config`) (`TH1` on the board reads a little warm from the board's own heat).
- **Library:** the Adafruit "DHT sensor library" (type `DHT21`/`AM2301`), or an RMT-based DHT driver on the ESP32 if timing errors show up with WiFi active.

## 3. Review answers (30 October 2026)

| # | Question | Answer | Effect on the plan |
|---|---|---|---|
| 1 | Meter model and register map | **FORT FCN300-3E4Y**, register guide received (`docs/meter/fcn300-3e4y-modbus-guide.md`). `arkan-cmms` says "FC300" | The guide is not a manufacturer document and has gaps (data types, scales, CT ratio): **verify it on the meter** (`docs/meter/README.md`). The firmware reads a configurable register table seeded from the guide |
| 2 | How many meters | **1 for now**, more later | Firmware and database take N meters per logger from the start |
| 3 | Codex | **Not crossed out**: Claude, Codex and PowerShell | Repository rules go in `AGENTS.md` too (as in `arkan-skills-V1`) |
| 15 | Client and site name | **`adab`** | Site code `adab` in both repositories: data folder `sites/adab/`, page `/adab/` |
| 16 | New repository | **OK**: Claude creates `arkan-monitoring` (private) at the start of S1 | |
| 17 | Alerts | **WhatsApp through Hermes** on hermes-vps, **to the owner's WhatsApp group** | Hermes webhook route in direct delivery mode (§5.3); the group's chat id is set in the route |
| 18 | Meter link | fortindo.id page of the **FCN300-3EH4Y** (the harmonic variant) | The guide received is for the **3E4Y**. Resellers list Modbus RS485 on both. **Read the model on the meter's label**: the 3EH4Y may have extra (harmonic) registers and a different map |
| 19 | Spare meter for the bench | **None yet** | The register check happens at the hotel (first site visit) unless one is bought (§7, S4) |
| 20 | Dashboard | **Open Energy Dashboard as the reference.** The design of `arkan-cmms` and `arkan-hub` is not used for now; integration later | OED is deployed as the platform's dashboard (§4.2, §5.3) |
| 22 | Live data | **15-second refresh for some values** | Live page `/live/<site>/` served by the ingest service, OED unchanged (`docs/LIVE.md`) |
| 23 | Meter variants | **Same registers for 3E4Y and 3EH4Y** | One register table; harmonics not read for now |
| 24 | Alarms | **A register saying which alarms go to WhatsApp** | `docs/alarms/alarms.csv`, `whatsapp` column, editable in Excel (`docs/alarms/README.md`) |
| 25 | RAM on the VPS | **Keep it low** | OED built off the VPS, slim image, tuned PostgreSQL, memory limits per container: about 300 to 450 MB in all (`docs/VPS-MEMORY.md`) |
| 21 | Temperature and humidity in OED | Asked: can OED show them? | **Yes**, as "raw" units: line graphs (3D and radar only on OED versions after v1.0.0); not bar or compare graphs (§5.3, `docs/REUSE.md` §7) |
| 4 | Domain | **`arkan-monitoring.duckdns.org`** | New DuckDNS name pointing to hermes-vps; native Caddy gets the certificate |
| 5 | Temp/RH | **Electrical room's air** | Alert on high room temperature (threshold to set) |
| 6 | WiFi | **Staff network, password, no login page** | WPA2 credentials set through the logger's setup page, kept in NVS |
| 7 | Logger outside the panel | **Yes** | Small plastic box beside the panel, RS485 cable in |
| 8 | Electrical work | **Not in this plan** | Out of scope |
| 9 | UPS | **Optional, not installed for the trial** | A power cut stops the logger: the gap shows as "logger offline". The RTC keeps the clock, so logging restarts with correct times |
| 10 | Timezone | **Makassar** (`Asia/Makassar`, WITA, UTC+8, no daylight saving) | Store UTC, show WITA; "today" runs from 00:00 WITA |
| 11 | VPS | **Hostinger, Ubuntu, the same `hermes-vps`** | Same layout as the Hub and the CMMS: native Caddy 2.6, `/opt/edge/sites/*.caddy`, Docker on loopback, user `ai` |
| 12 | Dashboard style | **Use the existing repositories** | No Grafana. Arkan UI kit, plus the CMMS Monitoring views ported (§4) |
| 13 | Timing | **OK**: meter every 15 s then 1-minute averages, T/RH every 60 s, upload every minute | |
| 14 | Access | **Same as the other dashboards** (shared login file confirmed, 30 October) | Caddy `basicauth` with the shared login file `/opt/edge/secrets/hub-users.caddy`; the signed-in name reaches the app in `X-Auth-User` |

## 4. Which existing repository to build on

### 4.1 What exists

The full search (Arkan repositories, open-source platforms and dashboards, firmware, Hermes) with a screenshot of the existing CMMS Monitoring page is in **`docs/REUSE.md`**. Summary of the Arkan repositories:

| Repository | What is useful for monitoring | What does not fit |
|---|---|---|
| **arkan-cmms** | **Monitoring views already built** on the Arkan UI kit (`cmms-demo/src/features.js`): Fort FC300 meter card (V, A, kW, kVAr, kVA, PF, Hz, kWh per phase), demand chart 00:00 to 24:00 with peak and outage shading, temp/RH charts with dew point, a 56-term glossary (EN + ID). Server weather API (MET Norway, BMKG). **VPS deploy files for hermes-vps**: Dockerfile, compose on loopback, `sites/cmms.caddy` with the shared Hub login, `update-vps.sh` | One property per instance, built by patching a demo page. The user asked for the platform to be separate from the CMMS |
| **arkan-hub** | The **deploy and access pattern**, written up and smoke-tested on hermes-vps: trusted-proxy `X-Auth-User`, `/health`, audit log, `update.sh` by tag with rollback, `backup.sh`, smoke tests, install guide | Built around the project record (`arkan_mcp` wheel) and one container per project. Not a time-series app |
| arkan-solar-desk | Same Python standard-library server pattern | Different domain (PV workflow desk), nothing for telemetry |
| arkan-skills-V1 | Engineering references (`solar-pv-energy-storage/references/calc-monitoring.md`, `senior-electrical-elv-engineer/.../calc-energy-efficiency.md`, `calc-power-quality-pfc.md`) for which KPIs to show | Skills and MCP, not an app |

No repository has an ingest endpoint, a time-series store or device code. That part is new whatever we choose.

### 4.2 Recommendation

**Two repositories** (owner's decision, 30 October 2026):

| Repository | Holds |
|---|---|
| **`esp32-datalogging`** (this one) | The logger: firmware, hardware notes, pin map, bench and install docs. A vendored copy of the data contract (`contract/`, with `VENDORED.md`) |
| **`arkan-monitoring`** (new, private) | The platform: ingest, API, pages, tools, deploy files, the tests. **Owns the data contract** (`contract/`: JSON Schema, CSV columns, example payloads) |

The contract lives in `arkan-monitoring`. The firmware repository keeps a copy, as `arkan-cmms` does with the UI kit, and its CI checks the firmware's example payloads against that copy. A contract change is made in `arkan-monitoring` first, then copied here, and both carry the contract version.

**The platform = a small ingest service of ours + Open Energy Dashboard (owner's decision, 30 October 2026).**

- **Open Energy Dashboard (OED)** is the dashboard: graphs, meters, groups of meters (site, then all sites), comparison, maps, export, its own admin pages. MPL-2.0, Node.js + PostgreSQL, run from its own Docker compose. We **deploy it as it is**, with our settings, and do not fork it.
- **`arkan-monitoring`** holds what OED does not do:
  - the **ingest endpoint** the logger posts to (OED takes readings as CSV uploads, not live posts from devices);
  - the **per-site data folders** (the record, §5.3);
  - the **push to OED** (new rows uploaded as CSV every few minutes);
  - the **alerts** through Hermes (OED has none);
  - the device registry, tokens, OTA and remote config for the loggers;
  - the deploy files: OED's compose with our settings, the Caddy site file, backups.
- **Not used for now:** the design of `arkan-cmms` and `arkan-hub`. Later, the CMMS Monitoring page can read the same per-site files or OED's data (S8+).
- **Reused from the Arkan repositories regardless of design:** the VPS conventions (loopback ports, `/opt/edge/sites/*.caddy`, the shared login file, no `sudo` by sessions, backups), as written up in `arkan-hub/deploy/` and `arkan-cmms/cmms-app/deploy/`.

**Why OED rather than the others** (`docs/REUSE.md`): it is built for many buildings and meters with groups and comparison, which is the multi-site platform of the sketch; it handles temperature as a unit; and it keeps its own database, so our per-site folders remain the plain-file record.

### 4.3 House rules taken over from the other repositories
- No em dashes or en dashes in any text.
- Interface in English and Indonesian.
- Real site names, places, paths and tokens stay out of the repository, in a **site profile on the VPS** (as in `arkan-cmms/profiles/`). See open point P1.
- Sessions do not `sudo` on hermes-vps. Caddy reloads and container restarts are live changes: the owner approves each one.
- Never overwrite an existing file on the VPS without asking. Leave the other services alone.
- One branch per work package. Nothing merges to `main` without the owner's go. The VPS deploys tags only.

## 5. Architecture

### 5.1 Logger firmware (ESP32-S3, PlatformIO + Arduino framework)
- **Read:** Modbus RTU master (FCN300-3E4Y, register table in config: address, function code, type, word order, scale), temperature and humidity from **`TH1`** (I2C, on the board) and **`TH2`** (AM2301, single wire), DS3231 RTC, ADS1115 (later). The sensors are a list in the config (id, type, pin or address, location label), so a third sensor is a config line.
- **Timestamp:** RTC, set by NTP when online. Everything is in UTC.
- **Store-and-forward:** every record is written to the **SD card first** (daily CSV + a send queue), then uploaded. The backlog is sent when the link comes back, so nothing is lost.
- **Uplink:** **HTTPS POST of CSV lines (the day file's header + up to 60 rows) to `/api/v1/ingest`** with a per-device token (agreed 7 November 2026; was JSON batches).
- **Live:** every 15 s, a small snapshot of the live values to `/api/v1/live` (not buffered, best effort; `docs/LIVE.md`).
- **Remote management:** OTA firmware updates pulled from the platform; remote config of the settings (intervals, Modbus address, offsets; not the register table, which is a file on the SD card); heartbeat (RSSI, uptime, free heap, SD state, backlog size, firmware version).
- **Robustness:** watchdog, WiFi reconnect, keeps running if the SD card fails, logs a boot reason (a power cut shows as a cold boot after a gap).
- **Setup:** WiFi credentials through a one-time setup page in access-point mode, stored in NVS.

### 5.2 Data contract (frozen in S1; field names follow the CMMS meter list)

> **Agreed 7 November 2026 (v0.11):** the logger uploads the **CSV lines of its day file** (header + up to 60 rows) instead of the JSON below; the columns (schema 2, with min and max) are in `docs/DATA-FORMAT.md` §3. The JSON stays for the live snapshot.

```json
POST /api/v1/ingest   Authorization: Bearer <device-token>
{
  "device": "LOG-0001", "fw": "0.1.0",
  "records": [
    { "ts": "2026-11-05T00:00:00Z", "seq": 10234,
      "env":   [ { "id": "TH1", "temp": 31.4, "hum": 62.0 },
                 { "id": "TH2", "temp": 29.8, "hum": 66.5 } ],
      "meters": [ { "id": "EM01",
        "ph":  [ { "v": 231.0, "i": 41.2, "p": 8.9, "pf": 0.93 }, { }, { } ],
        "vll": [ 400.1, 399.2, 400.6 ],
        "p": 27.6, "q": 9.8, "s": 29.3, "pf": 0.94, "f": 50.0, "e": 184522.7 } ],
      "sys":   { "rssi": -63, "uptime": 86400, "backlog": 0, "boot": "poweron" } }
  ]
}
```
- The site is found from the device token, so the payload carries no site name.
- `e` is the meter's **cumulative kWh counter**, stored as it is. Consumption is computed on the server, so gaps never corrupt totals.
- Duplicates are dropped by timestamp `ts` when the backlog is resent (v0.10: no `seq`).
- `env` is a **list of sensors**, one entry per sensor id. A sensor that failed its read sends `"err": "timeout"` (or `"checksum"`) instead of values, so a fault is never mistaken for a reading. The location of each id (for example "electrical room", "outside the box") is in `site.json`, not in the payload.

### 5.3 Platform (`arkan-monitoring`, Python 3.11 standard library)

**The data folder.** All recorded data lives in one dedicated folder, `/srv/arkan-monitoring/data/`, outside the code and outside the container image, with **one subfolder per site**:

```
/srv/arkan-monitoring/data/
  sites/
    adab/                           one folder per site, named by the site code
      site.json                     the site profile: name, timezone (Asia/Makassar), coordinates, devices, meters, alert thresholds
      <device>/                     one folder per logger (LOG-0001)
        raw/2026/11/2026-11-05.csv  1-minute records of that day (UTC), the same columns as the logger's SD card file
        events.jsonl                boots, gaps, config changes, OTA updates, alerts
      daily.csv                     one row per day: kWh, peak kW and its time, min/max room temperature, minutes received
      monthly.csv                   one row per month
    <next site>/
  devices.json                      device code -> site, token hash, firmware version, last seen (no token in clear)
  logs/                             reserved (the service logs to docker logs: docker compose logs ingest)
```

- **Plain CSV and JSON**: the files can be opened in Excel or read by Claude, Codex or PowerShell over SSH without the app, and copied site by site.
- **Same CSV columns on the SD card and on the server.** Backfilling a gap is a copy of the SD card's day files into the site folder; the tool merges them by timestamp `ts` and drops duplicates.
- **Append-only day files.** A new day starts a new file. The daily and monthly files are rewritten through a temporary file that is then swapped in, so a reader never sees half a file (the CMMS rule).
- **Size:** about 1,440 rows a day per logger, around 100 MB a year. A day chart reads one file; a month view reads `daily.csv`.
- **Adding a site** = a new subfolder with its `site.json`, made by `tools/add_site.py`. **Removing or archiving a site** = moving its folder.
- **Backup:** the whole folder, nightly, as in `arkan-hub/deploy/backup.sh`. It can later be synced to Google Drive the same way, site by site.
- If reading many files ever becomes slow, a cache can be added per site. It would be rebuilt from the CSV files, which stay the record.

**The ingest service (`arkan-monitoring`, Python 3.11 standard library):**
- **Ingest:** `/api/v1/ingest` checks the token and the schema, appends the rows to the site's day file, and answers with the counts stored, duplicated and rejected and the last `ts`.
- **Push to OED:** every 5 minutes, the new rows of each site go to OED's CSV upload API (`POST /api/csv/readings`, with an OED user that has the CSV role). One OED meter per measured value:

  | OED meter (site `adab`) | Unit in OED | Type | Graphs |
  |---|---|---|---|
  | `adab-EM01-energy` | kWh (from the meter's cumulative counter, `cumulative=yes`) | quantity | line (shown as kW), bar (kWh per day, week), compare, map |
  | `adab-TH1-temp` (electrical room), `adab-TH2-temp` (outdoor) | Celsius (built into OED) | raw | line |
  | `adab-TH1-hum`, `adab-TH2-hum` | **% RH** (a unit we add once, raw) | raw | line |
  | `adab-EM01-i1/i2/i3`, `-v1/v2/v3`, `-pf` (optional, lower case as the exporter writes them) | A, V, PF (units we add, raw) | raw | line |

  - The group **`adab`** holds the site's **energy** meters; a group **"All sites"** holds the site groups. OED refuses meters without a common unit in one group, so temperature and humidity meters are not in groups (tutorial 3).
  - **OED stores times without a timezone**: the push sends WITA local time (UTC+8, no daylight saving). Our files stay in UTC.
  - **OED is not a live view.** Readings appear after each push (5 minutes) and daily graphs after its view refresh. The "now" values and the logger's health are on the live page of the ingest service, refreshed every 15 s.
  - The push is idempotent: it keeps, per site and meter, the last time sent, and can resend a whole day from the files.
- **Live page** (`/live/` for all sites, `/live/<site>/` per site): the values listed in `site.json`, refreshed every 15 s, with a 60-minute sparkline, the logger's status (online, backlog, last push to OED), the open alarms and links to OED. Snapshots are kept in memory only (`docs/LIVE.md`).
- **History pages** on the same site page (side menu): power, one day, energy per day, this week vs last, temperature and humidity, from the day files through `/api/v1/history/<site>` (`docs/LIVE.md`).
- **Device API:** config and OTA for the loggers.
- **Alerts:** checked against the **alarm register** `alarms.csv` (`docs/alarms/`): 20 alarms to start, each with its threshold, delay, severity and a **`whatsapp` yes/no** column. A per-site copy in the site folder can override a line.
  - **Sent to the owner's WhatsApp group through Hermes.** The service POSTs the alert to a Hermes webhook route (`http://<docker gateway>:8644/webhooks/arkan-monitoring`), signed with HMAC-SHA256 (`X-Webhook-Signature-V2`). The route uses `deliver: whatsapp`, the group's `chat_id` and **`deliver_only: true`**, so Hermes sends the text as it is, without running the agent (no LLM cost). Hermes answers 200 when delivered and 502 when refused; the service retries.
  - The route is added to Hermes's config by the owner (sessions do not touch Hermes). Port 8644 must stay closed to the internet.
  - As in `arkan-solar-desk`: sending is **off by default** (`alerts.send` in the settings). Every alert is written to the site's `events.jsonl` and shown on the live page, whether it was sent or not.
  - Repeats are throttled: one message when an alert starts, one when it clears, a reminder every 6 hours at most.
- **`tools/`** (run from the laptop or the VPS):
  - add a site or a device and issue its token; create the site's meters and group in OED;
  - export CSV;
  - **backfill from an SD card's CSV files** (then pushed to OED);
  - rebuild a site's daily and monthly files from its day files;
  - resend a period to OED.

### 5.4 Deploy on hermes-vps
- **Two parts, both on loopback only:**
  - **OED**: `web` (Node.js) and `database` (PostgreSQL), published on `127.0.0.1:<oed port>`; Postgres data in `/srv/arkan-monitoring/oed-postgres/`. **Not OED's default compose**: our own lean image built off the VPS, tuned PostgreSQL and memory limits (`docs/VPS-MEMORY.md`).
  - **The ingest service**: one container on `127.0.0.1:<ingest port>` (proposed 8800; check it is free: the Hub uses 8780, the CMMS 8790). Data in `/srv/arkan-monitoring/data/` (§5.3), mounted at `/data`, owned by uid 1000.
- The code is cloned to `/opt/arkan-monitoring`, checked out at a tag. OED is built from a **pinned OED release or commit**, recorded in the repository.
- `/opt/edge/sites/monitoring.caddy`, its own host block for `arkan-monitoring.duckdns.org`:
  - `/` goes to **OED**, `/live/` to the ingest service's live page, both behind `basicauth` with `import /opt/edge/secrets/hub-users.caddy` (**the same logins as the other dashboards**). OED's own admin login stays for its settings pages.
  - `/api/v1/ingest` and the device endpoints go to the ingest service **without basicauth**: the logger cannot sign in through it, so the device token is checked in the service.
  - OED's own CSV upload API stays **behind the Arkan login** (OED's CSV upload page uses the same API, and the API also needs an OED user with the CSV role). The draft Caddy file has a commented block to close it completely once the automatic push exists (owner to decide).
  - The log filtered as in `cmms.caddy`, HSTS, `noindex`.
- DuckDNS: create the `arkan-monitoring` name, point it to the VPS IP, and keep it updated the way the other duckdns names are.
- Nightly backup of the data folder and an OED database dump (`pg_dump`), kept as in `arkan-hub/deploy/backup.sh`. OED can be rebuilt from the data folder at any time by resending.

### 5.5 Physical install (MDP, back of house)
- The logger in a small IP54 plastic box **beside** the steel panel. Check WiFi RSSI on site first: better than -70 dBm.
- RS485: shielded twisted pair, A/B to the meter, shield grounded at one end, 120 ohm termination at both ends if the run is long, kept away from power cables.
- Power: 5 V / 2 A adapter on **USB-C**.
- Photograph the meter settings (Modbus address, baud rate, CT ratio) for the as-built record.
- Check the room temperature reading against a reference thermometer.

## 6. Phases

| # | Phase | Output | Exit criterion |
|---|---|---|---|
| P0 | Review | This plan v1.0, meter register guide (received), WiFi credentials | Plan approved |
| P1 | Foundations | New `arkan-monitoring` repository; layout of both repositories, data contract, CI, vendored UI kit, `CLAUDE.md` + `AGENTS.md` in each | CI green in both: `pio run` here, `pytest` in `arkan-monitoring` |
| P2 | Firmware MVP (parallel with P3) | Sensors, RTC, SD, Modbus, HTTPS uplink, backlog | 48 h bench soak; 0 records lost after WiFi is pulled for 1 h |
| P3 | Platform MVP (parallel with P2) | Ingest, per-site data folders, push to OED, live page, alarms, deploy files, tools | Simulated logger's data shows in a local OED, tests pass |
| P4 | VPS + bench | Platform live on `arkan-monitoring.duckdns.org`; real board on the bench feeding it | Bench logger visible with the Arkan login |
| P5 | Remote ops | OTA, remote config, alerts | OTA update without touching the board; offline alert received |
| P6 | Site install | Mounted, wired, commissioned | Meter values match the meter display within 1 %; data live for 24 h |
| P7 | Validation | 1-week data review in OED | 7 days, more than 99 % of minutes present |
| P8 | Platform phase 2 | More meters and sites, reports, KPIs | A second site added by configuration only |

## 7. Work split: sessions and agents

Rule: **one session = one deliverable that ends in a PR.** Agents run in parallel inside a session on separate parts (separate worktrees); the session merges their work and opens the PR. Work that needs the board on USB or SSH to hermes-vps runs **on the laptop** (local Claude Code); everything else runs in **cloud sessions**.

| Session | Where | Needs | Agents inside the session (parallel) | Deliverable |
|---|---|---|---|---|
| **S0** Plan review (this one) | cloud, `esp32-datalogging` | | | This plan v1.0 |
| **S1** Foundations | cloud, **both repositories** | S0; you create the empty private repository `arkan-monitoring` (or approve that Claude creates it) | A1 `esp32-datalogging`: firmware skeleton (PlatformIO, ESP32-S3) + CI · A2 `arkan-monitoring`: platform skeleton, deploy set copied from `arkan-cmms`, vendored UI kit, data folder layout (§5.3), `CLAUDE.md`/`AGENTS.md` · A3 `arkan-monitoring`: data contract (JSON Schema, CSV columns, example payloads), then copied to `esp32-datalogging/contract/`; the FCN300-3E4Y register table seeded from the guide | Both skeletons, contract frozen at v1 |
| **S2** Firmware MVP | cloud, `esp32-datalogging` | S1 | A1 drivers: RTC, T/RH, SD, ADS1115 · A2 Modbus master + FCN300-3E4Y table + a simulated meter for tests + `tools/modbus_dump.py` (laptop register dump) + an ESPHome YAML for a first meter test · A3 WiFi setup page, HTTPS uplink, store-and-forward queue | Firmware builds, unit tests pass |
| **S3** Platform MVP | cloud, `arkan-monitoring` | S1 | A1 ingest + per-site day files + daily/monthly files + tools (add site, tokens, CSV export, SD backfill) + tests · A2 OED: pinned release, compose with our settings, units (% RH, A, V, PF), meters and groups created by a tool through OED's API, the push service, tested against a local OED · A3 live page and `/api/v1/live`, alarms from `alarms.csv` (Hermes webhook client, sending off by default), lean OED image and memory limits measured with `docker stats`, deploy files (`monitoring.caddy` with the shared login and the open ingest path), backup, smoke tests | Simulated logger's data shows in a local OED and on the live page; RAM measured |
| **S4** Bench bring-up | **laptop, board on USB**, `esp32-datalogging` | S2 | A1 pin check (I2C scan, SD, RS485 loopback) · A2 **meter register check** (`docs/meter/README.md`): dump with the laptop, compare with the LCD, write the verified map. **No spare meter yet**, so this is done at the hotel during a first short visit (laptop + USB-RS485 adapter, no install), unless one is bought before | Pin map confirmed, registers verified, 48 h soak started |
| **S5** VPS deploy | **laptop, `ssh hermes-vps`**, `arkan-monitoring` | S3 | One operator, in sequence. The owner does the `sudo` steps (data folder `/srv/arkan-monitoring/data/`, Caddy site file) and approves the Caddy reload | Platform live, bench logger visible with the Arkan login |
| **S6** Remote ops | cloud, both repositories | S4, S5 | A1 OTA + remote config (firmware here, server side in `arkan-monitoring`) · A2 alerts through the Hermes webhook (the owner adds the route) + install checklist (`docs/install-checklist.md`) | OTA and alerts proven on the bench unit |
| **S7** Site install | on site, **you + Claude on the phone** | S6 | | Installed and commissioned |
| **S8** Validation | cloud, then laptop | S7 + 7 days | A1 data quality report (gaps, logger vs meter display, OED vs files) · A2 as-built record and operating guide | Hand-over |
| **S9** Arkan integration (later) | | S8 | Arkan design for the platform; `arkan-cmms` Monitoring on real data | Planned separately |
| **S10+** Platform phase 2 | | S8 | Planned separately | |

**Critical path:** S0, S1, then S2 and S3 in parallel, then S4 and S5 in parallel, then S6, S7, S8.
The **meter register check** is the one uncertain step on that path: the spare meter has no Modbus port (8 November), so it is done at the hotel at the first visit and the install day gets longer (`docs/meter/README.md` section 4).

**Who does what**
- **You (Arkan):**
  - get the staff WiFi credentials; photograph the meter's label (3E4Y or 3EH4Y) and its back (RS485 terminals); buy a spare meter for the bench if wanted;
  - give the WhatsApp group that receives the alerts (its chat id for the Hermes route);
  - add the Hermes webhook route for WhatsApp alerts (S6);
  - create the DuckDNS name;
  - approve PRs and the Caddy reload;
  - run S4 and S5 on the laptop, and the install day.
- **Claude cloud sessions:** code, tests, docs and PRs (S1, S2, S3, S6, S8).
- **Claude on the laptop (or Codex):** flashing, hardware debugging, SSH deploys (S4, S5).

## 8. Open points

| # | Point | Proposal |
|---|---|---|
| P1 | Client name in the repository | **Settled**: `adab` is the site code and name, in both repositories |
| P2 | The new platform repository | **Settled**: `arkan-monitoring`, private, created by Claude in S1 |
| P3 | Alert channel | **Settled**: WhatsApp through Hermes. Open: which WhatsApp group or number receives them, and whether Hermes's webhook platform is on |
| P4 | FCN300-3E4Y register map | Guide received, **not verified** (`docs/meter/README.md`). The spare meter at the office has **no Modbus port** (8 November): verified **on site** at the first visit, `docs/meter/README.md` section 4; proposed table `docs/meter/registers-proposed.csv`. CTs are 250/5 A (owner, 8 November), to be confirmed on their labels |
| P5 | Platform | **Settled**: Open Energy Dashboard + our ingest service. Arkan design integration later |
| P6 | Meter variant | Read the label: FCN300-**3E4Y** (guide received) or **3EH4Y** (link sent). If 3EH4Y, ask the seller for its register map |
| P7 | RAM on hermes-vps | Plan in `docs/VPS-MEMORY.md` (about 300 to 450 MB). Check free memory and swap before S5 (`free -h`) |
| P8 | Alarm thresholds | Supply voltage, contracted kVA, room limits to confirm (`docs/alarms/README.md`) |

## 9. Bill of materials (trial)
- 5 V / 2 A USB-C adapter
- IP54 plastic enclosure, cable glands, mounting
- Shielded twisted-pair cable for RS485 (length: logger to meter), ferrules
- microSD card, industrial grade, 8 to 32 GB, FAT32
- AM2301 (DHT21) sensor (owner's), a 4.7 kohm resistor, about 2 m of 3-core shielded outdoor-rated cable, two cable glands, sealant for the wall pass
- A radiation shield (louvred screen) for the AM2301 and a mounting bracket
- USB-RS485 adapter, for the bench test with a simulated meter and for site debugging
- A spare CR1220 cell

## 10. Risks
| Risk | Mitigation |
|---|---|
| Register guide wrong or incomplete | Configurable register table; register dump compared with the LCD; the proposed table and the on-site check (`docs/meter/README.md`); the spare meter cannot be read (no Modbus port) |
| The meter has no RS485 port | Check the back of the meter before buying anything else; if absent, a meter with Modbus is needed |
| Weak WiFi at the back of house | Box outside the panel; RSSI check before mounting; 4G router as a fallback |
| Power cuts (no UPS) | RTC keeps time; the SD queue keeps unsent data; the gap is shown as "logger offline" |
| SD card wear or corruption | Industrial card, append-only files, SD health in the heartbeat |
| Shared VPS (Hub, CMMS, other services) | Loopback port only, its own container and data folder, no `sudo` by sessions, owner approves live changes |
| Open ingest path on the internet | Per-device token, size limit, rate limit in the app, schema check, tokens revocable from settings |
| Unattended device needs a fix | OTA + remote config proven before the install (S6 before S7) |
