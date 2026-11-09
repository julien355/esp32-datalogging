# Updating the VPS and the loggers

How a new version of this repository reaches `hermes-vps` and the loggers, and the extra steps of the **8 November 2026 release** (VPS `v0.4.0`, firmware `0.4.0`, replaced by **`0.4.1`** on 9 November: section 5). The detailed tutorial steps are in [tutorial 2, C5](tutorials/2-VPS-SETUP.md#c5-updating-to-a-new-tag-and-going-back) (VPS) and [`OTA.md`](OTA.md) (loggers).

House rules: the VPS only runs **tags**; the owner approves every container restart and the Caddy reload; a backup comes first.

## 0. What is in this release

| Part | What changed | What it needs |
|---|---|---|
| Site page `/live/<site>/` | New design (dashboard mockup), side menu, history pages (power, one day, energy per day, week, temperature, humidity) | VPS update |
| Register page `/live/<site>/register` | See, edit, import, check and send the meter register table and the meter link settings | VPS update **and the new Caddy file** (`/api/v1/registers` is a logger path); logger firmware 0.4.0 |
| Firmware update | **Firmware update** in the site page's menu: send a GitHub release or a `.bin` to one logger | VPS update and `ADMIN_USERS` in `server/.env` |
| Firmware 0.4.0, **use 0.4.1** | Remote register table; build marker and build report (OTA checks); "check now" hint; registers read only when they touch; floats with 3 decimals | 0.4.1: first time by cable on the bench, then OTA (section 3). 0.4.0 is withdrawn (section 5) |
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

**Use firmware 0.4.1, never 0.4.0** (section 5). Tag `fw-v0.4.1` once 0.4.1 has run 10 minutes on the bench logger without a restart (section 5, step 2): CI makes the release **Logger firmware 0.4.1**.

Check what each logger runs (VPS, in `/opt/arkan-monitoring/server`): `docker compose exec ingest python tools/manage.py list` (`fw ...`).

| The logger | How it gets 0.4.1 |
|---|---|
| **Not flashed yet** (the bench logger before the first test) | By cable: tutorial 1, [A4](tutorials/1-LOGGER-ON-SITE.md#a4-building-and-flashing-the-firmware), from the tagged code (`git checkout fw-v0.4.1` in your copy) or the release's `.bin` files |
| **Online, on 0.3.x** | Over the air, after the VPS update (section 2): site page, **Firmware update**, **From a GitHub release**, choose `fw-v0.4.1: logger-0.4.1.bin` (the native USB build; `logger-uart-0.4.1.bin` only for a logger built with `logger-uart`), **Send to LOG-0001**. A 0.3.0 logger does not know the "check now" hint: it takes the update at its next check (6 h, `ota_check_h`), or at once if someone types `ota` on its console |
| **On site, offline** | It takes the offer at its next check after it comes back online. Nothing to do on site |

**After the update** (from 0.3.0: within 6 h, or at once after `ota` on the console; later updates from 0.4.1: within a minute):
- `manage.py list` shows `fw 0.4.1`, and the alarm log has **A35 Firmware updated** `... -> 0.4.1, by remote update (OTA)`;
- the panel shows *installed* and the logger's build (`usb`): from 0.4.0 on, the panel checks the build of every file sent;
- the register page shows the table on the logger (it reports after each boot) instead of *Firmware too old*.

If the logger kept restarting on the new firmware, it goes back by itself (**A36**) and that version is not offered to it again: report it, do not send it to other loggers.

**Command line instead of the panel** (VPS, in `/opt/arkan-monitoring/server`, after copying the `.bin` to `/srv/arkan-monitoring/data/`):

```bash
docker compose exec ingest python tools/manage.py publish-fw /data/logger-0.4.1.bin --device LOG-0001
```

## 4. Next releases

- **VPS only:** a new tag `v0.x.y`, then section 2 (2.4 and 2.5 only if `.env.example` or the Caddy file changed: tutorial 2, C5 steps 3a and 3b, tell you).
- **Firmware only:** change `FW_VERSION`, test on the bench logger, tag `fw-v<version>`, then section 3 from the panel. Every build gets a new version number, never reused ([`OTA.md`](OTA.md) section 2).

## 5. 9 November 2026: firmware 0.4.0 withdrawn, 0.4.1, and the lessons of the update

### What happened

- 8 November: the VPS went to `v0.4.0` and the release `fw-v0.4.0` was sent to `LOG-0001` (on 0.3.0) from the panel. On 0.4.0 the logger restarted about 60 s after each WiFi connection (`task_wdt` in its log). After three boots it went back to 0.3.0 by itself, as designed (**A36**, the panel shows *rolled back*). It does not take 0.4.0 again.
- **Cause.** When the server has nothing to send back, it answers `204 No Content` (live values, settings report, settings check and, new in 0.4.0, the register table check). Caddy sends a 204 without a length. The ESP32 web library then waited for the end of the reply until the server closed the connection, which it never does (the logger reuses it on purpose). After 60 s the task watchdog restarted the board. 0.4.0 checks the register table at each boot, and the answer is 204 until a table is sent, so it hung at every boot.
- The same fault had already been fixed on the office PC (commit `f4527ba`, 8 November, flashed by cable at 06:22 UTC, stable since), together with the AM2301 on GPIO 1. **That commit had not been pushed**, so CI built 0.4.0 without it. It is now merged.
- Also found: the console command `tail` on a big log file restarted the logger (it read the card one byte at a time while holding it). Fixed in 0.4.1; on 0.3.x use `cat` instead.

### What 0.4.1 changes

| Change | Why |
|---|---|
| No reply body read on `1xx`, `204` and `304` | The fault above (commit `f4527ba`) |
| AM2301 (`TH2`) default `pin_dht` = **1** | As wired and checked on the board (commit `f4527ba`); docs and drawings follow |
| Optional SD files checked before they are opened or removed | No more "does not exist" errors in the boot messages |
| `cat` and `tail` read the card in blocks and release it while printing | `tail` no longer starves the other tasks |

### Steps (owner, with the bench logger on the USB cable)

1. **Flash 0.4.1 by cable** from VS Code. In the VS Code terminal, bring your copy `C:\dev\esp32-datalogging` to the code of 0.4.1 (your own commit is in it):

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git fetch origin
```

```powershell
git checkout -B release-0.4.1 origin/claude/great-brahmagupta-9uvj1m
```

```powershell
cd firmware
```

```powershell
pio run -e logger -t upload
```

```powershell
pio device monitor -p COM4 -b 115200 -f esp32_exception_decoder -f time -f log2file
```

2. **Watch 10 minutes.** Expected: `firmware 0.4.1` at the boot, `TH2 sensor: AM2301 on GPIO 1`, WiFi connected, then **no** restart. `status` after 10 minutes shows `up 600 s` or more, `Uploads: ok n, failed 0`. If it restarts, keep the monitor text (the `log2file` file in the `firmware` folder) and stop there.
3. **Only then:** merge into the default branch, then tag `fw-v0.4.1` (section 1, with `fw-v0.4.1` instead of `fw-v0.4.0`; no new VPS tag is needed, the service did not change). CI makes the release **Logger firmware 0.4.1**.
4. **Mark `fw-v0.4.0` as withdrawn** on GitHub: **Releases**, **Logger firmware 0.4.0**, **Edit**, tick **Set as a pre-release**, add `Withdrawn: restarts every minute behind Caddy. Use 0.4.1.` to the notes, **Update release**. The panel then lists it as `(pre-release)`.
5. **Put the OTA check back to 6 h** (it was set to 1 h for the test). VPS:

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose exec ingest python tools/manage.py set-config LOG-0001 ota_check_h=@default
```

6. From now on, firmware for `LOG-0001` goes over the air from the panel (section 3), always after a bench test on a logger on the cable.

### Lessons for the next updates

- **Push before you tag.** A fix built on a PC and flashed by cable is committed **and pushed** the same day. Before a `fw-v` tag, compare the board's own log with the code: `TH2 sensor: AM2301 on GPIO ...` and `BOOT fw=...` must match what the tag builds.
- **Bench before OTA.** A new firmware runs 10 minutes on the bench logger, flashed by cable with the monitor open, before it is sent over the air to anyone.
- **The VPS code is a git clone.** On 8 November `/opt/arkan-monitoring` was a copy made by hand (`git describe` said `fatal: not a git repository`). It was replaced by a clone of the (now public) repository, checked out at the tag. The old copy is kept as `/opt/arkan-monitoring.hand-copy-2026-11-08`: delete it once the owner agrees. `server/.env` is not in git and stays in place across updates.
- **Every `docker compose` command runs in `/opt/arkan-monitoring/server`.** Elsewhere it answers `no configuration file provided: not found`.
- **Never `docker rm -f` the container.** If `curl -s http://127.0.0.1:8800/health` gives no answer and `docker compose ps` lists nothing, the container is not running: `docker compose up -d --build` (in `/opt/arkan-monitoring/server`) creates it again. The data is in `/srv/arkan-monitoring/data`, not in the container.
- **Read the logger's own log** when an update fails: the serial monitor (tutorial 1, [A5](tutorials/1-LOGGER-ON-SITE.md#a5-first-boot-and-the-serial-monitor); in VS Code `pio device monitor -p COM4 -b 115200` from the `firmware` folder), then `ls /log` and `cat /log/<YYYY-MM>.log`.
