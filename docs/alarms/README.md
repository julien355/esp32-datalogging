# Alarm register and alarm log

Two files:
- **The register** `alarms.csv`: which alarms and warnings exist, their thresholds, delays, severity, and which go to WhatsApp. **Open it in Excel, change a line, save it as CSV**: the platform reads it again at the next record, with no code change and no restart.
- **The log** (the alarm and warning register log) on the VPS: one line each time an alarm **starts**, **clears**, or an **event** happens. Built by the ingest service (`server/app/alarms.py`) since firmware 0.2.0.

Status: **built and tested with the simulated logger** (7 November 2026). WhatsApp sending through Hermes comes in session S6; the `whatsapp` column is ready for it.

## 1. How it works

- Every 1-minute record is checked against every enabled line of the register, **in time order**, including the backlog sent after an outage. An alarm's time is **the minute the condition began in the data**, not the moment the data reached the VPS.
- Power quality alarms use the **min and max of the 15 s samples** in each minute (logger 0.2.0), so a short dip shows even when the minute's mean looks normal.
- **Delay:** the condition must hold for `delay_min` consecutive minutes before the alarm starts (0 or 1 = at once). A gap of more than 5 minutes in the data restarts the count.
- **Hysteresis:** the alarm clears only past `clear_at` (for example undervoltage starts below 207 V and clears above 210 V), so it does not flap.
- **Events** (power interruption, crash, counter backwards) are single lines, no start or clear.
- Two checks do not come from the records:
  - **A01 logger offline** is checked every minute on what the VPS **receives**;
  - **A18 clock** is checked on the live snapshots.
- Nothing is lost by evaluating on the VPS: the logger keeps every record on its SD card, and **`manage.py alarms adab --rebuild` replays the whole history** against the current register (after an SD backfill, or to see what a new threshold would have given).

## 2. Where the files are

| File | Use |
|---|---|
| `docs/alarms/alarms.csv` (this repository) | The default register, built into the server image |
| `/srv/arkan-monitoring/data/alarm-register.csv` | **The register in use on the VPS** (copied by `manage.py init`). Edit this one |
| `/srv/arkan-monitoring/data/sites/<site>/alarm-register.csv` | Optional, per site: a line with the same `id` replaces the line for that site only |
| `/srv/arkan-monitoring/data/sites/<site>/alarms/2026.csv` | **The log** of the site, one file per year |
| `/srv/arkan-monitoring/data/sites/<site>/<logger>/alarm-state.json` | Open alarms and pending delays (internal) |

Read the log:
- in Excel, from the file;
- on the live page `/live/adab/`, which shows the open alarms at the top and the last 20 log lines at the bottom;
- `docker compose exec ingest python tools/manage.py alarms adab`;
- `GET /api/v1/alarms/adab` (JSON, with the Arkan login).

## 3. Log columns

| Column | Meaning |
|---|---|
| `ts_utc` | When the condition began (start), ended (clear) or happened (event), from the records |
| `local_time` | Same, in WITA |
| `device` | Logger code |
| `id`, `name`, `severity` | From the register |
| `state` | `start`, `clear` or `event` |
| `value` | Worst value during the alarm (lowest voltage, highest temperature...) |
| `threshold`, `unit` | From the register |
| `duration_min` | On `clear`: how long it lasted |
| `message` | Plain text, for example "cleared after 6 min; worst value 180", "no records from ... for 42 min: outage about 42 min" |

## 4. Register columns

| Column | Meaning |
|---|---|
| `id` | A01, A02, ... Never reused once given |
| `name` | Short name, used in the WhatsApp message |
| `group` | `power quality`, `load`, `meter`, `environment`, `logger`, `platform` |
| `rule` | The check the code runs (do not change unless you know the list in `server/app/alarms.py`) |
| `applies_to` | A meter (`EM01`), sensors (`TH1`, `TH1,TH2`: the first is the room, the second the outdoor sensor) or `logger` |
| `threshold`, `clear_at`, `unit` | Starts past `threshold`, clears past `clear_at` |
| `delay_min` | Minutes the condition must last |
| `severity` | `critical`, `warning` or `info` |
| **`whatsapp`** | **`yes`: will be sent to the WhatsApp group (S6). `no`: logged and shown only** |
| `repeat_h` | WhatsApp reminder every N hours while it stays on (S6) |
| `enabled` | `no` turns the check off |
| `evaluated_on` | `1-min record`, `live snapshot` or `reception` |
| `condition`, `note` | Plain text: what it means, what to check |

## 5. The alarms and warnings recommended for recording (34 lines, 31 enabled)

**Power quality (from the 1-minute mean, min and max)**

