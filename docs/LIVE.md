# Live data every 15 seconds

## The limit in OED

OED is not built for live data:
- Readings enter only through CSV uploads.
- Graphs load when a person opens or redraws them, with no auto refresh.
- The hourly and daily views are refreshed by scheduled jobs.

There is also **no plugin system** to add a live widget without changing OED's code.

## Options

| Option | How | Verdict |
|---|---|---|
| **A. Live page beside OED** | The logger sends a small snapshot every 15 s; the ingest service keeps it in memory and serves a live page at `/live/<site>/` that refreshes every 15 s. Same login as OED. OED stays unchanged for history | **Recommended.** No change to OED, very little RAM, nothing written to disk every 15 s |
| B. Push 15-second readings into OED | Upload every 15 s instead of every 5 min | OED still shows them only on redraw, and stores 4x more rows in PostgreSQL (more RAM and disk). Not live |
| C. Add a "Live" page inside OED | Change OED's React client and server to add a live view | A fork to keep up with OED's updates; MPL-2.0 requires publishing the changed files. Possible later, or proposed to the OED project |

## Option A in detail

**Which values are live** is a list per site in `site.json`, so it can change without code:

```json
"live": {
  "refresh_s": 15,
  "values": ["EM01_p", "EM01_s", "EM01_pf", "EM01_f", "EM01_v1", "EM01_v2", "EM01_v3",
             "EM01_i1", "EM01_i2", "EM01_i3", "TH1_t", "TH1_rh", "TH2_t", "TH2_rh"]
}
```

Default for Adab:
- total kW and kVA, power factor, frequency;
- voltage and current per phase;
- temperature and humidity of the electrical room (`TH1`, on the board) and outdoors (`TH2`, the AM2301), with the room-minus-outdoor difference and the outdoor dew point;
- logger status (online, last seen, WiFi signal).

**Logger:**
- Every 15 s, after reading the meter, it POSTs the snapshot to `/api/v1/live` (about 300 bytes, on a kept-open HTTPS connection).
- The snapshot is **not** written to the SD card and not resent if lost: the next one replaces it 15 s later.
- The 1-minute records go on as before, through the SD queue to `/api/v1/ingest`. **History stays complete; only live is best effort.**
- Data use: about 2 MB a day on the hotel WiFi.

**Ingest service:**
- Keeps the last snapshot and the **last 60 minutes** (240 points) per site in memory for the page: a few kB per site.
- **Since 0.5.0 every snapshot is also saved** in the data folder, so a second dashboard reads the same live data ([`DATA-ACCESS.md`](DATA-ACCESS.md)): `sites/<site>/<device>/live.json` (the last snapshot) and `live/YYYY-MM-DD.jsonl` (every snapshot of the UTC day, kept 7 days, `LIVE_KEEP_DAYS`). About 3 MB a day per logger (22 MB for 7 days); `LIVE_KEEP_DAYS=0` goes back to memory only.
- Serves `/api/v1/live/<site>` (JSON) and the page `/live/<site>/`.
- After a restart or an update the 60 minutes are read back from the saved snapshots: the page is full at once.
- The live alarms (A04 phase lost, A07 frequency) are checked on the snapshots, so they react within 15 to 30 s.

