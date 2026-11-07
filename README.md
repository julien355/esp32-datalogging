# esp32-datalogging

Energy and environment datalogger built on a Bluino ESP32-S3 (T/RH, RS485, RTC, analog inputs) board plus an AM2301 temp/RH sensor,
reading a FORT FCN300 (3E4Y or 3EH4Y, same registers) meter over Modbus RTU. Pilot site: **adab**.

- Plan and work split: [`docs/PLAN.md`](docs/PLAN.md). The monitoring platform (ingest, dashboards, per-site data folders) lives in its own repository, `arkan-monitoring`.
- What is reused from existing repositories and open-source projects: [`docs/REUSE.md`](docs/REUSE.md)
- Meter register map and what must be verified: [`docs/meter/`](docs/meter/)
- Alarm register (which alarms go to WhatsApp): [`docs/alarms/alarms.csv`](docs/alarms/alarms.csv)
- Live data every 15 s: [`docs/LIVE.md`](docs/LIVE.md)
- Keeping RAM low on the VPS: [`docs/VPS-MEMORY.md`](docs/VPS-MEMORY.md)
- Hardware photos and original sketch: [`docs/img/`](docs/img/)
- **Logger firmware** (PlatformIO, ESP32-S3): [`firmware/`](firmware/). Functions and every setting: [`docs/FIRMWARE.md`](docs/FIRMWARE.md)
- **Ingest service for the VPS** (Docker, Python standard library): [`server/`](server/). Setup: [`docs/VPS-SETUP.md`](docs/VPS-SETUP.md)
- How the data is saved (SD card and VPS, ready for OED): [`docs/DATA-FORMAT.md`](docs/DATA-FORMAT.md)
- Office preparation: build, flash, configure, bench tests: [`docs/OFFICE-PREP.md`](docs/OFFICE-PREP.md)
- Open questions to fine-tune the plan: [`docs/QUESTIONS.md`](docs/QUESTIONS.md)
- Installation and setup guide, written as a lab manual for engineering students, with schematics: [`docs/install/`](docs/install/)
