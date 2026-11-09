# Updating the VPS and the loggers

How a new version of this repository reaches `hermes-vps` and the loggers. **This release: 9 November 2026, VPS `v0.5.0`** (section A, below); the loggers keep firmware `0.4.0`. The steps of the 8 November release (`v0.4.0`) follow it, for reference. The detailed tutorial steps are in [tutorial 2, C5](tutorials/2-VPS-SETUP.md#c5-updating-to-a-new-tag-and-going-back) (VPS) and [`OTA.md`](OTA.md) (loggers).

House rules: the VPS only runs **tags**; the owner approves every container restart and the Caddy reload; a backup comes first.

## A. Release v0.5.0 (9 November 2026): weather, saved live data, firmware versions page

### A0. What is in it

| Part | What changed | What it needs |
|---|---|---|
| Weather | Menu group **Weather**: Today (forecast hour by hour), Tomorrow (next day forecast), Weather log (actual weather against the forecast and the outdoor sensor, CSV). One weather line on Live now. Open-Meteo, no key ([`WEATHER.md`](WEATHER.md)) | VPS update, then **once**: the site's position (A3.5). The container must reach `api.open-meteo.com` |
| Live data saved | Every 15 s snapshot is also saved in the data folder (`live.json`, `live/<day>.jsonl`, 7 days, about 3 MB a day per logger); the live page refills after a restart; a second dashboard can read everything from one place ([`DATA-ACCESS.md`](DATA-ACCESS.md)) | VPS update. Optional `.env` key `LIVE_KEEP_DAYS` |
| Firmware versions page | **Firmware versions** in the menu (group Logger), for everyone: running firmware, since when, last restart, offers, history, GitHub releases ([`OTA.md`](OTA.md) section 5) | VPS update |
| Docker network | The service's network is now named `arkan-monitoring` (a second dashboard's container joins it) | Nothing: the restart creates it (A3.4) |
| Firmware | No change: stays `0.4.0`, **no `fw-v` tag** this time | Nothing on the loggers |
| Caddy | No change: the new pages and `/api/v1/weather/*`, `/api/v1/versions/*` are behind the Arkan login like the others | Nothing (checked in A3.3) |

### A1. On GitHub (owner): merge, then tag

1. Merge the pull request from `claude/practical-cori-ji7fop` into the default branch. Wait for CI to be green (jobs `firmware`, `server`, `tools`).
2. Tag the merge commit `v0.5.0`, on GitHub (**Releases**, **Draft a new release**, **Choose a tag**, type `v0.5.0`, target the default branch, publish) or from a terminal on the merged commit:

```bash
git tag v0.5.0
```

```bash
git push origin v0.5.0
```

Its `/health` answers `"version": "0.5.0"`.

### A2. Before: where you start from

**Where:** VPS, user ai (`ssh hermes-vps`), except the steps marked owner.

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** `v0.4.0`. Write it down: it is what you go back to.

```bash
git status
```

**Expected:** `nothing to commit, working tree clean` (an untracked `server/.env` is fine). Modified files: stop and ask the owner.

### A3. Update

**A3.1 Backup**

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**A3.2 Get the new version**

```bash
git fetch --tags
```

```bash
git checkout v0.5.0
```

**A3.3 `.env` and Caddy: nothing to change, check only**

```bash
diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy
```

**Expected:** no output (if OED is installed, compare with `server/deploy/oed/monitoring-oed.caddy`). The new `.env` keys are optional; without them the defaults apply: `WEATHER` (on), `WEATHER_EVERY_MIN` (60), `LIVE_KEEP_DAYS` (7); see `server/.env.example`.

**A3.4 Rebuild and restart (owner approves)**

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

**Expected:** `Network arkan-monitoring Created` and the container `Recreated`, `Started`. The old network of the service (`server_default`) is no longer used; once the container is up, the owner may remove it (it fails harmlessly if something else still uses it):

```bash
docker network rm server_default
```

**A3.5 Weather: the hotel's position (once)**

Adab Sidemen Resort, from the Google Maps pin:

```bash
docker compose exec ingest python tools/manage.py weather adab --lat -8.4766 --lon 115.4319
```

**Expected:** `fetched ... hours`, then `now (...)`, then three lines, today, tomorrow and the day after, each with a weather, a temperature range and rain. If it says `Open-Meteo not reachable`, the container cannot open an HTTPS connection to `api.open-meteo.com`: check the VPS outbound firewall rules (the firmware panel reaches `api.github.com` the same way), then run the command again. The rest of the release works without it.

