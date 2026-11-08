# Questions to fine-tune the logger and the VPS

## Decisions of 7 November 2026 (owner)

| # | Question | Decision | Done in |
|---|---|---|---|
| | Sensors in the record | **1-minute average only** | firmware 0.2.0 (no sample count, no min/max for TH1, TH2) |
| | Alarm and warning log | **Add it**, with a recommended list | `docs/alarms/` (37 alarms, 34 enabled since the second round), VPS log `sites/<site>/alarms/<year>.csv` |
| Q1 | Upload format | **CSV** | done (PLAN.md §5.2 updated) |
| Q3 | Min and max per minute | **Yes, min and max: power quality analysis** | firmware 0.2.0: mean, `_min`, `_max` for every meter value |
| Q6 | Open Energy Monitoring = Open Energy Dashboard | **Yes, OED** | export format kept |
| Q7, Q8 | Daily reboot 03:05 WITA, reboot after 6 h offline | **Yes** | defaults kept |
| Q9 | 4G router | **No** | `wifi_ssid2` stays empty |
| Q10 | UPS | **Maybe later** | A32 "Mains lost (logger on UPS)" in the register, off until then |
| Q12 | Server code location | **Here until OED is installed**, then `arkan-monitoring` | |
| Q13 | OTA | **Yes, on from day one** | `ota_on` default 1 |
| Q14 | Remote settings | **Yes** | firmware 0.2.0 + `manage.py set-config` |
| Q15 | Setup WiFi password | **One per logger, in the password manager** | `manage.py add-device` makes one and puts it in the SD settings file |
| Q16 | Setup button | **Reachable through the closed box** | drill a small hole over BOOT in the box lid, label it (`docs/OFFICE-PREP.md` §4) |
| Q18 | Bench meter | **A spare meter is at the office**. **Revised 8 November: it has no Modbus port**, so it cannot be read | register check is back **on site** at the first visit (`docs/meter/README.md` section 4); the office T4 only tests wiring and A03 (`docs/OFFICE-PREP.md`) |

## Decisions of 7 November 2026, second round (owner)

| # | Question | Decision | Done in |
|---|---|---|---|
| | Sensors in the record | **5-minute average only** (saves space) | firmware 0.3.0: `TH*_t`, `TH*_rh` on the rows at :00, :05... (setting `th_avg_min`) |
| | Logger health | **Log when the firmware is updated** | A35 Firmware updated (old -> new, OTA or by hand), A36 Update rolled back; the boot column carries `reason@version` |
| Q23 | Supply | **PLN 3-phase** | 230/400 V nominal (SNI), contracts at 220/380 V: `nominal_v` 230, `contract_v_ln` 220 |
| Q24 | Contracted kVA | **82.5 kVA** | A08 at 74.25 kVA; new **A37** per-phase limit 3 x 125 A (warns at 112.5 A) |
| Q25 | Main breaker | **200 A** | A29 at 180 A |
| Q26 | CT ratio | **Set in the meter, which shows correct power and amps**; ratio to be noted. **Decided 8 November (owner): CTs are 250/5 A, ratio 50**, to be confirmed on the CT labels (`docs/meter/README.md` section 2) | `ct_mult` stays 1 until the **site** test; if the registers turn out to be secondary values, `ct_mult` = CT ratio (50 for 250/5) |
| Q27 | WhatsApp list | **OK** | as in `alarms.csv` |
| Q28 | Daily count of dips and swells | **Yes** | `daily.csv`: `dips`, `swells`, `power_interruptions`, `alarms_started` |

## Still open

| # | Question | Default now | Recommendation |
|---|---|---|---|
| Q2 | Day files in UTC (WITA days computed for `daily.csv` and OED) | UTC | Keep UTC |
| Q4 | Keep everything on the SD card, delete oldest uploaded days only at 95 % full | Forever | Keep |
| Q5 | No valid clock = no record | No record | Keep |
| Q11 | Live snapshot every 15 s (about 2 MB a day on the hotel WiFi) | On | Yes |
| Q17 | Who keeps the tokens and may run `manage.py add-device` | Owner | Owner only |
| Q19 | Small OLED on the I2C header (WiFi, last upload, kW) | None | Optional |
| Q20 | 2.4 GHz WiFi at the office for the bench | | |
| Q22 | WhatsApp alerts through Hermes in session S6 | Not built | Yes |
| **Q29** | **A37 (phase current near the PLN limit) to WhatsApp?** New since Q27; proposed yes, since a PLN limiter trip blacks out the hotel | yes | Yes |
| **Q30** | CT ratio value, for the as-built record (Q26) | **250/5** (owner, 8 November) | **Confirm on the label of each of the three CTs and photograph them**, then note CT1/CT2 from the meter menu, on site |
