# Adab Hotel Energy Logger — Installation Plan

Status: **DRAFT v0.1, waiting for review** (see §3, open questions)
Sources: `docs/img/sketch-adab-logger.jpg` (hand sketch), `docs/img/board-top.jpg`, `docs/img/board-bottom.jpg`

---

## 1. What the sketch says (my reading)

Three layers, top to bottom:

### 1.1 Site: Adab hotel
- **Logger:** Bluino *ESP32-S3 TMP/RH RS485 RTC AI* board.
  - Built-in **temperature and % humidity** sensor.
  - **SD card** for local storage.
  - **RS485** link to an energy **meter, "Fort FCN300"** (model name to be confirmed).
  - **RTC** for timestamps.
  - **AI** (analog inputs) available but not used in the sketch.
- **Power:** **5 V** from an AC/DC adapter plugged into a socket in the
  **MD Panel, BOH** (main distribution panel, back of house). **UPS optional.**
- **Connectivity:** **WiFi** through the **site's internet**, out to the cloud ("ONLINE").

### 1.2 VPS (cloud)
- Holds `/folder`, `/script` and `/interface`, which together make the
  **`/arkan-cons/adab` dashboard**.
- **Live data** comes in from the site.
- **Data access + remote access** in both directions with **"my laptop"**,
  where the work is done with **Claude, Codex(?) and PowerShell**.

### 1.3 Visualization (two outputs)
1. **Web interface** at `arkan-cons…/adab`, a dashboard for this one site.
2. **Complete energy monitoring platform:** a platform and dashboard for
   **multiple sites and devices**. This is the long-term goal, and Adab is the pilot.

```
 [Fort FCN300 meter] --RS485/Modbus--> [ESP32-S3 logger] --WiFi--> hotel internet
                                         |  T/RH, RTC, SD                  |
 MDP BOH socket -> AC/DC 5V -> (UPS) ----+                                 v
                                                         VPS  (ingest API + DB + /adab web)
                                                          ^  \
                                     laptop (SSH, Claude) |   +--> multi-site platform (phase 2)
```

## 2. The hardware (from the photos)

| Block | What I see | Notes |
|---|---|---|
| MCU | ESP32-S3-WROOM module, **PCB antenna** | No external antenna. WiFi range suffers inside a metal panel. |
| Power in | USB-C (5 V), **DC jack marked 7–15 V**, 5V/3V3 pins on the header | Buck regulator (4R7 inductor) + LDO. **The DC jack takes 7–15 V, not 5 V.** A 5 V supply must go to USB-C or the 5V pin. |
| RTC | SOIC-16 chip (likely DS3231) + CR1220 coin cell | Keeps time when power or WiFi is lost. |
| Storage | microSD slot (SPI) | Header "SPI INTERFACE": GND 3V3 12 13 11 21 |
| Temp/RH | Blue I2C breakout module on board (AHT/HTU/SHT family) | It sits on the PCB, so it reads ambient plus board self-heat. |
| Analog in | ADS1115 (16-bit, 4 ch, I2C) | Spare. Could take CTs or a 0–10 V/4–20 mA signal later (check the input range). |
| RS485 | 8-pin transceiver, **120 Ω termination jumper**, TX/RX LEDs, green screw terminals | Modbus RTU master to the meter. |
| I2C header | "I2C (OLED)" 4-pin | Optional local display. |
| GPIO header | IO0, RST, 4–7, 9–12, 39–44, 47, 48, GND, 3V3, 5V | |
| Buttons | BOOT, RESET | |

**Provisional pin map.** Taken from the mirrored back silkscreen, which is blurry.
**Not verified**: confirm it in bring-up (I2C scan, SD mount, RS485 loopback).

| Function | GPIO (provisional) |
|---|---|
| I2C SDA / SCL | 8 / 9 |
| SD SCK / MISO / MOSI / CS | 12 / 13 / 11 / 10 or 21 |
| RS485 TX / RX / DE-RE | read from the back table (top 3 rows), to verify |

> Ask for the Bluino schematic or pinout PDF if the vendor has one. It saves a bring-up session.

## 3. Questions for review (please answer or correct)

**Understanding of the sketch**
1. Is the meter a **"Fort FCN300"**? Please send the datasheet or **Modbus register map**,
   and say whether it is **single-phase or three-phase**, its **CT ratio**, and whether it is **already installed** in the MDP.
2. Does the meter measure the **whole hotel incomer** or one feeder? Are more meters planned at Adab?
3. "Codex" in the laptop list: is it crossed out, or is it part of the toolset?
4. Is the domain **`arkan-cons.<tld>`**, already pointed to the VPS? Is the dashboard path **`/adab`**?
5. What is the temp/RH for: **room ambient in the BOH/electrical room**, or something else?

**Site constraints**
6. **Hotel WiFi:** is there a staff/IoT SSID with **WPA2 password and no captive portal**?
   Guest WiFi with a login page or client isolation will not work. Fallback: a 4G router.
7. **Can the logger sit outside the metal MDP** (plastic box next to it, RS485 cable in)?
   Inside a steel panel, the PCB antenna will likely lose WiFi.
