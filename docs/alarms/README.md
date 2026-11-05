# Alarm register

`alarms.csv` lists every alarm the platform checks. **Open it in Excel, change a line, save it as CSV**: the platform reloads it within a minute, so no code change is needed.

- The **`whatsapp`** column decides which alarms go to the WhatsApp group (`yes`) and which are only logged and shown on the status page (`no`).
- Every alarm, sent or not, is written to the site's `events.jsonl` and shown on the live/status page.

## Where the register lives

| Copy | Use |
|---|---|
| `docs/alarms/alarms.csv` (this repository, later `arkan-monitoring/config/alarms.csv`) | The default for every site |
| `/srv/arkan-monitoring/data/sites/<site>/alarms.csv` on the VPS | Optional, per site. A line with the same `id` replaces the default line for that site only (for example a different temperature limit, or WhatsApp off) |

## Columns

| Column | Meaning |
|---|---|
| `id` | A01, A02, ... Never reused once given |
| `name` | Short name, used in the WhatsApp message |
| `source` | Where the check runs: `meter` (meter values), `sensor` (temperature and humidity), `logger` (the logger's health), `platform` (the server's own checks) |
| `applies_to` | Which device the alarm is checked on, one alarm per device: a meter id (`EM01`), sensor ids (`TH1,TH2`), `logger` or `site`. A message names the device: "A11 Room hot (TH2, outside the box)". **For a different threshold per sensor**, split the line: keep A11 for `TH1` and add a new id (for example A22) for `TH2` with its own threshold |
| `condition`, `threshold`, `unit` | What raises the alarm |
| `delay_min` | How long the condition must last before the alarm starts (filters short spikes). 0 = at once |
| `clears_when` | What ends the alarm. The gap between the threshold and the clear value stops the alarm from flapping |
| `severity` | `critical`, `warning` or `info` |
| **`whatsapp`** | **`yes`: sent to the WhatsApp group through Hermes. `no`: logged and shown only** |
| `repeat_h` | Reminder every N hours while the alarm stays on. 0 = no reminder |
| `enabled` | `no` turns the check off completely |
| `note` | Why the threshold is what it is, what to check |

## What the WhatsApp group receives

Three messages per alarm at most, plus reminders:

```
[adab] CRITICAL A04 Phase lost
L2 at 0 V since 14:32 WITA (L1 231 V, L3 229 V)
https://arkan-monitoring.duckdns.org/live/adab/
```
```
[adab] CLEARED A04 Phase lost
All phases back at 14:51 WITA (19 min)
```

- **Master switch:** nothing is sent while `alerts.send` is off in the settings (the default, as in `arkan-solar-desk`). Turn it on once the thresholds have been checked over the first week.
- Times are WITA (Asia/Makassar).
- Several alarms starting within one minute are grouped into one message.
- Sent through the Hermes webhook route in direct delivery mode (no AI run, no cost per message). If Hermes refuses, the platform retries for 30 minutes, then logs the failure.

## Thresholds to confirm

- **A05, A06:** the PLN supply voltage at the hotel (230 V assumed) and the limits wanted.
- **A08:** the hotel's contracted kVA (`contracted_kva` in `site.json`).
- **A11, A12, A13:** the limits for the electrical room (`TH1`, the board's sensor).
- **A22 to A25:** the outdoor sensor (`TH2`, the AM2301 beside the panel room). Proposed 5 November 2026:
  - **A22 Outdoor very hot:** above 36 C for 30 min. Information only, no WhatsApp.
  - **A23 Condensation risk in the electrical room:** the outdoor dew point comes within 2 C of the room temperature for 30 min. Logged only at first; turn WhatsApp on if the room is air-conditioned.
  - **A24 Electrical room much warmer than outdoors:** room more than 8 C above outdoors for 30 min. **WhatsApp yes**: the most useful of the four, as it points to failed ventilation or cooling. Tune after the first week, once the `TH1` offset is set.
  - **A25 Outdoor sensor wet or stuck:** 99 % RH or more for 24 h. Information only.
- **A21:** off at adab (the two sensors are not in the same room).
- **A04 to A10** depend on the meter registers being verified (`docs/meter/README.md`).
