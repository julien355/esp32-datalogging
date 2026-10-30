# esp32-datalogging

Energy and environment datalogger built on a Bluino ESP32-S3 (T/RH, RS485, RTC, analog inputs) board,
reading a FORT FCN300-3E4Y meter over Modbus RTU. Pilot site: **adab**.

- Plan and work split: [`docs/PLAN.md`](docs/PLAN.md). The monitoring platform (ingest, dashboards, per-site data folders) lives in its own repository, `arkan-monitoring`.
- What is reused from existing repositories and open-source projects: [`docs/REUSE.md`](docs/REUSE.md)
- Meter register map and what must be verified: [`docs/meter/`](docs/meter/)
- Hardware photos and original sketch: [`docs/img/`](docs/img/)