8. Is there a **socket inside or near the MDP**, and who does the electrical work
   (a licensed electrician from the hotel or from Arkan)?
9. **UPS:** yes or no? I recommend yes (small DC UPS). The logger then keeps logging
   through outages and **timestamps power cuts**, which is valuable data in itself.
10. **Site timezone** (all data is stored in UTC and shown in local time).

**VPS / software**
11. VPS provider and OS, and what already runs on it (nginx? docker?). Is there SSH key access from the laptop?
12. Dashboard style for phase 1: **Grafana** (fastest, standard) or a **custom web page**
    (more on-brand, more work)? My recommendation: Grafana now, custom platform in phase 2.
13. Sample rate: proposed **meter every 15 s → 1-min averages, temp/RH every 60 s, upload every 1 min.** OK?
14. Who needs access to the `/adab` dashboard: only Arkan, or also hotel staff (login per client)?

## 4. Architecture (proposed)

### 4.1 Device firmware (ESP32-S3, PlatformIO + Arduino framework)
- **Read:** Modbus RTU master (meter), I2C T/RH, DS3231 RTC, ADS1115 (optional).
- **Timestamp:** RTC, kept in sync by NTP when online. Everything is in UTC.
- **Store-and-forward:** every record is written to the **SD card first** (daily CSV + a send queue),
  then uploaded. If WiFi or the VPS is down, the backlog is sent once the link is back. No data loss.
- **Uplink:** **HTTPS POST (JSON batches) on port 443.** It passes hotel firewalls more reliably than MQTT on port 8883.
  Each device has its own API token.
- **Remote management:** OTA firmware update pulled from the VPS, remote config (intervals, meter ID), heartbeat
  (RSSI, uptime, free heap, SD state, backlog size, firmware version).
- **Robustness:** hardware watchdog, WiFi auto-reconnect, safe boot if the SD card fails, power-fail event logging (with UPS).
- **Config:** WiFi credentials through a one-time setup portal (AP mode), stored in NVS.

### 4.2 Data contract (shared by firmware and server: write it first)
```json
POST /api/v1/ingest   Authorization: Bearer <device-token>
{
  "site": "adab", "device": "adab-logger-01", "fw": "0.1.0",
  "records": [
    { "ts": "2026-11-05T08:00:00Z", "seq": 10234,
      "env":   { "t_c": 27.4, "rh": 48.1 },
      "meter": { "v": [231.0,229.8,230.5], "i": [41.2,38.9,40.1],
                 "p_kw": 27.6, "pf": 0.93, "f_hz": 50.0,
                 "e_imp_kwh": 184522.7 },
      "sys":   { "rssi": -63, "uptime_s": 86400, "backlog": 0, "mains": true } }
  ]
}
```
Store the **cumulative kWh counter** as it is and compute consumption on the server, so gaps never corrupt totals.
`seq` is used to drop duplicates when the backlog is resent.

### 4.3 VPS
- Docker Compose stack behind **Caddy or nginx with TLS**:
  - `ingest-api` (FastAPI or Node): validates the token and schema, writes to the DB, serves OTA and config.
  - **PostgreSQL + TimescaleDB**: tables `sites`, `devices`, `readings`. Multi-site from day one, so phase 2 is not a rewrite.
  - **Grafana**: `/adab` dashboard (power, daily/monthly kWh, peak demand, V/I balance, PF, temp/RH, device health).
  - Alerts: **device offline > 15 min**, backlog growing, abnormal temp in the electrical room, power cut.
- Backups: nightly `pg_dump` sent off-box. SSH keys only, firewall open on 22/80/443 only.
- Laptop access: SSH, read-only DB user for Claude/PowerShell analysis, CSV export endpoint.

### 4.4 Physical install at Adab (MDP, BOH)
- The logger goes in a **small IP54 plastic enclosure outside the steel MDP**, with a WiFi RSSI check on site first (target better than −70 dBm).
- **RS485:** shielded twisted pair (e.g. Belden 3105A or Cat5e for short runs), A/B to the meter, shield grounded at one end,
  **120 Ω termination ON** at both ends if the run is long. Keep it away from power cables.
- **Power:** 5 V/2 A adapter on USB-C (or a 12 V DIN-rail supply on the DC jack, which is more robust in a panel) → optional DC UPS.
- Label everything; take photos of the meter settings (ID, baud, CT ratio) for the as-built record.
- ⚠ Any work inside the MDP is done by a **licensed electrician** with the panel isolated where required.

## 5. Phases and milestones

| # | Phase | Output | Exit criterion |
|---|---|---|---|
| P0 | Review and site info | Answers to §3, meter register map, WiFi creds, VPS access | Plan v1.0 approved |
| P1 | Foundations | Repo layout, data contract, CI building the firmware | `pio run` green in CI |
| P2 | Firmware MVP (parallel with P3) | Sensors + RTC + SD + Modbus + HTTPS uplink + backlog | 48 h bench soak, 0 lost records after WiFi pulled for 1 h |
| P3 | VPS stack (parallel with P2) | Ingest API, DB, Grafana `/adab`, TLS, backups | Firmware on the bench shows live on `arkan-cons…/adab` |
| P4 | Remote ops | OTA, remote config, heartbeat, offline alerts | OTA update done without touching the board |
| P5 | Site install | Mounted, wired, commissioned at Adab | Meter values match the meter display ±1 %; data live for 24 h |
| P6 | Hand-over and validation | As-built doc, runbook, 1-week data review | 7 days >99 % data completeness |
| P7 | Platform (phase 2) | Multi-site/multi-device platform and branded dashboard | Second site onboarded by config only |

