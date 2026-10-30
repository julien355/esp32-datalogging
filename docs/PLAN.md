# Adab Hotel Energy Logger: Installation Plan

Status: **DRAFT v0.2, 30 October 2026.** Review answers of 30 October are in §3; the choice of base repository is in §4.
Sources: `docs/img/sketch-adab-logger.jpg` (hand sketch), `docs/img/board-top.jpg`, `docs/img/board-bottom.jpg`,
and the repositories `arkan-cmms`, `arkan-hub`, `arkan-solar-desk`, `arkan-skills-V1` (read on 30 October 2026).

---

## 1. What the sketch says (confirmed in review)

**On site (Adab hotel, main distribution panel in the back-of-house area)**
- The **Bluino ESP32-S3 TMP/RH RS485 RTC AI** board, with its built-in temperature and humidity sensor (it reads the **electrical room's air**), an SD card, a real-time clock and WiFi.
- It reads **one Fort FC300 power meter** over RS485 (Modbus RTU). More meters may be added later.
- **5 V** from an adapter plugged into a socket in the panel. **No UPS for the trial.**
- It goes online through the hotel's **staff WiFi network** (WPA2 password, no login page).

**On the VPS (`hermes-vps`, Hostinger, Ubuntu)**
- The ingest script and the dashboard, at **`https://arkan-monitoring.duckdns.org/`**, with the same logins as the other Arkan dashboards.
- The laptop (Claude, Codex, PowerShell) reaches both the data and the server over SSH.

**What it leads to**
1. The Monitoring page in `arkan-cmms` for this hotel. That page already exists, with simulated data.
2. The **full monitoring platform** for many sites and devices. Adab is its pilot. This is what this repository builds.

```
 [Fort FC300] --RS485/Modbus--> [ESP32-S3 logger] --staff WiFi--> internet
                                  | T/RH (room air), RTC, SD                 |
 panel socket -> 5V adapter ------+                                          v  HTTPS POST, device token
                                     hermes-vps: native Caddy -> monitoring container (Python + SQLite)
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
| Temp/RH | Blue I2C breakout module on the board (AHT/HTU/SHT family) | Reads room air plus some board self-heat; check against a reference thermometer on site. |
| Analog in | ADS1115 (16-bit, 4 ch, I2C) | Spare for now. |
| RS485 | 8-pin transceiver, **120 ohm termination jumper**, TX/RX LEDs, screw terminals | Modbus RTU master to the meter. |
| I2C header | "I2C (OLED)" 4-pin | Optional local display. |

**Provisional pin map.** Read from the mirrored, blurry back silkscreen. **Not verified**: confirm in bench bring-up (session S4).

| Function | GPIO (provisional) |
|---|---|
| I2C SDA / SCL | 8 / 9 |
| SD SCK / MISO / MOSI / CS | 12 / 13 / 11 / 10 or 21 |
| RS485 TX / RX / DE-RE | top 3 rows of the back table, to verify |

## 3. Review answers (30 October 2026)

| # | Question | Answer | Effect on the plan |
|---|---|---|---|
| 1 | Meter model and register map | **To be confirmed.** `arkan-cmms` calls it the **Fort FC300** (not FCN300) and notes that no datasheet was found online | Get the register map from the supplier or read it off the meter's manual. **Blocks S2 (meter driver) and S4 (bench test).** Until then the driver is written against a configurable register table |
| 2 | How many meters | **1 for now**, more later | Firmware and database take N meters per logger from the start |
| 3 | Codex | **Not crossed out**: Claude, Codex and PowerShell | Repository rules go in `AGENTS.md` too (as in `arkan-skills-V1`) |
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
| 14 | Access | **Same as the other dashboards** | Caddy `basicauth` with the shared login file `/opt/edge/secrets/hub-users.caddy`; the signed-in name reaches the app in `X-Auth-User` |

## 4. Which existing repository to build on

### 4.1 What exists

| Repository | What is useful for monitoring | What does not fit |
|---|---|---|
| **arkan-cmms** | **Monitoring views already built** on the Arkan UI kit (`cmms-demo/src/features.js`): Fort FC300 meter card (V, A, kW, kVAr, kVA, PF, Hz, kWh per phase), demand chart 00:00 to 24:00 with peak and outage shading, temp/RH charts with dew point, a 56-term glossary (EN + ID). Server weather API (MET Norway, BMKG). **VPS deploy files for hermes-vps**: Dockerfile, compose on loopback, `sites/cmms.caddy` with the shared Hub login, `update-vps.sh` | One property per instance, built by patching a demo page. The user asked for the platform to be separate from the CMMS |
| **arkan-hub** | The **deploy and access pattern**, written up and smoke-tested on hermes-vps: trusted-proxy `X-Auth-User`, `/health`, audit log, `update.sh` by tag with rollback, `backup.sh`, smoke tests, install guide | Built around the project record (`arkan_mcp` wheel) and one container per project. Not a time-series app |
| arkan-solar-desk | Same Python standard-library server pattern | Different domain (PV workflow desk), nothing for telemetry |
| arkan-skills-V1 | Engineering references (`solar-pv-energy-storage/references/calc-monitoring.md`, `senior-electrical-elv-engineer/.../calc-energy-efficiency.md`, `calc-power-quality-pfc.md`) for which KPIs to show | Skills and MCP, not an app |

No repository has an ingest endpoint, a time-series store or device code. That part is new whatever we choose.

### 4.2 Recommendation

**Build the platform in this repository** (`esp32-datalogging`, renamed `arkan-monitoring` if you agree) as one repository with `firmware/` and `platform/`:
- **Copy the patterns, do not depend on the other repos at runtime:**
  - the Python standard-library server pattern (Hub/CMMS);
  - the **Arkan UI kit, vendored** as `arkan-cmms/arkan-ui/` does (`VENDORED.md`);
  - the **deploy set from `arkan-cmms/cmms-app/deploy/`** (Dockerfile, `docker-compose.vps.yml`, `sites/*.caddy` with the shared login, `update-vps.sh`);
  - `/health`, backup and smoke tests from `arkan-hub`.
- **Port the CMMS Monitoring views** (meter card, phases, demand day chart, peak, energy, temp/RH with dew point, glossary terms) into the platform's site page, fed by the real API instead of the simulator.
- **Storage: SQLite** (Python standard library), one file on the VPS, WAL mode. Raw 1-minute rows plus 15-minute and daily rollups. One logger with one meter is about 0.5 M rows a year, around 100 MB, which SQLite handles easily for dozens of devices. No new database server on a VPS that already runs other services.
- **One repository for firmware and platform** because they share the data contract: a change to the payload changes both sides in one PR, with one version number.
- **Afterwards, `arkan-cmms` reads the real feed** from the platform, server to server, the way it already reads the weather (`api/weather`). That is a small change in `arkan-cmms`, in its own session (S8). The CMMS page stays the hotel's view; the platform is Arkan's multi-site view.

**Why not the alternatives**
- **Grafana + InfluxDB/Timescale:** a new stack and a second login system, a look that does not match the Arkan dashboards, and more services on a shared VPS.
- **Inside `arkan-cmms`:** you asked for the platform to be separate. The CMMS is also one property per build, made by patching a demo page.
- **Inside `arkan-hub`:** the Hub is built around the project record, one instance per project. Monitoring is per site and per device, with time series.

### 4.3 House rules taken over from the other repositories
- No em dashes or en dashes in any text.
- Interface in English and Indonesian.
- Real site names, places, paths and tokens stay out of the repository, in a **site profile on the VPS** (as in `arkan-cmms/profiles/`). See open point P1.
- Sessions do not `sudo` on hermes-vps. Caddy reloads and container restarts are live changes: the owner approves each one.
- Never overwrite an existing file on the VPS without asking. Leave the other services alone.
- One branch per work package. Nothing merges to `main` without the owner's go. The VPS deploys tags only.

## 5. Architecture

### 5.1 Logger firmware (ESP32-S3, PlatformIO + Arduino framework)
- **Read:** Modbus RTU master (FC300, register table in config), I2C temp/RH, DS3231 RTC, ADS1115 (later).
- **Timestamp:** RTC, set by NTP when online. Everything is in UTC.
- **Store-and-forward:** every record is written to the **SD card first** (daily CSV + a send queue), then uploaded. The backlog is sent when the link comes back, so nothing is lost.
- **Uplink:** **HTTPS POST of JSON batches to `/api/v1/ingest`** with a per-device token.
- **Remote management:** OTA firmware updates pulled from the platform; remote config (intervals, Modbus address, register table); heartbeat (RSSI, uptime, free heap, SD state, backlog size, firmware version).
- **Robustness:** watchdog, WiFi reconnect, keeps running if the SD card fails, logs a boot reason (a power cut shows as a cold boot after a gap).
- **Setup:** WiFi credentials through a one-time setup page in access-point mode, stored in NVS.

### 5.2 Data contract (frozen in S1; field names follow the CMMS meter list)
```json
POST /api/v1/ingest   Authorization: Bearer <device-token>
{
  "device": "LOG-0001", "fw": "0.1.0",
  "records": [
    { "ts": "2026-11-05T00:00:00Z", "seq": 10234,
      "env":   { "temp": 31.4, "hum": 62.0 },
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
- `seq` drops duplicates when the backlog is resent.

### 5.3 Platform (`platform/`, Python 3.11 standard library + SQLite)
- **Ingest:** `/api/v1/ingest` checks the token and the schema, writes the rows, and answers with the last `seq` stored.
- **Read API** for the pages and for `arkan-cmms`: live values, day series, rollups, CSV export.
- **Device API:** config and OTA.
- **Pages** on the Arkan UI kit:
  - **All sites:** status (online, offline since), live kW, today's kWh, peak, room temperature, last seen.
  - **Site page:** the ported CMMS Monitoring views.
  - **Device health.**
  - **Settings:** sites, devices, tokens.
- **Alerts:** logger offline over 15 min, backlog growing, room temperature too high, meter not answering. The channel is still to choose (P3).
- **`tools/`** (run from the laptop or the VPS):
  - add a site or a device and issue its token;
  - export CSV;
  - **backfill from an SD card's CSV files**;
  - SQLite backup.

### 5.4 Deploy on hermes-vps (copied from `arkan-cmms/cmms-app/deploy/`)
- Container `arkan-monitoring` on `127.0.0.1:<port>`. Proposed port 8800; check it is free (the Hub uses 8780, the CMMS 8790).
- Data in `/srv/arkan-monitoring/data/` (the SQLite file, the site profiles).
- The code is cloned to `/opt/arkan-monitoring`, checked out at a tag.
- `/opt/edge/sites/monitoring.caddy` gets its own host block for `arkan-monitoring.duckdns.org`:
  - `basicauth` with `import /opt/edge/secrets/hub-users.caddy` (**the same logins**) on every path **except** `/api/v1/ingest` and the device endpoints. Those are open to the internet and protected by the device token in the app, because the logger cannot sign in through basicauth.
  - `request_header -X-Auth-User`, then `X-Auth-User` set from the sign-in.
  - The log filtered as in `cmms.caddy`, HSTS, `noindex`.
- DuckDNS: create the `arkan-monitoring` name, point it to the VPS IP, and keep it updated the way the other duckdns names are.
- Nightly backup with `sqlite3 .backup`, kept as in `arkan-hub/deploy/backup.sh`.

### 5.5 Physical install (MDP, back of house)
- The logger in a small IP54 plastic box **beside** the steel panel. Check WiFi RSSI on site first: better than -70 dBm.
- RS485: shielded twisted pair, A/B to the meter, shield grounded at one end, 120 ohm termination at both ends if the run is long, kept away from power cables.
- Power: 5 V / 2 A adapter on **USB-C**.
- Photograph the meter settings (Modbus address, baud rate, CT ratio) for the as-built record.
- Check the room temperature reading against a reference thermometer.

## 6. Phases

| # | Phase | Output | Exit criterion |
|---|---|---|---|
| P0 | Review | This plan v1.0, FC300 register map, WiFi credentials | Plan approved; register map in hand (or S2 starts with a configurable table) |
| P1 | Foundations | Repository layout, data contract, CI, vendored UI kit, `CLAUDE.md` + `AGENTS.md` | CI green: `pio run` and `pytest` |
| P2 | Firmware MVP (parallel with P3) | Sensors, RTC, SD, Modbus, HTTPS uplink, backlog | 48 h bench soak; 0 records lost after WiFi is pulled for 1 h |
| P3 | Platform MVP (parallel with P2) | Ingest, SQLite, pages, deploy files, tools | Simulated logger shows live on a local run, tests pass |
| P4 | VPS + bench | Platform live on `arkan-monitoring.duckdns.org`; real board on the bench feeding it | Bench logger visible with the Arkan login |
| P5 | Remote ops | OTA, remote config, alerts | OTA update without touching the board; offline alert received |
| P6 | Site install | Mounted, wired, commissioned | Meter values match the meter display within 1 %; data live for 24 h |
| P7 | Validation + CMMS link | 1-week data review; CMMS Monitoring reads the real feed | 7 days, more than 99 % of minutes present |
| P8 | Platform phase 2 | More meters and sites, reports, KPIs | A second site added by configuration only |

## 7. Work split: sessions and agents

Rule: **one session = one deliverable that ends in a PR.** Agents run in parallel inside a session on separate parts (separate worktrees); the session merges their work and opens the PR. Work that needs the board on USB or SSH to hermes-vps runs **on the laptop** (local Claude Code); everything else runs in **cloud sessions**.

| Session | Where | Needs | Agents inside the session (parallel) | Deliverable |
|---|---|---|---|---|
| **S0** Plan review (this one) | cloud | | | This plan v1.0 |
| **S1** Foundations | cloud | S0 | A1 firmware skeleton (PlatformIO, ESP32-S3) + CI · A2 platform skeleton: deploy set copied from `arkan-cmms`, vendored UI kit, `CLAUDE.md`/`AGENTS.md` · A3 data contract: JSON Schema, example payloads, the FC300 register table (template until the map arrives) | Repository skeleton, contract frozen |
| **S2** Firmware MVP | cloud | S1 | A1 drivers: RTC, T/RH, SD, ADS1115 · A2 Modbus master + FC300 table + a simulated meter for tests · A3 WiFi setup page, HTTPS uplink, store-and-forward queue | Firmware builds, unit tests pass |
| **S3** Platform MVP | cloud | S1 | A1 ingest + read API + SQLite + rollups + tools (tokens, CSV, SD backfill) + tests · A2 pages: all sites, and the site page ported from the CMMS Monitoring views (EN + ID) · A3 deploy: Dockerfile, compose, `monitoring.caddy` (shared login, open ingest path), update and backup scripts, smoke tests | `platform/` runs locally against a simulated logger |
| **S4** Bench bring-up | **laptop, board on USB** | S2 | A1 pin check (I2C scan, SD, RS485 loopback) · A2 simulated FC300 through a USB-RS485 adapter, or the real meter if one is free | Pin map confirmed, 48 h soak started |
| **S5** VPS deploy | **laptop, `ssh hermes-vps`** | S3 | One operator, in sequence. The owner does the `sudo` steps and approves the Caddy reload | Platform live, bench logger visible with the Arkan login |
| **S6** Remote ops | cloud | S4, S5 | A1 OTA + remote config (firmware + platform) · A2 alerts + install checklist (`docs/install-checklist.md`) | OTA and alerts proven on the bench unit |
| **S7** Site install | on site, **you + Claude on the phone** | S6 | | Installed and commissioned |
| **S8** Validation + CMMS link | cloud, then laptop | S7 + 7 days | A1 data quality report · A2 in **`arkan-cmms`**: Monitoring reads the platform's feed (server side, like `api/weather`), simulated data kept as the fallback | Hand-over, CMMS on real data |
| **S9+** Platform phase 2 | | S8 | Planned separately | |

**Critical path:** S0, S1, then S2 and S3 in parallel, then S4 and S5 in parallel, then S6, S7, S8.
The **FC300 register map** is the one outside input on that path: it is needed by S4 at the latest.

**Who does what**
- **You (Arkan):**
  - get the FC300 register map and the staff WiFi credentials;
  - create the DuckDNS name;
  - approve PRs and the Caddy reload;
  - run S4 and S5 on the laptop, and the install day.
- **Claude cloud sessions:** code, tests, docs and PRs (S1, S2, S3, S6, S8).
- **Claude on the laptop (or Codex):** flashing, hardware debugging, SSH deploys (S4, S5).

## 8. Open points

| # | Point | Proposal |
|---|---|---|
| P1 | Client name in the repository. `arkan-cmms` and `arkan-hub` keep every client and place name out of the repository; this repo has "Adab" in this plan and in the sketch photo | Name the site by a code here (for example `S01`), keep the real name, the place and the path in a site profile on the VPS, and remove the sketch photo from the repository. Your call |
| P2 | Rename this repository `arkan-monitoring` | Yes, so it matches the domain. GitHub redirects the old address |
| P3 | Alert channel | Email first; WhatsApp or Telegram later if wanted |
| P4 | FC300 register map | You get it from the supplier or the manual. Until then: a configurable table, tested on a simulated meter |

## 9. Bill of materials (trial)
- 5 V / 2 A USB-C adapter
- IP54 plastic enclosure, cable glands, mounting
- Shielded twisted-pair cable for RS485 (length: logger to meter), ferrules
- microSD card, industrial grade, 8 to 32 GB, FAT32
- USB-RS485 adapter, for the bench test with a simulated meter and for site debugging
- A spare CR1220 cell

## 10. Risks
| Risk | Mitigation |
|---|---|
| FC300 register map not found | Ask the supplier now; read registers on the bench with the laptop + USB-RS485 adapter before site day |
| Weak WiFi at the back of house | Box outside the panel; RSSI check before mounting; 4G router as a fallback |
| Power cuts (no UPS) | RTC keeps time; the SD queue keeps unsent data; the gap is shown as "logger offline" |
| SD card wear or corruption | Industrial card, append-only files, SD health in the heartbeat |
| Shared VPS (Hub, CMMS, other services) | Loopback port only, its own container and data folder, no `sudo` by sessions, owner approves live changes |
| Open ingest path on the internet | Per-device token, size limit, rate limit in the app, schema check, tokens revocable from settings |
| Unattended device needs a fix | OTA + remote config proven before the install (S6 before S7) |
