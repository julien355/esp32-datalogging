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
- Hardware theory, wiring drawings and lab sheets: [`../install/README.md`](../install/README.md)
- Decisions and open questions: [`../QUESTIONS.md`](../QUESTIONS.md), plan: [`../PLAN.md`](../PLAN.md)

## Status (7 November 2026)
The firmware (0.3.0) and the ingest service are written and tested by CI and with a simulated logger, **not yet on the real board**. The board's RS485 pins and the meter register map are **to verify** on the bench (tutorial 1, part A). Open Energy Dashboard is **not installed yet**: tutorial 3 and its deploy files in [`../../server/deploy/oed/`](../../server/deploy/oed/) are drafts to test.
