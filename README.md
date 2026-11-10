# esp32-datalogging

Energy and environment datalogger built on a Bluino ESP32-S3 (T/RH, RS485, RTC, analog inputs) board plus an AM2301 temp/RH sensor,
reading a FORT FCN300 (3E4Y or 3EH4Y, same registers) meter over Modbus RTU. Pilot site: **adab**.

- Plan and work split: [`docs/PLAN.md`](docs/PLAN.md). The monitoring platform (ingest, dashboards, per-site data folders) lives in its own repository, `arkan-monitoring`.
- What is reused from existing repositories and open-source projects: [`docs/REUSE.md`](docs/REUSE.md)
- Meter register map and what must be verified: [`docs/meter/`](docs/meter/)
- Alarm register and the alarm and warning log (which alarms are recorded, which go to WhatsApp): [`docs/alarms/`](docs/alarms/)
- **Step-by-step tutorials** (logger on site, VPS, Open Energy Dashboard, Modbus registers): [`docs/tutorials/`](docs/tutorials/)
- **Updating the VPS and the loggers** (and what the 10 November 2026 release, `v0.6.0`, needs): [`docs/UPDATING.md`](docs/UPDATING.md)
- Site page `/live/<site>/`: live data every 15 s, history pages, meter register page, firmware update: [`docs/LIVE.md`](docs/LIVE.md). Design mockup: [`docs/mockup/`](docs/mockup/)
- **Power quality** pages on the site page: voltage per phase (mean, lowest and highest 15 s sample, one day minute by minute), dips and swells, unbalance, frequency, power factor and the kVArh PLN bills, against the limits of the alarm register: [`docs/LIVE.md`](docs/LIVE.md#option-a-in-detail) (Power quality pages)
- **Weather** on the site page: today's forecast hour by hour, tomorrow's forecast, and a log of the actual weather against the forecast and the outdoor sensor (Open-Meteo, no key): [`docs/WEATHER.md`](docs/WEATHER.md)
- **One server, one data folder:** where every piece of data is (live, records, alarms, weather) and how a second dashboard reads it at the same time: [`docs/DATA-ACCESS.md`](docs/DATA-ACCESS.md)
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