## 6. Work split: sessions and agents

Rule: **one session = one clear deliverable that ends in a commit/PR.** Agents run in parallel
**inside** a session on independent parts (separate worktrees), and the session integrates their work.
Hardware and VPS-SSH work must run **on the laptop** (Claude Code local, board on USB / SSH keys).
Everything else can run in **cloud sessions**.

| Session | Where | Depends on | Agents inside the session (parallel) | Deliverable |
|---|---|---|---|---|
| **S0 — Plan review** (this one) | cloud | — | — | `docs/PLAN.md` v1.0 after your answers |
| **S1 — Foundations** | cloud | S0 | A1 repo scaffold (PlatformIO, `server/`, CI) · A2 data contract + JSON schema + example payloads · A3 meter register map → `docs/meter-fcn300.md` | Skeleton repo, contract frozen |
| **S2 — Firmware MVP** | cloud | S1 | A1 drivers: RTC, T/RH, ADS1115, SD · A2 Modbus RTU meter driver (+ simulator for tests) · A3 network: WiFi provisioning, HTTPS uplink, store-and-forward queue | Firmware compiles, unit tests pass, PR |
| **S3 — VPS stack** | cloud | S1 | A1 ingest API + DB schema + tests · A2 Grafana provisioning (dashboards as code) · A3 docker-compose, Caddy TLS, backups, hardening | `server/` deployable with one command, PR |
| **S4 — Bench bring-up** | **laptop + board on USB** | S2 | A1 pin verification (I2C scan, SD, RS485 loopback) · A2 fake meter via USB-RS485 adapter (Modbus slave sim on the laptop) | Pin map confirmed, firmware fixes, soak test started |
| **S5 — VPS deploy** | **laptop (SSH to VPS)** | S3 | — (sequential, one operator) | Live `arkan-cons…/adab`, device token issued, bench logger visible |
| **S6 — Remote ops** | cloud | S4, S5 | A1 OTA + remote config (fw + api) · A2 alerts (offline, backlog, temp, power cut) → email/Telegram/WhatsApp | OTA + alerts working on the bench unit |
| **S7 — Site install** | on site, **human + Claude on phone** | S6 | — | Installed, commissioned (checklist `docs/install-checklist.md`, written in S6) |
| **S8 — Validation** | cloud + laptop | S7 +7 days | A1 data-quality report (gaps, meter vs logger) · A2 as-built + runbook | Hand-over pack |
| **S9+ — Platform (phase 2)** | cloud | S8 | Planned separately: multi-tenant auth, site/device onboarding, branded UI | Separate plan |

**Critical path:** S0 → S1 → (S2 ∥ S3) → (S4 ∥ S5) → S6 → S7 → S8.
S2 and S3 run in parallel because the data contract is frozen in S1.

**Who does what**
- **Arkan (you):** answer §3, get the meter register map, WiFi creds and VPS access, approve PRs, run the laptop sessions (S4, S5), install day.
- **Electrician:** MDP work, socket, RS485 run (S7).
- **Claude cloud sessions:** code, tests, docs, PRs (S1, S2, S3, S6, S8).
- **Claude on laptop:** flashing, hardware debugging, SSH deploys (S4, S5).

## 7. Bill of materials still needed (to confirm)
- 5 V/2 A USB-C adapter (or 12 V DIN-rail PSU) · optional mini DC UPS
- IP54 plastic enclosure + cable glands · DIN rail / mounting
- Shielded twisted-pair cable for RS485 (length = logger ↔ meter) · ferrules
- microSD card, industrial grade, 8–32 GB (FAT32)
- USB-RS485 adapter (bench test with a simulated meter, and site debugging)
- CR1220 spare · optional external-antenna variant if WiFi is weak (ESP32-S3-WROOM-1U)
- Optional 4G router if the hotel WiFi is not usable

## 8. Risks
| Risk | Mitigation |
|---|---|
| Hotel WiFi has a captive portal, client isolation, or weak signal at BOH | Dedicated IoT SSID; enclosure outside the panel; 4G router fallback |
| Meter Modbus map unknown or wrong | Get the datasheet in P0; test with the laptop + USB-RS485 adapter before site day |
| Power cuts | SD buffer + RTC (no data loss); UPS for outage logging |
| SD card wear or corruption | Industrial card, append-only files, health check in heartbeat |
| Clock drift / wrong timestamps | DS3231 + NTP sync, UTC everywhere |
| Unattended device needs a fix | OTA + remote config before install (S6 comes before S7) |
| Safety in the MDP | Licensed electrician, isolation procedure |
