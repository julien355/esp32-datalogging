# esp32-datalogging

Energy and environment datalogger built on a Bluino ESP32-S3 (T/RH, RS485, RTC, analog inputs) board plus an AM2301 temp/RH sensor,
reading a FORT FCN300 (3E4Y or 3EH4Y, same registers) meter over Modbus RTU. Pilot site: **adab**.

- **Where everything is (GitHub, our computer `C:\dev\esp32-datalogging`, VPS, logger) and how to check it is up to date:** [`docs/CHECK-UP-TO-DATE.md`](docs/CHECK-UP-TO-DATE.md). **The general update of 10 November 2026**, step by step (VPS `v0.6.0` to `v0.8.0`, logger `0.4.1` to `0.5.1`, the technician's login): [section 7](docs/CHECK-UP-TO-DATE.md#7-general-update-to-do-now-in-order-10-november-2026)
- Plan and work split: [`docs/PLAN.md`](docs/PLAN.md). The monitoring platform (ingest, dashboards, per-site data folders) lives in its own repository, `arkan-monitoring`.
- What is reused from existing repositories and open-source projects: [`docs/REUSE.md`](docs/REUSE.md)
- Meter register map and what must be verified: [`docs/meter/`](docs/meter/)
- Alarm register and the alarm and warning log (which alarms are recorded, which go to WhatsApp): [`docs/alarms/`](docs/alarms/)
- **Step-by-step tutorials** (logger on site, VPS, Open Energy Dashboard, Modbus registers): [`docs/tutorials/`](docs/tutorials/)
- **How to update the VPS and the logger**, the same steps for every release (the VPS from its terminal, the logger by cable from VS Code and PlatformIO, or over the air from a GitHub release): [`docs/HOW-TO-UPDATE.md`](docs/HOW-TO-UPDATE.md). What each release needs on top (next: `v0.7.1`, section L, logins limited to one site; then `v0.8.0` with firmware `0.5.0`, section M, the Modbus link of each meter and the history pages with two dates and a CSV; then firmware `0.5.1`, section W, two WiFi networks of equal rank for a logger moved between two sites): [`docs/UPDATING.md`](docs/UPDATING.md)
- Site page `/live/<site>/`, in the Arkan design of the CMMS (side bar with **View as** and **Settings**, light, dark and high contrast): live data every 15 s, history pages, meter register page, firmware update: [`docs/LIVE.md`](docs/LIVE.md). Who can log in, and a technician's login limited to one site: [`docs/LIVE.md`](docs/LIVE.md#logins). The same page with saved answers, for reviews: [`docs/mockup/arkan/`](docs/mockup/arkan/README.md)
- **Power quality** pages on the site page: voltage per phase (mean, lowest and highest 15 s sample, one day minute by minute), dips and swells, unbalance, frequency, power factor and the kVArh PLN bills, against the limits of the alarm register: [`docs/LIVE.md`](docs/LIVE.md#option-a-in-detail) (Power quality pages)
- **Weather** on the site page: today's forecast hour by hour, tomorrow's forecast, and a log of the actual weather against the forecast and the outdoor sensor (Open-Meteo, no key): [`docs/WEATHER.md`](docs/WEATHER.md)
- **One server, one data folder:** where every piece of data is (live, records, alarms, weather) and how a second dashboard reads it at the same time: [`docs/DATA-ACCESS.md`](docs/DATA-ACCESS.md)
- **Archiving a test period** (Adab: everything before 17:00 WITA on 11 November 2026 was bench data), with `manage.py archive` from VPS `v0.8.1`: [`docs/ARCHIVE.md`](docs/ARCHIVE.md)
- Keeping RAM low on the VPS: [`docs/VPS-MEMORY.md`](docs/VPS-MEMORY.md)
- Hardware photos and original sketch: [`docs/img/`](docs/img/)
- **Logger firmware** (PlatformIO, ESP32-S3): [`firmware/`](firmware/). Functions and every setting: [`docs/FIRMWARE.md`](docs/FIRMWARE.md)
- **Firmware versions** page `/live/<site>/#versions`: what each logger runs, since when, every change and restart, the GitHub releases (read only, everyone)
- **Remote firmware update** per logger, from the site page (GitHub release, uploaded file or stored file): [`docs/OTA.md`](docs/OTA.md)
- **Meter register table** changed remotely from the page `/live/<site>/register`: [`docs/meter/README.md`](docs/meter/README.md#changing-the-register-table). Modbus meter simulator for practice and tests: [`tools/modbus_sim/`](tools/modbus_sim/)
- **Ingest service for the VPS** (Docker, Python standard library): [`server/`](server/). Setup: [`docs/VPS-SETUP.md`](docs/VPS-SETUP.md)
- How the data is saved (SD card and VPS, ready for OED): [`docs/DATA-FORMAT.md`](docs/DATA-FORMAT.md)
- Office preparation: build, flash, configure, bench tests: [`docs/OFFICE-PREP.md`](docs/OFFICE-PREP.md)
- Open questions to fine-tune the plan: [`docs/QUESTIONS.md`](docs/QUESTIONS.md)
- Installation and setup guide, written as a lab manual for engineering students, with schematics: [`docs/install/`](docs/install/)