### A4. Checks

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.5.0", ...}`.

```bash
docker compose ps
```

**Expected:** `Up ... (healthy)` after a minute.

```bash
ls -l /srv/arkan-monitoring/data/sites/adab/LOG-0001/live.json /srv/arkan-monitoring/data/sites/adab/weather/
```

**Expected:** `live.json` changed in the last 15 s (the logger is sending live data); `forecast.json`, `actual-2026.csv` in the weather folder (`dayahead-2026.csv` appears at 18:00 hotel time).

In the browser, `https://arkan-monitoring.duckdns.org/live/adab/`:
- **Live now**: the weather line under the alarms;
- menu **Weather**: Today, Tomorrow and Weather log show data;
- menu **Logger**, **Firmware versions**: LOG-0001 on `0.4.0`, "up to date", its history;
- restart test (optional, owner approves): `docker compose restart ingest`, then Live now still shows the last 60 minutes at once.

**Going back:** `git checkout v0.4.0`, then `docker compose up -d --build`. The data folder keeps the new `weather/` and `live/` files; `v0.4.0` ignores them, so going back is safe. Nothing to undo in Caddy.

---

# Release v0.4.0 (8 November 2026), for reference

## 0. What is in this release

| Part | What changed | What it needs |
|---|---|---|
| Site page `/live/<site>/` | New design (dashboard mockup), side menu, history pages (power, one day, energy per day, week, temperature, humidity) | VPS update |
| Register page `/live/<site>/register` | See, edit, import, check and send the meter register table and the meter link settings | VPS update **and the new Caddy file** (`/api/v1/registers` is a logger path); logger firmware 0.4.0 |
| Firmware update | **Firmware update** in the site page's menu: send a GitHub release or a `.bin` to one logger | VPS update and `ADMIN_USERS` in `server/.env` |
| Firmware 0.4.0 | Remote register table; build marker and build report (OTA checks); "check now" hint; registers read only when they touch; floats with 3 decimals | Flash once by cable, or OTA from an older logger |
| CI | Tag `fw-v<version>` makes a GitHub release with the OTA images; Modbus simulator tests | Nothing on the VPS |
| OED files | `server/deploy/oed/`: tested on a test machine, `oed-setup.py`, unguarded OED routes blocked | Only if OED is installed (tutorial 3) |

## 1. On GitHub (owner): merge, then tag

1. Merge the work into the default branch (pull request from `claude/great-brahmagupta-9uvj1m`, which holds every session of 8 November 2026). Wait for CI to be green (jobs `firmware`, `server`, `tools`).
2. Tag the merge commit twice, on GitHub (**Releases**, **Draft a new release**, **Choose a tag**, type the name, target the default branch) or from a terminal on the merged commit:

```bash
git tag v0.4.0
```

```bash
git tag fw-v0.4.0
```

```bash
git push origin v0.4.0 fw-v0.4.0
```

- `v0.4.0` is the version the VPS checks out. Its `/health` answers `"version": "0.4.0"`.
- `fw-v0.4.0` makes CI build the firmware and create the release **Logger firmware 0.4.0** with `logger-0.4.0.bin`, `logger-uart-0.4.0.bin`, the bootloader and the partition table. CI stops if the tag does not match `FW_VERSION` in `firmware/include/config.h` (0.4.0).

## 2. The VPS

**Where:** VPS, user ai (`ssh hermes-vps`), except the steps marked owner.

**2.1 Where you start from**

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** a tag (for example `v0.3.0`): write it down as `<previous-tag>`. A bare commit number (no tag yet) is fine too: write it down the same way, it is what you go back to.

```bash
git status
```

**Expected:** `nothing to commit, working tree clean` (an untracked `server/.env` is fine). If files are listed as modified, someone edited the code on the VPS: stop and ask the owner.

**2.2 Backup**

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**2.3 Get the new version**

```bash
git fetch --tags
```

```bash
git checkout v0.4.0
```

**2.4 `.env`: who may update firmware from the web page**

```bash
cd /opt/arkan-monitoring/server
```

```bash
cp -n .env.example .env
```

```bash
chmod 600 .env
```

```bash
nano .env
```

Set `ADMIN_USERS=<your Arkan login>` (comma separated for several; the names of `hub-users.caddy`). Keep `FW_GITHUB_REPO=julien355/esp32-datalogging`. `FW_GITHUB_TOKEN` only if the repository is private ([`OTA.md`](OTA.md) section 6). If your `.env` already existed, keep its `INGEST_PORT` and add the three new lines from `.env.example`.

