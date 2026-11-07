# How the data is saved: on the SD card and on the VPS

Status: **proposal, implemented in firmware 0.1.0 and the ingest service.** To confirm with the owner ([`QUESTIONS.md`](QUESTIONS.md) Q1 to Q4).

## 1. The choice: one file per day, all values of a logger in one row per minute

| Option | For | Against | Verdict |
|---|---|---|---|
| One big file | Simple | Grows without end; one corruption hits everything; slow to scan or copy; hard to resend a period | No |
| **One file per day (UTC), one row per minute, all values as columns** | A day = one file to read, copy, resend or delete. A corrupted file costs one day at most. Opens in Excel. 1,440 rows a day | Columns change if the configuration changes: handled by a `_2` file that day | **Chosen** |
| One file per sensor (or per value) | Matches OED's "one meter per value" | 25 files written every minute on the SD card (more wear, more FAT updates, more ways to fail at a power cut); the timestamp repeated 25 times; values of the same minute in different files | No for storage. **Produced on demand by the OED export** (section 5) |
| One file per month | Fewer files | 43,000 rows; a month lost on corruption; a month resent after a gap | No |
| A database (SQLite) on the logger | Queries | Fragile on power cuts on an SD card, more RAM and code | No |

**Why UTC days:** no daylight saving issue, same file names on the logger and the server whatever the site's timezone. WITA days (the "today" of the dashboards) are computed from UTC files by the server (`daily.csv`, OED).

## 2. Layout

**On the logger's SD card** (FAT32):
```
/data/2026/11/2026-11-07.csv       1-minute records of that UTC day
/data/2026/11/2026-11-07_2.csv     only if the columns changed that day
/log/2026-11.log                   event log of the month (text)
/state/upload.txt                  upload pointer: "20261107 1 48211" (day, part, bytes sent)
/config/registers.csv              optional: meter register table
/config/settings.txt               optional: settings to import (deleted once applied)
```

**On the VPS** (`/srv/arkan-monitoring/data/`, the dedicated folder, mounted at `/data` in the container):
```
devices.json                                   logger -> site, token hash, firmware
firmware/manifest.json, logger-x.y.z.bin       OTA
sites/adab/site.json                           site profile: name, timezone, labels, live values
sites/adab/LOG-0001/raw/2026/11/2026-11-07.csv same file as on the SD card (same name, same columns)
sites/adab/LOG-0001/events.jsonl               boots and their reason, firmware changes, column changes, backfills
sites/adab/daily.csv                           one row per WITA day (manage.py daily)
export/oed/adab/*.csv                          OED upload files (manage.py export-oed)
```
Backups: `/srv/arkan-monitoring/backups/data-<date>.tar.gz`, nightly, 14 kept (`server/deploy/backup.sh`).

**The SD card and the server hold the same files.** Recovering a gap = copying the SD card's `/data` folder and running `manage.py backfill adab LOG-0001 <copy>`: rows already on the server are dropped, the others are merged in time order.

## 3. The CSV file (schema 1)

Plain text, UTF-8, comma separated, `\n` line ends, a header line, no quotes, `.` as decimal point. Empty field = no valid reading.

| Column | Unit | Meaning |
|---|---|---|
| `ts` | UTC | Start of the minute, `2026-11-07T03:15:00Z`. Unique in a day: the key for duplicates |
| `EM01_v1` `_v2` `_v3` | V | Phase voltage L-N, mean of the minute |
| `EM01_v12` `_v23` `_v31` | V | Line voltage L-L |
| `EM01_i1` `_i2` `_i3` | A | Phase current |
| `EM01_f` | Hz | Frequency |
| `EM01_p1` `_p2` `_p3` | kW | Active power per phase |
| `EM01_p` | kW | Total active power, mean of the minute |
| `EM01_p_max` | kW | Highest 15 s total power in the minute |
| `EM01_q` | kvar | Total reactive power |
| `EM01_s` | kVA | Total apparent power |
| `EM01_pf` | | Power factor |
| `EM01_e` | kWh | **Cumulative** import energy counter of the meter, last reading of the minute |
| `EM01_eq` | kvarh | Cumulative reactive energy counter |
| `EM01_n` | | Number of good meter reads in the minute (4 = all) |
| `TH1_t` `TH1_rh` `TH1_n` | C, %RH | Electrical room (board sensor), offset applied |
| `TH2_t` `TH2_rh` `TH2_n` | C, %RH | Outdoor (AM2301), offset applied |
| `rssi` | dBm | WiFi signal (empty when offline) |
| `heap_kb` | kB | Free memory |
| `up_s` | s | Uptime |
| `backlog_min` | min | Age of the oldest record not yet uploaded |
| `boot` | | Reset reason, on the first record after a boot only |

A second meter adds the same block with `EM02_`. The meter columns and their scales come from the register table: **until the register check, the values and units of currents and powers are not trusted.**

Size: about 350 bytes a row, **0.5 MB a day, 180 MB a year per logger** (plain text; gzip in the backups divides it by about 5).

Example:
```
ts,EM01_v1,...,EM01_p,EM01_p_max,...,EM01_e,EM01_eq,EM01_n,TH1_t,TH1_rh,TH1_n,TH2_t,TH2_rh,TH2_n,rssi,heap_kb,up_s,backlog_min,boot
2026-11-07T03:15:00Z,231.25,...,28.445,29.867,...,184523.17,40210.32,4,31.37,60.4,4,29.09,76.5,4,-63,180,86400,0,
```

## 4. Upload (logger to VPS)

`POST /api/v1/ingest`, body = the file's header line + up to 60 rows, exactly as they are on the card. The server checks the header and every row (field count, timestamp format, not in the future, safe characters), stores the new rows, counts duplicates and bad rows, and answers:
```json
{"ok": true, "stored": 58, "duplicates": 2, "rejected_rows": 0, "last_ts": "2026-11-07T03:15:00Z"}
```
**Change from PLAN.md §5.2:** the plan proposed JSON records. CSV lines are sent instead because the logger then sends the bytes of its file as they are (less RAM, no conversion, identical files on both sides), and the server stores them as they are. The JSON live snapshot stays JSON. To confirm (Q1).

## 5. Ready for Open Energy Dashboard

The files are ready to load without change of format on our side:
- **Energy**: `EM01_e` is the meter's own cumulative counter. OED takes it as a meter with `cumulative=yes`, and computes kWh per interval and kW. Gaps and logger reboots do not corrupt totals; a meter reset shows as the counter going down (alarm A19).
- **Temperature and humidity**: raw readings per minute.
- `manage.py export-oed adab [--from 2026-11-01] [--to 2026-11-30] [--all]` writes **one file per value** in OED's CSV upload format (`reading,start_timestamp,end_timestamp`, **WITA local time** because OED stores times without a timezone):
  - `adab-EM01-energy.csv` (cumulative=yes), `adab-TH1-temp.csv`, `adab-TH1-hum.csv`, `adab-TH2-temp.csv`, `adab-TH2-hum.csv`;
  - with `--all`: every value (`adab-EM01-v1.csv`, `adab-EM01-p.csv`, ...).
- The automatic push to OED (every 5 minutes) is the next step, to be done once OED is installed (PLAN.md §5.3).

`daily.csv` (`manage.py daily adab`): one row per WITA day and logger: `minutes`, `coverage_pct`, `EM01_e_delta` (kWh of the day, from the previous day's last reading), `EM01_p_max` and its time, mean of every value, min/max/mean of temperature and humidity.
