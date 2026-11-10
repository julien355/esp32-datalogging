# Tutorials: setting up each part, step by step

Four tutorials written for beginners: every term explained, where every thing is, which tool, every command, and what you should see after each step.

| # | Tutorial | For | Where it happens | Do it |
|---|---|---|---|---|
| 1 | [**The logger on site**](1-LOGGER-ON-SITE.md) | Technicians and students, with a supervisor and an electrician | Office bench, then the Adab hotel | After the VPS (tutorial 2) is running, so the logger has somewhere to send |
| 2 | [**The VPS setup**](2-VPS-SETUP.md) | The operator, with the owner for the `sudo` steps | Laptop (Windows, PowerShell) and `hermes-vps` over SSH | First |
| 3 | [**Open Energy Dashboard**](3-OPEN-ENERGY-DASHBOARD.md) | The operator, with the owner | Laptop and `hermes-vps` | After tutorial 2; any time before or after the site install (data is kept and can be loaded later) |
| 4 | [**Modbus registers: read, change and test**](4-MODBUS-REGISTERS.md) | Technicians and students, with the supervisor | Laptop (no hardware needed for Part 3), office bench, then the hotel | Before the first site visit: it prepares the register check on the real meter. Needs nothing from tutorials 2 and 3 |

## Order of work

```
 2. VPS setup  ──>  1A. logger at the office (bench tests; the spare meter has no Modbus port)  ──>  1B. logger on site
      │
      └──>  3. Open Energy Dashboard (history graphs; the live page /live/ works without it)

 4. Modbus registers (practise with the simulator on the laptop)  ──>  before the register check on site (1B)
```

## Where the reference documents are
- What the logger does and all its settings: [`../FIRMWARE.md`](../FIRMWARE.md)
- The data files: [`../DATA-FORMAT.md`](../DATA-FORMAT.md)
- The alarms and the alarm log: [`../alarms/README.md`](../alarms/README.md)
- The full bench test list: [`../OFFICE-PREP.md`](../OFFICE-PREP.md)
- The short VPS guide: [`../VPS-SETUP.md`](../VPS-SETUP.md)
- The site page (live, history, registers, firmware update): [`../LIVE.md`](../LIVE.md); remote firmware update: [`../OTA.md`](../OTA.md)
- Hardware theory, wiring drawings and lab sheets: [`../install/README.md`](../install/README.md)
- Decisions and open questions: [`../QUESTIONS.md`](../QUESTIONS.md), plan: [`../PLAN.md`](../PLAN.md)

## Updating
New version of the VPS code or of the firmware: [`../HOW-TO-UPDATE.md`](../HOW-TO-UPDATE.md), the same steps for every release (the VPS from its terminal, the logger by cable from VS Code and PlatformIO, or over the air from a GitHub release). What each release needs on top: [`../UPDATING.md`](../UPDATING.md).

## Status (10 November 2026)
The firmware and the ingest service (site page with history, power quality, meter register page, firmware update from the web) are written and tested by CI and with a simulated logger. The bench board `LOG-0001` runs firmware 0.4.1 (release `fw-v0.4.1`), online and uploading to the platform; it ran 1 h 45 min on the bench without a restart on 10 November. Do not use 0.4.0 (withdrawn: [`../UPDATING.md`](../UPDATING.md) section 5). The VPS ran `v0.6.0` on 10 November; next come `v0.7.1` (logins limited to one site) and `v0.8.0` (the Modbus link of each meter, history pages with two dates and a CSV): [`../UPDATING.md`](../UPDATING.md) sections L and M. Then firmware 0.5.1, which contains 0.5.0 (the Modbus link) and adds two WiFi networks of equal rank: section W. The order, step by step: [`../CHECK-UP-TO-DATE.md`](../CHECK-UP-TO-DATE.md#7-general-update-to-do-now-in-order-10-november-2026) section 7. The board's RS485 pins are **to verify** on the bench (tutorial 1, part A); the meter register map is verified **on site** (the spare meter has no Modbus port), after practice with the simulator (tutorial 4). Open Energy Dashboard is **not installed yet**: tutorial 3 and its deploy files in [`../../server/deploy/oed/`](../../server/deploy/oed/) were tested on a test machine, not yet on `hermes-vps`.