| Id | Name | Starts when | Sev. | WhatsApp |
|---|---|---|---|---|
| A04 | Phase lost | lowest 15 s phase voltage < 100 V | critical | yes |
| A05 | Undervoltage | a phase mean < 207 V (-10 %) for 5 min | warning | yes |
| A06 | Overvoltage | a phase mean > 242 V (+5 %) for 5 min | warning | yes |
| A26 | **Voltage dip** (new) | a 15 s sample < 207 V | info | no |
| A27 | **Voltage swell** (new) | a 15 s sample > 253 V (+10 %) | info | no |
| A28 | **Voltage unbalance** (new) | > 2 % for 10 min (EN 50160 limit) | warning | no |
| A07 | Frequency out of range | min or max more than 0.5 Hz from 50 Hz (genset) | warning | yes |
| A09 | Low power factor | < 0.85 for 15 min, load above 1 kW | warning | no |
| A10 | Current imbalance | > 20 % for 15 min, mean above 5 A | warning | no |
| A32 | Mains lost, logger on UPS | **off until the UPS is installed** (needs a mains-sense signal) | critical | yes |

**Load and meter**

| Id | Name | Starts when | Sev. | WhatsApp |
|---|---|---|---|---|
| A08 | High demand | kVA max > 90 % of contracted kVA for 5 min (needs `contracted_kva`) | warning | yes |
| A29 | **Phase current near the rating** (new) | I max > 90 % of `rated_a` for 5 min (needs `rated_a`) | warning | yes |
| A03 | Meter not answering | no good read in a whole minute | critical | yes |
| A30 | **Negative power on a phase** (new) | phase kW < -0.5 for 5 min: CT backwards or on the wrong phase | warning | no |
| A31 | **Energy counter not moving** (new) | kWh unchanged 30 min while load > 1 kW: wrong register | warning | no |
| A19 | Energy counter went backwards | event | warning | no |

**Environment**: A11 room hot (35 C), A12 room very hot (40 C), A13 room humid (80 %), A22 outdoor very hot, A23 condensation risk, A24 room much warmer than outdoors (WhatsApp), A25 outdoor sensor wet; A21 off at adab.

**Logger health**

| Id | Name | Starts when | Sev. | WhatsApp |
|---|---|---|---|---|
| A01 | Logger offline | nothing received for 15 min | critical | yes |
| A02 | Power interruption | event: boot after power loss, with the outage length from the gap | info | no |
| A33 | **Logger crash restart** (new) | event: boot by watchdog or crash | warning | no |
| A34 | **Frequent restarts** (new) | event: 3 unplanned restarts within 24 h | warning | yes |
| A14 | Temp/RH sensor fault | no valid reading for 10 min | warning | no |
| A15 | SD card error | records from the RAM queue | warning | no |
| A16 | Backlog growing | backlog > 60 min **while WiFi is up** (uploads failing) | warning | no |
| A17 | Weak WiFi | < -80 dBm for 60 min | info | no |
| A18 | Clock wrong | logger clock more than 2 min off (live snapshots) | warning | no |
| A20 | Push to OED failing | off until the push to OED exists | warning | no |

Also kept in `events.jsonl`, not in the alarm log because they are not faults: firmware changed, settings sent and applied, logger added, backfill, columns changed.

## 6. Thresholds to confirm
- **A05, A06, A26, A27:** 230 V nominal assumed; SPLN tolerance +5 % / -10 %. Confirm with the PLN supply at the hotel.
- **A08:** the hotel's contracted kVA → `contracted_kva` in `site.json`. Until then A08 never starts.
- **A29:** main breaker or CT rating in A → `rated_a` in `site.json`. Until then A29 never starts.
- **A11, A12, A13** (electrical room), **A22 to A25** (outdoor): as proposed on 5 November.
- **A04 to A10, A26 to A31** depend on the meter register check (spare meter at the office, `docs/OFFICE-PREP.md` T4).
- Review the log after the first week and tune: a line that fires every day is noise; raise its threshold or delay, or set WhatsApp to `no`.

## 7. What the WhatsApp group will receive (S6)

```
[adab] CRITICAL A04 Phase lost
L2 at 0 V since 14:32 WITA (L1 231 V, L3 229 V)
https://arkan-monitoring.duckdns.org/live/adab/
```
```
[adab] CLEARED A04 Phase lost
All phases back at 14:51 WITA (19 min)
```
- Master switch `alerts.send` off until the thresholds have been checked over the first week.
- Several alarms starting within one minute grouped into one message; reminders every `repeat_h`.
- Through the Hermes webhook route in direct delivery mode (no AI run, no cost per message).
