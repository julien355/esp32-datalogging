# Archiving the test period of a site (VPS `v0.8.1`)

**Case of 11 November 2026:** everything `LOG-0001` recorded for `adab` **before 17:00 hotel time (WITA, UTC+8) on 11 November** is test data, from the bench. The live site data starts at 17:00, which is **09:00 UTC**. The test data must leave the site page, the alarm log and the daily file, but stay kept somewhere.

The records carry their own time, so the archive does not have to run at 17:00 exactly. It can run tonight or tomorrow: it moves the rows before 09:00 UTC and keeps every row from 09:00 UTC on. Until it runs, the site page shows the test data and the live data together.

## 1. What `manage.py archive` does

```
manage.py archive <site> --before "YYYY-MM-DD HH:MM" [--apply]
```

`--before` is in the site's local time (`timezone` in `site.json`: `Asia/Makassar` for `adab`). The command prints the same time in UTC. Without `--apply` it only says what it would do and changes nothing.

The archive goes to `/srv/arkan-monitoring/data/archive/<site>-before-<local time>/`, `/data/archive/...` in the container. Today that is `archive/adab-before-2026-11-11T1700/`. It has the same layout as the data folder, so the tools can read it, for example `manage.py --data /data/archive/adab-before-2026-11-11T1700 daily adab`. Its `README.txt` says what was moved and when. The nightly backup takes it with the rest of the data folder.

| Data | What happens |
|---|---|
| Records, `raw/` (1-minute rows) | Rows before the time are **moved** to the archive. The day files before 11 November move whole. The file of 11 November (a UTC day) is cut in two: rows before `09:00:00Z` go to the archive, rows from `09:00:00Z` stay |
| Live snapshots, `live/*.jsonl` (15 s) | The same, by the time the server received them (`recv`) |
| Alarm log, `alarms/2026.csv` | Lines before the time are **moved**, then the log is **rebuilt** from the records kept (`alarms --rebuild`). An offline or clock alarm that began before the time and is still open leaves the open alarms (its start line is in the archive). It opens again by itself if the logger is still offline |
| `daily.csv`, OED export files (`export/oed/<site>/`) | **Moved**. `daily.csv` is rebuilt from the records kept |
| `site.json` | Gets `"records_from": "2026-11-11T09:00:00Z"`. From then on the service **does not store an older row**: not from a logger's backlog, not from an SD card copy (`backfill`). The logger still gets `200` and moves on. The answer counts these rows in `before_start` |
| Logger events (`events.jsonl`), alarm state | **Copied** to the archive. The events stay on the site (the **Firmware versions** page), with one more line, `archive` |
| Settings, register table, devices, firmware, weather log (Open-Meteo, not from the logger) | Not touched |
| Open Energy Dashboard | Not installed on `hermes-vps`. Once it is, `export-oed` reads only the records kept |
| The logger's SD card | Not touched. The test files stay on the card, the original copy. Because of `records_from`, a later `backfill` from the card cannot bring them back |

**Safety.** With `--apply` the command refuses to run if the service answers (stop it first: two programs must not write the same day file). It also refuses a time in the future, and an archive that exists already.

## 2. Steps (11 November 2026)

**Where:** `ssh hermes-vps`, user ai. The owner approves the restarts (steps 1, 4 and 6). About 15 minutes.

### Step 1. Update the VPS to `v0.8.1`

