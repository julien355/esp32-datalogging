# Weather forecast and weather log

The site page `/live/<site>/` has a **Weather** group in its side menu (service 0.5.0, 9 November 2026):

| Menu | Address | What it shows |
|---|---|---|
| Today | `#wtoday` | the forecast of today, hour by hour: weather, temperature, feels like, rain and its chance, humidity, cloud, wind, sun. Past hours in grey, with the logger's outdoor sensor (`TH2`) beside them. Tiles: now, lowest and highest, rain today and when it is likely, sun energy, sunrise and sunset |
| Tomorrow | `#wtomorrow` | the next day forecast: the same table and graphs, and tomorrow's highest against today's |
| Weather log | `#wlog` | the actual weather of every past hour against what was forecast the day before, and against the outdoor sensor; one row per day with the site's kWh. 7, 14 or 31 days. **CSV ↓** downloads the hourly log |

**Live now** also shows one line under the alarms: weather now, today's range and rain, tomorrow's range (click it for Today).

## Where the data comes from

[Open-Meteo](https://open-meteo.com): free, no account and no key, CC BY 4.0 (the source is named on every weather page).
It blends the national weather models (ECMWF, GFS, ICON and others) for the site's position; Indonesia has no
public BMKG API with hourly data, which is why it is used.

- The ingest service fetches the forecast **every hour** for each site that has a position (one small request, about 30 kB; Open-Meteo allows 10 000 a day free for non-commercial use: an hourly fetch per site is far below it. For commercial use Open-Meteo asks for its paid plan).
- If Open-Meteo cannot be reached, the service tries again after 10 minutes; the page shows the last forecast it has and the error.
- Nothing is asked of the logger: no firmware change.

## The logs (files on the VPS)

```
sites/adab/weather/forecast.json       the last forecast fetched (2 days back to the day after tomorrow, hour by hour)
sites/adab/weather/actual-2026.csv     ACTUAL weather: one row per hotel hour that has passed
sites/adab/weather/dayahead-2026.csv   NEXT DAY forecast: tomorrow's 24 hours, saved once a day at 18:00 hotel time
```

Both CSV files only grow (a row is never rewritten), open in Excel, and are in the nightly backup with the rest of the data folder.

- **One row = one hotel hour**, `t` = `2026-11-09 14:00` means 14:00 to 15:00, the same hours as the history pages and `daily.csv`.
- **Actual** (`actual-YYYY.csv`): written one hour after the hour ends, from Open-Meteo's latest run (corrected with the observations it has). It is the weather *service's* value for the place, not a measurement at the hotel; the measurement is the outdoor sensor `TH2` in the day files. The log page shows both: their mean difference tells if the sensor is in the sun or near a warm wall. After a service stop of up to 2 days, the missing hours are filled at the next fetch.
- **Day-ahead** (`dayahead-YYYY.csv`): the first fetch at or after `dayahead_hour` (18:00) saves tomorrow's 24 hours with the time it was issued. The weather log joins it to the actual hour, so a forecast can be judged (and, later, used to forecast the next day's kWh).

| Column | Unit | Meaning |
|---|---|---|
| `t` | hotel time | start of the hour |
| `temp_c`, `feels_c`, `dew_c` | °C | air temperature at 2 m, feels like, dew point: mean of the hour |
| `rh_pct`, `cloud_pct` | % | relative humidity, cloud cover: mean of the hour |
| `precip_mm` | mm | rain in the hour |
| `precip_prob_pct` | % | chance of rain in the hour (day-ahead file only) |
| `wind_kmh`, `gust_kmh`, `wind_dir` | km/h, degrees | wind at 10 m, gusts, direction it comes from (0 = north) |
| `rad_wm2` | W/m² | sun on a flat surface (shortwave radiation), mean of the hour |
| `code`, `condition` | | WMO weather code and its name, the worse of the hour (e.g. 61 Light rain) |
| `fetched_utc` / `issued_utc` | UTC | when that row was fetched |

The log CSV from the page adds `fc_temp_c`, `fc_precip_mm`, `fc_precip_prob_pct`, `fc_code`, `fc_condition`, `fc_issued_utc`: the day-ahead forecast of that hour (empty if none was saved).

## Turning it on for a site

Weather is off until the site has a position. On the VPS (decimal degrees, south and west negative; take them from Google Maps, right click on the building).

**Adab** (Adab Sidemen Resort, Sidemen, Karangasem; Google Maps pin -8.4766088, 115.4318855):

```bash
cd /opt/arkan-monitoring/server
docker compose exec ingest python tools/manage.py weather adab --lat -8.4766 --lon 115.4319
```

Open-Meteo uses its nearest grid point (-8.4710, 115.4381, about 600 m away) and corrects the temperature to 480 m
elevation, the valley's height: expect about 2 °C cooler than Ubud or the coast. Checked on 9 November 2026: 21.6 to
29.6 °C, thunderstorm, 8.5 mm of rain.

This writes the position in `sites/adab/site.json`, fetches once and prints today, tomorrow and the log count. The service then fetches every hour by itself; the page has the Weather menu at once.

```json
"weather": {"lat": -8.4766, "lon": 115.4319, "dayahead_hour": 18, "model": "best_match", "enabled": true}
```

Other options of `manage.py weather <site>`:
- `--dayahead-hour 20`: save tomorrow's forecast at 20:00 instead of 18:00 (hotel time);
- `--model ecmwf_ifs025`: one model instead of Open-Meteo's best blend (names on open-meteo.com);
- `--off`: stop fetching (the logs are kept); give `--lat/--lon` again to turn it back on;
- `--no-fetch`: only show the forecast and the log.

Changing the position later does not clear the logs: rows before the change are for the old position. Move or rename
`sites/<site>/weather/actual-*.csv` and `dayahead-*.csv` first if the old position was wrong.

New sites: `manage.py add-site <code> ... --lat .. --lon ..` sets it at once.

## Service settings (`server/.env`, optional)

| Setting | Default | |
|---|---|---|
| `WEATHER` | `on` | `off` = the service never fetches (the pages show the last forecast and the logs) |
| `WEATHER_EVERY_MIN` | `60` | minutes between two fetches of a site |

The container needs to reach `api.open-meteo.com` on port 443 (outbound HTTPS, like GitHub for the firmware). Caddy needs no change: `/api/v1/weather/*` is behind the Arkan login like the other people pages.

## API (behind the Arkan login)

- `GET /api/v1/weather/<site>`: the last forecast: `current`, `days` (per day: condition, low, high, rain, chance, sun kWh/m², UV, sunrise, sunset) and `hours` from today 00:00 to the day after tomorrow, `fetched`, `error`.
- `GET /api/v1/weather/<site>/log?days=7`: `hours` (actual with the `fc_` day-ahead values) and `days` (low, high, rain, sun, forecast low, high, rain), up to 92 days; `&format=csv` for the CSV file.

Code: [`server/app/weather.py`](../server/app/weather.py); page: [`server/app/live.html`](../server/app/live.html) (`WXVIEWS`); tests: [`server/tests/test_weather.py`](../server/tests/test_weather.py).