**2.5 The Caddy site file (owner)**

```bash
diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy
```

**Expected for this release:** one difference, `/api/v1/registers` added at the end of the `@device` line. (If OED is installed, compare with `server/deploy/oed/monitoring-oed.caddy` instead, and install that one below.) If you see other differences, someone changed the live file: stop and compare with the owner.

The owner keeps a copy of the current file, installs the new one, validates, and reloads after the container is up (2.6):

```bash
sudo cp /opt/edge/sites/monitoring.caddy /opt/edge/monitoring.caddy.before-v0.4.0
```

```bash
sudo cp /opt/arkan-monitoring/server/deploy/monitoring.caddy /opt/edge/sites/monitoring.caddy
```

If the port is not 8800 (tutorial 2, B14), edit the three `reverse_proxy 127.0.0.1:8800` lines again now.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

**Expected:** `Valid configuration`.

**2.6 Rebuild and restart (owner approves)**

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

Then the Caddy reload (owner):

```bash
sudo systemctl reload caddy
```

**2.7 Checks**

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.4.0", ...}`.

```bash
docker compose ps
```

**Expected:** `Up ... (healthy)` after a minute.

```bash
docker compose logs --tail 20 ingest
```

**Expected:** the logger's `POST /api/v1/ingest` lines coming back (it kept its records on the SD card during the restart).

In the browser, `https://arkan-monitoring.duckdns.org/live/adab/`:
- the new design: dark blue header with the green pill `Live · updated n s ago`, side menu on the left;
- **Power** and **Energy per day** in the menu show the history from the day files;
- **Meter registers** opens `/live/adab/register`;
- **Firmware update** is in the menu for the logins in `ADMIN_USERS`, not for the others.

**Going back:** `git checkout <previous-tag>`, `docker compose up -d --build`, and the owner puts back `/opt/edge/monitoring.caddy.before-v0.4.0`, validates and reloads. The data folder is not changed by this release, so going back is safe.

## 3. The loggers

Check what each logger runs: `docker compose exec ingest python tools/manage.py list` (`fw ...`).

| The logger | How it gets 0.4.0 |
|---|---|
| **Not flashed yet** (the bench logger before the first test) | By cable: tutorial 1, [A4](tutorials/1-LOGGER-ON-SITE.md#a4-building-and-flashing-the-firmware), from the tagged code (`git checkout fw-v0.4.0` in your copy) or the release's `.bin` files |
| **Online, on 0.3.x** | Over the air, after the VPS update (section 2): site page, **Firmware update**, **From a GitHub release**, choose `fw-v0.4.0: logger-0.4.0.bin` (the native USB build; `logger-uart-0.4.0.bin` only for a logger built with `logger-uart`), **Send to LOG-0001**. A 0.3.0 logger does not know the "check now" hint: it takes the update at its next check (6 h, `ota_check_h`), or at once if someone types `ota` on its console |
| **On site, offline** | It takes the offer at its next check after it comes back online. Nothing to do on site |

**After the update** (from 0.3.0: within 6 h, or at once after `ota` on the console; later updates from 0.4.0: within a minute):
- `manage.py list` shows `fw 0.4.0`, and the alarm log has **A35 Firmware updated** `... -> 0.4.0, by remote update (OTA)`;
- the panel shows *installed* and the logger's build (`usb`): from 0.4.0 on, the panel checks the build of every file sent;
- the register page shows the table on the logger (it reports after each boot) instead of *Firmware too old*.

If the logger kept restarting on the new firmware, it goes back by itself (**A36**) and that version is not offered to it again: report it, do not send it to other loggers.

**Command line instead of the panel** (VPS, after copying the `.bin` to `/srv/arkan-monitoring/data/`):

```bash
docker compose exec ingest python tools/manage.py publish-fw /data/logger-0.4.0.bin --device LOG-0001
```

## 4. Next releases


- **VPS only:** a new tag `v0.x.y`, then section 2 (2.4 and 2.5 only if `.env.example` or the Caddy file changed: tutorial 2, C5 steps 3a and 3b, tell you).
- **Firmware only:** change `FW_VERSION`, test on the bench logger, tag `fw-v<version>`, then section 3 from the panel. Every build gets a new version number, never reused ([`OTA.md`](OTA.md) section 2).
