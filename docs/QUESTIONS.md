# Questions to fine-tune the logger and the VPS (7 November 2026)

Each question has the **current default** (what the code does today) and a recommendation. Answer by number; a "yes" keeps the default. Settings marked *(setting)* can be changed later without new firmware.

## A. Data and storage

| # | Question | Default now | Recommendation |
|---|---|---|---|
| Q1 | **Upload format.** PLAN.md §5.2 planned JSON records. The code sends the CSV lines of the day file as they are (same bytes on the card and the server, less RAM). OK to change the contract to CSV? | CSV | Yes, CSV |
| Q2 | **Files per UTC day** on the card and the VPS (WITA days are computed for `daily.csv` and OED). Or do you want WITA day files (`2026-11-07.csv` = 00:00 to 24:00 WITA)? | UTC days | UTC: no ambiguity, same on every site |
| Q3 | **What the minute record keeps.** Mean of the 15 s samples, plus max kW, plus last kWh counter. Do you also want the **minimum voltage** per phase in each minute (shows short dips) and the **max current** per phase? Adds 6 columns | Not kept | Yes for V min if power quality matters to the hotel |
| Q4 | **Keep data on the SD card forever** (a 16 GB card holds decades) and delete the oldest uploaded days only when the card is 95 % full. Or delete after N days? | Forever *(setting `sd_min_free`)* | Forever |
| Q5 | **No valid clock = no record.** Only possible with a dead coin cell and no internet. Or record anyway with a "clock unknown" flag? | No record | Keep: a wrong timestamp is worse than a gap |
| Q6 | **Open Energy Monitoring:** do you mean **Open Energy Dashboard (OED)**, chosen on 30 October (PLAN.md §4.2), or **OpenEnergyMonitor / Emoncms** (a different product)? The files fit both; the export written today is in OED's format | OED | Confirm OED |

## B. Robustness

| # | Question | Default now | Recommendation |
|---|---|---|---|
| Q7 | **Daily reboot** at 03:05 WITA (19:05 UTC). Costs 2 of the 4 samples of one minute a day. Keep it, move it, or switch it off? | On, 03:05 WITA *(setting `reboot_hr`)* | Keep for the trial; switch off later if the logs show it is never needed |
| Q8 | **Reboot after 6 h without WiFi.** | 6 h *(setting `offline_rbt_h`)* | Keep |
| Q9 | **Backup network:** is there a 4G router (or a second hotel network) the logger can fall back to? | None *(setting `wifi_ssid2`)* | A cheap 4G router only if the RSSI survey is poor |
| Q10 | **UPS:** none for the trial (PLAN.md §3, Q9). A small 5 V power bank with pass-through (or a mini UPS) would let the logger record the outage itself instead of showing a gap. Worth adding? | None | Optional; useful because outages are one of the things we want to see |

## C. Network and remote management

| # | Question | Default now | Recommendation |
|---|---|---|---|
| Q11 | **Live snapshot every 15 s** to the VPS, about 2 MB a day on the hotel WiFi. OK with the hotel? | On *(setting `live_on`)* | Yes |
| Q12 | **Where the server code lives.** `arkan-monitoring` does not exist yet, so the ingest service is in `server/` of this repository. Do you create the empty private repository `arkan-monitoring` now so we move it there, or keep it here until OED is added? | Here | Create `arkan-monitoring` when OED is installed; keep it here until then |
| Q13 | **OTA updates from the VPS:** switch them on from day one? Without OTA, any fix needs a trip to the hotel with a laptop | Off *(setting `ota_on`)* | On, once T12 has passed on the bench |
| Q14 | **Remote settings** (change an offset or the meter address from the VPS without a visit) are not built yet. Needed for the trial? | Not built | Yes, small addition (next session, S6) |

## D. Access and security

| # | Question | Default now | Recommendation |
|---|---|---|---|
| Q15 | **Setup WiFi password** (`ARKAN-LOG-0001`): who knows it? One shared Arkan password, or one per logger? | `arkan-setup` (change it) | One per logger, kept in the password manager with the token |
| Q16 | **Setup button:** the BOOT button opens the portal (3 s). It must be reachable with the box closed (a small hole) or the box opened? Or no button at all on site (portal only from the console)? | BOOT, 3 s | Reachable through the closed box: lets someone fix the WiFi on site without a laptop |
| Q17 | **Device token:** who keeps it (password manager), and who may run `manage.py add-device` on the VPS? | Owner | Owner only |

## E. Office preparation and site

| # | Question | Default now | Recommendation |
|---|---|---|---|
| Q18 | **Meter for the bench:** buy a spare FCN300 (or any Modbus meter), use a Modbus simulator on a laptop, or do the register check at the hotel during a first visit? | Check at the hotel | A spare meter: it also serves the next sites |
| Q19 | **Status LED / small OLED:** the board has an I2C (OLED) header. A 0.96" OLED showing WiFi, last upload and kW helps on site. Add it? | None *(setting `pin_led`)* | Optional, cheap |
| Q20 | **Office WiFi for the bench test:** 2.4 GHz available? (the ESP32-S3 has no 5 GHz) | | |
| Q21 | **Sampling:** meter and sensors every 15 s (PLAN.md §3, Q13 said T/RH every 60 s; reading them every 15 s costs nothing and feeds the live page). OK? | 15 s *(setting `sample_s`)* | Yes |
| Q22 | **Alerts (WhatsApp through Hermes)** stay for session S6, after the bench and VPS tests. OK? | Not built | Yes |