The `archive` command comes with `v0.8.1`. Follow [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 2 with `<previous-tag>` = `v0.8.0` and `vX.Y.Z` = `v0.8.1`. Its 2.1 is the merge of the pull request and the tag `v0.8.1`, on the PC.

- **2.5:** expect no output: no `.env` change, no Caddy change.
- **2.7:** `/health` answers `"version": "0.8.1"`.

`v0.8.1` changes nothing on the page or for the logger. It only adds the `archive` command and the `records_from` check.

### Step 2. Backup

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**Expected:** `... backup ok: /srv/arkan-monitoring/backups/data-<date>.tar.gz (<size>)`. This is the copy of everything as it was before the archive.

### Step 3. See what it would do (changes nothing)

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose exec ingest python tools/manage.py archive adab --before "2026-11-11 17:00"
```

**Expected** (your numbers):

```
Archive of adab: every record before 2026-11-11 17:00 Asia/Makassar = 2026-11-11T09:00:00Z
Into: /data/archive/adab-before-2026-11-11T1700
  LOG-0001 records: 5320 row(s) moved (2026-11-07 to 2026-11-11), 4 day file(s) whole; 2026-11-11: 75 row(s) from 2026-11-11T09:00:00Z kept
  LOG-0001 live snapshots (15 s): 23040 moved
  alarm log: 41 line(s) moved, 2 kept, then rebuilt from the records kept
  sites/adab/daily.csv: moved, then rebuilt
  site.json: "records_from": "2026-11-11T09:00:00Z": older rows (a logger's backlog, an SD card backfill) are not stored again
  kept as they are: the logger events, settings and register table, the weather log, devices, firmware
Nothing was changed. Stop the service (docker compose stop ingest), then run again with --apply.
```

Check two things:
- the first line ends with **`= 2026-11-11T09:00:00Z`**;
- the `kept` count of 11 November is about the number of minutes from 17:00 WITA to now, the live data (at most 900: the UTC day of 11 November ends at 08:00 WITA on the 12th; later rows are in the next day's file and are not touched).

Not as expected: stop here. Nothing was changed.

### Step 4. Stop the service (owner approves)

```bash
docker compose stop ingest
```

**Expected:** `Container arkan-monitoring-ingest  Stopped`. The site page has no live data until step 6. The logger keeps its records on the SD card and sends them afterwards, so nothing is lost.

### Step 5. Archive

`exec` needs a running service, so this step uses `run --rm`, a one-off container with the same data folder:

```bash
docker compose run --rm ingest python tools/manage.py archive adab --before "2026-11-11 17:00" --apply
```

**Expected:** the same lines as in step 3, then:

```
alarm log rebuilt from the records kept: 2 line(s)
/data/sites/adab/daily.csv: 1 day(s); ...
Done. Archive: /data/archive/adab-before-2026-11-11T1700. Start the service again: docker compose start ingest
```

`error: the ingest service answers ...`: step 4 was not done. Nothing was changed.

### Step 6. Start the service (owner approves)

```bash
docker compose start ingest
```

### Step 7. Checks

```bash
docker compose exec ingest python tools/manage.py list
```

**Expected:** `adab: Adab hotel (Asia/Makassar), records from 2026-11-11T09:00:00Z (older ones archived)` and `LOG-0001: fw ..., last record <a few minutes ago>`.

```bash
docker compose logs --tail 20 ingest
```

**Expected:** the logger's `POST /api/v1/ingest` lines with `200`, within 2 minutes.

```bash
ls /srv/arkan-monitoring/data/archive/adab-before-2026-11-11T1700
```

**Expected:** `README.txt  devices.json  sites`.

In the browser, <https://arkan-monitoring.duckdns.org/live/adab/> (Ctrl+F5):
- **Power**, **From** 2026-11-11 **to** 2026-11-11, **Show**: the curve starts at 17:00;
- **From** 2026-11-10 **to** 2026-11-10: `No meter records for this period.`, and the **CSV** button is greyed out;
- **Open alarms** and the alarm log: nothing from before 17:00.

**Done when:** `list` shows `records from 2026-11-11T09:00:00Z`, and the page shows nothing before 17:00 on 11 November.

## 3. Going back

The test rows are not lost: they are in the archive and in the backup of step 2. To put them back on the site (service stopped, as in step 4):

1. Remove the line `"records_from": ...` from `/srv/arkan-monitoring/data/sites/adab/site.json` (`nano`, `sudo nano` if it is refused; the line before it then ends without a comma). Check the file:

```bash
python3 -m json.tool /srv/arkan-monitoring/data/sites/adab/site.json > /dev/null && echo ok
```

**Expected:** `ok`.

2. Merge the archived records back. Rows already on the site are dropped:

```bash
docker compose run --rm ingest python tools/manage.py backfill adab LOG-0001 /data/archive/adab-before-2026-11-11T1700/sites/adab/LOG-0001/raw
```

```bash
docker compose run --rm ingest python tools/manage.py alarms adab --rebuild
```

```bash
docker compose run --rm ingest python tools/manage.py daily adab
```

3. `docker compose start ingest`. Then move the archive folder aside, so the same archive can be made again later. The 15 s live snapshots stay in the archive: the site keeps only the last 7 days of them anyway.

## 4. Another site or another time

The same command, with that site's code and its local start time. For example, after a test week at a new site `villa`: `archive villa --before "2026-12-01 09:00"`. A second archive of the same site with a later time is fine. It makes a new folder, and `records_from` moves to the later time.