**Live page `/live/<site>/`** (content of the dashboard mockup approved 8 November 2026; since service 0.7.0 in the Arkan design of the CMMS, `docs/mockup/arkan/`):
- A side bar: the Arkan logo, the site (a link to **All sites**, except for a login limited to its sites: [Logins](#logins)), **View as** (who is logged in: `Admin · <login>` for a login in `ADMIN_USERS`, `Viewer · <login>` otherwise; an admin can look at the pages as a viewer), the menu, and at the bottom **Settings** (`#prefs`: light, dark or high contrast, density, text size, motion, saved in the browser; who is logged in; the site details) with the status pill ("Live · updated 4 s ago", or "No data for 2 min" in red). An icon rail on a tablet, bottom tabs and a **More** list on a phone.
- Every chart shows both axes with their scales; the small charts of the cards cover the last 60 minutes.
- The open alarms first (severity icon, label and colour), or "No open alarm".
- **Power:** total kW, kVA with a bar against the PLN contract (`contracted_kva`), power factor, frequency.
- **Per phase:** one card for the three voltages and one for the three currents, each with a 3-line sparkline (L1 blue, L2 orange, L3 green); the current card has a bar against the PLN per-phase limit (`contracted_kva` / 3 / `contract_v_ln`, 125 A at Adab).
- **Environment:** each sensor's temperature and humidity, the room-minus-outdoor difference and the outdoor dew point (same formula as the alarms).
- Every value card: the value rounded for reading, its 60-minute range and sparkline; hover a sparkline for the values at that time.
- **Logger:** last reading, WiFi signal, backlog, SD card, firmware, running time. Then the alarm log (last 20, hotel time).
- Values listed in `site.json` that the page does not group are shown under "Other values", so adding one needs no code.
- Not yet: the time of the last push to OED (the push service is not written yet).
- Plain HTML and a few lines of JavaScript that fetch the JSON every 15 s; no chart library.
- Behind a Caddy login: the Arkan logins (`hub-users.caddy`, as OED) or a login for this platform only (`monitoring-users.caddy`). See [Logins](#logins).
- Readable on a phone.

**History pages of `/live/<site>/`** (side menu, added 8 November 2026 from the mockup's graph screens):

| Menu | Address | What it shows |
|---|---|---|
| Live now | `#now` (default) | the live view above |
| Power | `#power` | mean kW of each hour and the highest 15-second sample in it, over the period chosen (below) |
| One day | `#day` | the 1-minute power of one hotel day: the day before and after (◀ ▶) or any day from a calendar; the day's kWh, highest sample, base load; **CSV** of that day |
| Energy per day | `#energy` | kWh per hotel day from the meter's counter (today and incomplete days lighter); today, yesterday, mean of full days (for two dates: total, highest day, mean of full days) |
| This week vs last | `#week` | complete hours of this week (from Sunday 00:00) against the same hours last week, and day by day; says "not comparable" when records are missing in either week |
| Temperature, Humidity | `#temperature`, `#humidity` | hourly means of each sensor, hover for the hour's lowest and highest |

- **The period** (added 10 November 2026), at the top right of Power, Energy per day, Temperature, Humidity, the three power quality pages and the Weather log: **7, 14 or 31 days** (up to today), or **From … to …**: two hotel dates picked on a calendar, then **Show** (or Enter; Show turns blue while the dates are not shown yet). Both dates are included, at most 92 days; dates the wrong way round are swapped; the calendars start at the oldest record. The period stays when moving between these pages. While two dates are in use, no 7/14/31 button is pressed and the date fields are outlined; two dates that end today and span 7, 14 or 31 days become that button again (it moves with time).
- **CSV** (beside the period, and on One day): downloads the **original 1-minute records** of those dates in one file, `adab-LOG-0001-2026-11-03-to-2026-11-09.csv`: every column and every row of the logger's day files ([`DATA-FORMAT.md`](DATA-FORMAT.md)), nothing removed or averaged, times in UTC. The day files are UTC days, so the file holds the UTC days that cover the hotel dates and starts and ends a few hours outside them (for 3 to 9 November at Adab: 2 November 00:00 UTC = 08:00 hotel time, to 9 November 23:59 UTC). When the columns changed during the period (a `_2` file), the header has every column and each row its values under its own columns. Greyed when the period has no records. The Weather log's CSV is the weather log of the same dates.
- Data: `GET /api/v1/history/<site>?days=N` or `?from=YYYY-MM-DD&to=YYYY-MM-DD` (one row per hotel hour: kWh, mean and peak kW, sensor means, min and max; with `first_day`, the hotel date of the oldest record) and `GET /api/v1/history/<site>/day/<date>` (1-minute power), read from the day files by `server/app/history.py`. `GET /api/v1/records/<site>?from=&to=` (or `?days=N`, `&device=`) is the CSV, streamed file by file (little memory, about 0.7 MB per day before Caddy's gzip). Same login as the rest (`/api/v1/*` behind the Caddy login); a login limited to some sites (`USER_SITES`, [Logins](#logins)) gets the records of its own sites only.
- Energy is the step of the cumulative counter `EM01_e` between records less than an hour apart; a counter going down is ignored (A19 reports it). It matches `daily.csv` (`manage.py daily`).
- Each day file is summarised once and kept in memory until it changes: the first 14-day request reads the files (under a second for 14 days), later ones take a few milliseconds. A longer period reads more files the first time (92 days: a few seconds).
- These pages overlap with OED's line, bar and compare graphs. OED stays for what they do not do: groups of sites, export, maps, the comparison of any period.

**Power quality pages of `/live/<site>/`** (side menu, group *Power quality*, added 9 November 2026):

| Menu | Address | What it shows |
|---|---|---|
| Power quality | `#quality` | the share of minutes with all three phases inside the voltage limits (A05/A06: 207–242 V, 1-minute means), the lowest and highest 15 s sample, dips and swells (A26/A27: minutes with a 15 s sample below 207 V or above 253 V; below 100 V is A04 phase lost), voltage unbalance (A28, 2 %), the frequency range (A07, 50 ± 0.5 Hz), the power factor of the period, current imbalance (A10); a table day by day (click a day for its voltage minute by minute); the power quality lines of the alarm log of the period; the frequency hour by hour with its lowest–highest band |
| Voltage | `#voltage` | each phase's hourly mean with a grey band from the lowest to the highest 15 s sample, and the limits as dashed lines; voltage unbalance hour by hour (mean and highest minute, A28 line); **one hotel day minute by minute** (◀ ▶, a calendar, and a button to the day of the lowest sample of the period; it opens on the last day of the period); hover for each phase's range |
| Power factor | `#pf` | power factor of the period from the kWh and kVArh counters; mean under load; share of the loaded time below 0.85; the **kVArh above 62 % of the kWh** (what PLN bills as excess reactive energy when the month's power factor is under 0.85); an indicative capacitor size to reach 0.95; the power factor hour by hour with its lowest sample, its mean by hour of the day, kW and kvar hour by hour, and a table day by day |

- Data: `GET /api/v1/quality/<site>?days=N` (one row per hotel hour, with the limits and the power quality alarm lines) and `GET /api/v1/quality/<site>/day/<date>` (the 1-minute voltage, frequency and power factor of one hotel day), from the day files by `server/app/quality.py`. Same login as the rest. The same period as the history pages (`?days=N` or `?from=&to=`; the alarm lines are those of the period) and the same **CSV** button.
- **The limits come from the alarm register in use** (`alarm-register.csv` on the VPS, with the site's own lines): change a threshold there and the page counts against it at the next request, so the page and the alarms always agree. A line switched off (`enabled` = no) still gives its threshold, shown as "(alarm off)".
- Same rules as the alarms: unbalance is the largest deviation of a phase from the mean of the three, in % of the mean; current imbalance is not counted below 5 A; the power factor is counted only while the load is 1 kW or more, without its sign (leading or lagging is not told apart).
- The power factor of a period is kWh / √(kWh² + kVArh²) from the meter's counters `EM01_e` and `EM01_eq`, like PLN's monthly reading. The capacitor size is the largest need of an hour, kW × (tan φ − tan φ at 0.95): a first figure for an automatic bank, to confirm with a site survey.
- What a 1-minute record of 15 s samples cannot show: a sag shorter than the sampling, harmonics (THD) and flicker. The register table read today has no harmonic values.
- Each day file is summarised once and kept in memory until it changes, as for the history pages: under a second for the first 14-day request, then a few milliseconds.

**Weather pages of `/live/<site>/`** (side menu, group *Weather*, added 9 November 2026): **Today** (`#wtoday`, the forecast hour by hour with the outdoor sensor beside the past hours), **Tomorrow** (`#wtomorrow`, the next day forecast) and **Weather log** (`#wlog`, the actual weather of each hour against the forecast made the day before, with the day's kWh). Live now shows one weather line under the alarms. Open-Meteo, fetched every hour by the ingest service; logs in `sites/<site>/weather/`. Setup and file format: [`WEATHER.md`](WEATHER.md).

**Logger pages of `/live/<site>/`** (side menu, group *Logger*):

| Menu | Address | What it is | Who |
|---|---|---|---|
| Meter registers | `#register` (a list of the loggers at the top right if the site has several; the old address `/live/<site>/register` leads here) | the meter register table the logger reads: see, edit, import, check and send it, history of versions, and the meter link settings (`meters`, `mb_baud`, `mb_format`, `ct_mult`). Firmware 0.4.0 or later. Steps: [`meter/README.md`](meter/README.md#changing-the-register-table) | everyone with the Arkan login |
| Firmware versions | `#versions` | each logger's running firmware and build, since when, last restart and why, what is offered and its state, versions refused; the history of every firmware change, offer and (optional) restart; the GitHub releases and which logger runs each; the firmware files on the server. Read only. Data: `GET /api/v1/versions/<site>` | everyone with the Arkan login |
| Firmware update | `#firmware` | one panel per logger: send a GitHub release, a `.bin` file or a stored file to that logger, status and recent events. [`OTA.md`](OTA.md) | only the logins in `ADMIN_USERS` (`server/.env`); the menu entry is hidden for the others |

**`/live/`** lists all sites with their status and total kW: the multi-site live overview.

## Logins

Every address for people (the site pages, their API, Open Energy Dashboard) is behind a Caddy login (HTTP basic auth). Two files on hermes-vps hold the logins. Both are owner only: never in git, never copied.

| File | For | Opens |
|---|---|---|
| `/opt/edge/secrets/hub-users.caddy` | Arkan staff: the shared Arkan logins | every Arkan dashboard, this platform and OED included |
| `/opt/edge/secrets/monitoring-users.caddy` (since `v0.7.1`) | people who only need this platform, for example a technician | the site pages and their API only: not OED, not the other Arkan dashboards |

Two lines of `server/.env` give the rights inside the site page:

| Setting | Effect | Example |
|---|---|---|
| `ADMIN_USERS` | Logins that may send a firmware to a logger (**Firmware update**, [`OTA.md`](OTA.md)). They show as `Admin` in **View as** | `ADMIN_USERS=julien,tech-adab` |
| `USER_SITES` (since `v0.7.1`) | Logins limited to some sites: `login:site`, comma separated; a login may come back for a second site (`ops:adab,ops:villa`). `/live/` (the list of all sites) and the page of another site send them to their own site; **All sites** is not in their menu; every API path of another site, or of a logger of another site, answers `403` (firmware update and register table included). A login not listed sees every site. A wrong site name (`tech-adab:Adab`) limits the login to no site, never to all | `USER_SITES=tech-adab:adab` |

Every login can, on the sites it sees: live data, history, power quality, weather, firmware versions, and the **Meter registers** page, which includes sending a new register table and the meter link settings to the logger (each change is written in the register history with the login name). `ADMIN_USERS` adds **Firmware update**. **Settings** shows the login, its rights and its sites.

### Adding a technician's login (owner, on hermes-vps)

The example gives the login `tech-adab` full access to the Adab site page (firmware update included), and nothing else. It needs `v0.7.1` or later on the VPS, with its Caddy file ([`UPDATING.md`](UPDATING.md) section L).

1. Choose the login name (letters, digits, `-`, `_`; it shows in **View as** and in the register history) and a long password. Give the password to the technician in person or through the password manager, never in a chat. One login per person, so it can be removed alone.
2. The password hash. Caddy asks for the password twice and prints the hash; nothing is saved:

```bash
caddy hash-password
```

3. Add a line `tech-adab <the hash, exactly as printed>` to the platform-only file (the file is created by [`UPDATING.md`](UPDATING.md) L3.3). A login name must not be in both files.

```bash
sudo nano /opt/edge/secrets/monitoring-users.caddy
```

4. The rights. Add the login to `ADMIN_USERS` after the names already there (leave it out for someone who must not send firmware), and limit it to its site:

```bash
cd /opt/arkan-monitoring/server
```

```bash
nano .env
```

```
ADMIN_USERS=julien,tech-adab
USER_SITES=tech-adab:adab
```

5. Check the Caddy configuration:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

**Expected:** `Valid configuration`. **If** an error names `monitoring-users.caddy` or the login: the line is not `name hash`, or the name is in both files. Nothing has changed on the live site yet: fix the line and validate again.

6. **The owner approves** the service restart (about 30 s without live data on the page) and the Caddy reload:

```bash
docker compose up -d
```

```bash
sudo systemctl reload caddy
```

7. Checks, with the technician's password:

```bash
curl -s -u tech-adab https://arkan-monitoring.duckdns.org/api/v1/admin/me
```

**Expected:** `"user": "tech-adab"`, `"admin": true` and `"sites": ["adab"]` (`"admin": false` if the login is not in `ADMIN_USERS`). **If** nothing is printed (Caddy refused the login): the password or the hash line is wrong, or Caddy was not reloaded. **If** `"sites": null`: `USER_SITES` is not set, or the container was not restarted.

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" -u tech-adab https://arkan-monitoring.duckdns.org/live/
```

**Expected:** `302 https://arkan-monitoring.duckdns.org/live/adab/`.

In a private browser window, log in as `tech-adab`: `https://arkan-monitoring.duckdns.org/live/adab/` opens, the menu has no **All sites**, **Settings** shows `Sites: adab only`, and `https://arkan-monitoring.duckdns.org/live/` lands on the Adab page. With your own login, `/live/` still lists every site.

**Removing the login:** delete its line in `monitoring-users.caddy`, validate and reload Caddy (steps 5 and 6), then take the name out of `ADMIN_USERS` and `USER_SITES` and `docker compose up -d`. The Caddy reload alone already locks the login out.

## Getting from OED to the live page

OED has no setting for a custom menu link. The live page links to OED, and people bookmark `/live/` as the start page. If a single entry point is wanted later, option C (a small "Live" link added to OED's header) is the smallest change to OED.
