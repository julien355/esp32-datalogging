# One server, one data folder: reading the data from a second dashboard

All the monitoring data is on **one VPS** (`hermes-vps`), in **one folder**, `/srv/arkan-monitoring/data`
(`/data` inside the container). One program writes it: the ingest service (`arkan-monitoring-ingest`).
The site page `/live/<site>/` and any other dashboard read the same data at the same time. Nothing is kept
only in the service's memory (since 0.5.0, the live snapshots are saved too).

## What is where

| Data | How often | File (in `sites/<site>/`) | Read it through the API |
|---|---|---|---|
| **Live** snapshot: kW, V, A, PF, Hz, temperatures, logger status, Modbus link of each meter (`sys.mb`, firmware 0.5.0) | every 15 s | `<device>/live.json` (the last one), `<device>/live/YYYY-MM-DD.jsonl` (all of a UTC day, 7 days kept) | `GET /api/v1/live/<site>` (last + 60 min + `meters`: the Modbus link of each meter, [`LIVE.md`](LIVE.md#meter-link-modbus-connection-state) + open alarms), `GET /api/v1/live/<site>/day/<YYYY-MM-DD>?device=` |
| **Records**: 1-minute meter and sensor values (mean, min, max) | every minute, sent in batches | `<device>/raw/YYYY/MM/YYYY-MM-DD.csv` (UTC day; `_2.csv` if the columns changed) | `GET /api/v1/records/<site>?from=YYYY-MM-DD&to=YYYY-MM-DD` (the day files that hold those hotel dates, as they are, in one CSV), `GET /api/v1/history/<site>?days=N` (per hotel hour), `GET /api/v1/history/<site>/day/<date>` (1-minute power), `GET /api/v1/quality/<site>?days=N` (power quality per hotel hour: voltage, frequency, power factor, kVArh, unbalance, dips, swells, with the limits and the power quality alarm lines), `GET /api/v1/quality/<site>/day/<date>` (1-minute voltage, frequency, power factor) |
| Energy per day | on demand | `daily.csv` (`manage.py daily`) | from the history API (`kwh` per hour) |
| **Alarms** | when they start and end | `alarms/YYYY.csv`, `<device>/alarm-state.json` | `GET /api/v1/alarms/<site>` |
| **Weather** forecast | every hour | `weather/forecast.json` | `GET /api/v1/weather/<site>` |
| **Weather log**: actual weather, day-ahead forecast | every hour, once a day | `weather/actual-YYYY.csv`, `weather/dayahead-YYYY.csv` | `GET /api/v1/weather/<site>/log?days=N` (`&format=csv`) |
| Site profile: name, time zone, labels, contract, position | by hand | `site.json` | in `GET /api/v1/live/<site>` (`profile`) |
| Loggers, firmware, last record | on each upload | `devices.json`, `<device>/events.jsonl`, `<device>/settings-reported.json` | `GET /api/v1/status` |

Every `?days=N` (the last N hotel days, today included) also takes `?from=YYYY-MM-DD&to=YYYY-MM-DD` instead: hotel dates, both included, at most 92 days.

Formats: [`DATA-FORMAT.md`](DATA-FORMAT.md) (records), [`LIVE.md`](LIVE.md) (live), [`WEATHER.md`](WEATHER.md) (weather),
[`alarms/README.md`](alarms/README.md) (alarms). Times: records and live in UTC (`ts`, `recv`); history, weather and the
alarm log's `local_time` in hotel time (WITA, UTC+8).

Not on the site: `archive/<site>-before-<local time>/`, a test period moved out with `manage.py archive` ([`ARCHIVE.md`](ARCHIVE.md)), in the same layout. The site's `site.json` then has `"records_from"` (UTC): the site has no record before it.

Not in this folder: Open Energy Dashboard's own database (another container on the same VPS, filled from the
records with `manage.py export-oed`), and the copy on each logger's SD card (the same record files, for recovery).

## How a second dashboard reads it

**Read only, never write.** Only the ingest service writes the folder. Settings go through the site page or `manage.py`.

### 1. Through the HTTP API (recommended)

The same JSON the site page uses: the API hides the file details, and the service serves many readers at once
(one thread per request; history and weather are summarised once and cached). Read endpoints are `GET` only and
listed in the table above, and at the top of [`server/app/server.py`](../server/app/server.py).

| Where the second dashboard runs | Address | Login |
|---|---|---|
| In a container on the VPS | `http://arkan-monitoring-ingest:8800`, with the container in the Docker network `arkan-monitoring` (in its compose file: `networks: {default: {name: arkan-monitoring, external: true}}`) | none: this network is not reachable from the internet |
| On the VPS, outside Docker | `http://127.0.0.1:8800` | none (loopback only) |
| Anywhere else | `https://arkan-monitoring.duckdns.org/api/v1/...` | a login of its own in `/opt/edge/secrets/hub-users.caddy` (HTTP basic auth), so it can be removed alone |

- Live data changes every 15 s: ask `/api/v1/live/<site>` at most every 15 s. History and weather change every few minutes to every hour: every 5 minutes is plenty.
- A dashboard running in the browser on **another domain** cannot call the API directly (no CORS, and the login is per domain): put it behind the same Caddy site (a path such as `/dash2/`), or have its server call the API.
- Never give a dashboard the `/api/v1/admin/*` paths (firmware, register table): they change the loggers.

### 2. From the files (read-only mount)

For a tool that wants the raw files (for example a database loader), mount the folder **read-only**:

```yaml
volumes:
  - /srv/arkan-monitoring/data:/data:ro
```

Rules for a reader of the files while the service writes them:
- `.json` files are replaced whole (written to a temporary file, then renamed): read them at any time.
- `.csv` and `.jsonl` files grow at the end: **skip a last line that does not end with a newline**, it is still being written.
- A record day file can be rewritten whole when old rows arrive late (backfill, in time order): open it again at each read, do not keep it open.
- A new `_2.csv` part appears the day the logger's columns change: read every part of a day.
- Live day files older than 7 days are deleted (`LIVE_KEEP_DAYS` in `server/.env`).

## Space and memory

- Live snapshots: about 550 bytes each, 3 MB a day per logger, about 22 MB for the 7 days kept.
- Records: about 0.6 MB a day per logger (1440 rows). Weather: under 1 MB a year per site.
- The nightly backup (`server/deploy/backup.sh`) takes the whole folder, live and weather files included.
- Saving the live snapshots adds no memory; reading them back at a restart takes the same few kB as before.
