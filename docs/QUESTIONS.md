# Questions to fine-tune the logger and the VPS

## Decisions of 7 November 2026 (owner)

| # | Question | Decision | Done in |
|---|---|---|---|
| | Sensors in the record | **1-minute average only** | firmware 0.2.0 (no sample count, no min/max for TH1, TH2) |
| | Alarm and warning log | **Add it**, with a recommended list | `docs/alarms/` (34 alarms, 31 enabled), VPS log `sites/<site>/alarms/<year>.csv` |
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
| Q18 | Bench meter | **A spare meter is at the office** | register check moves to the office (`docs/OFFICE-PREP.md` T4) |

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
| **Q23** | **Supply voltage** at the hotel: 230 V L-N? | 230 V | Confirm: sets A05, A06, A26, A27 |
| **Q24** | **Contracted kVA** of the hotel (PLN bill) | not set | Needed for A08 High demand |
| **Q25** | **Rated current** of the main breaker (or the CTs) in A | not set | Needed for A29 Phase current near the rating |
| **Q26** | **CT ratio** of the meter (on its label or menu) | | Needed to check the current and power scales (T4) |
| **Q27** | Alarms going to WhatsApp: the proposal is in the `whatsapp` column of `docs/alarms/alarms.csv` (12 enabled alarms: A01, A03 to A08, A11, A12, A24, A29, A34; A32 too once the UPS is in). Add or remove any? | as listed | Start with these; review after the first week |
| **Q28** | Power quality alarms A26 (dip) and A27 (swell) are logged as info only. Do you also want a **daily count of dips and swells** in `daily.csv`? | No | Yes if the hotel has complaints about equipment trips |
