# How to update the VPS and the logger

The same steps for every release. In this guide, `vX.Y.Z` stands for the release you are installing, for example `v0.8.0`, and `X.Y.Z` stands for a firmware version, for example `0.4.2`. Before you start, read that release's section in [`UPDATING.md`](UPDATING.md). Its table **What is in it** says whether `.env`, Caddy or the loggers need anything more.

| Part | What | Where | Who |
|---|---|---|---|
| [1](#1-before-any-update-the-pc-folder) | Bring the PC folder up to date | PC, PowerShell | operator |
| [2](#2-the-vps-from-its-terminal) | Update the VPS to a new tag | GitHub, then `ssh hermes-vps` | operator; the owner approves the restart |
| [3](#3-the-logger-by-cable-from-vs-code-and-platformio) | Flash the logger by cable | PC, VS Code, PlatformIO terminal, logger on USB | operator, at the bench or on site |
| [4](#4-the-logger-over-the-air-from-a-github-release) | Send a firmware over the air | GitHub, then the site page | a login in `ADMIN_USERS` |

**Version numbers.** They are never reused.

| Tag | Is the version of | Set in | Shown by |
|---|---|---|---|
| `vX.Y.Z` | the VPS code (service, site page) | `VERSION` in `server/app/server.py` | `curl -s http://127.0.0.1:8800/health` on the VPS |
| `fw-vX.Y.Z` | the logger firmware | `FW_VERSION` in `firmware/include/config.h` | `status` on the logger console; the page **Firmware versions** (`/live/adab/#versions`) |

**House rules**
- GitHub is the reference. What is not pushed does not exist.
- The VPS only runs tags.
- A backup comes first.
- The owner approves every container restart and every Caddy reload.
- A new firmware runs 10 minutes on the bench logger, flashed by cable, before it goes over the air to anyone.

Order when both change: GitHub, then the PC folder, then the VPS, then the loggers.

## 1. Before any update: the PC folder

**Where:** PC, PowerShell, or the VS Code terminal. The code is in **one** folder, `C:\dev\esp32-datalogging` ([`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md) section 3).

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git checkout ccr-a52c0421-oygp4n
```

```powershell
git pull
```

```powershell
git fetch origin --tags --prune
```

```powershell
git status
```

**Expected:** `Your branch is up to date with 'origin/ccr-a52c0421-oygp4n'` and `nothing to commit, working tree clean`. Modified files listed: commit and push them, or ask, before you go on.

## 2. The VPS, from its terminal

### 2.1 On GitHub: merge, then tag (PC)

1. On GitHub, merge the pull request "Release vX.Y.Z" into the default branch `ccr-a52c0421-oygp4n` once CI is green (jobs `firmware`, `server`, `tools`).
2. On the PC, after part 1 (`git pull` brings the merge):

```powershell
git log -1 --oneline
```

**Expected:** the merge commit, a line like `cae7b85 Release vX.Y.Z: ... (#7)`. Anything else: stop. The merge is not in your folder yet, or someone pushed after it.

```powershell
git tag vX.Y.Z
```

```powershell
git log -1 --oneline vX.Y.Z
```

**Expected:** the same line as above, now with `(tag: vX.Y.Z)`. If `git tag` said `already exists`, an old local tag has that name. Delete it with `git tag -d vX.Y.Z`, then tag again.

```powershell
git push origin vX.Y.Z
```

**Expected:** `* [new tag] vX.Y.Z -> vX.Y.Z`. The tag is now on <https://github.com/julien355/esp32-datalogging/tags>.

### 2.2 Where you start from (VPS)

**Where:** `ssh hermes-vps`, user ai, except the steps marked owner.

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** the tag running now, for example `v0.7.0`. Write it down as `<previous-tag>`: it is what you go back to.

```bash
git status
```

**Expected:** `HEAD detached at <previous-tag>` and `nothing to commit, working tree clean` (an untracked `server/.env` is fine). Modified files: someone edited the code on the VPS. Stop and ask the owner.

### 2.3 Backup

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**Expected:** `... backup ok: /srv/arkan-monitoring/backups/data-<date>.tar.gz (<size>)`.

### 2.4 Get the new version

```bash
git fetch --tags
```

```bash
git log -1 --oneline vX.Y.Z
```

**Expected:** the same line as on the PC in 2.1, `<commit> (tag: vX.Y.Z) Release vX.Y.Z: ...`. If the line is different, the tag was moved on GitHub: run `git fetch --tags --force` and check again. Still different: stop and ask the owner.

```bash
git checkout vX.Y.Z
```

**Expected:** `HEAD is now at ... Release vX.Y.Z: ...`.

### 2.5 Anything more than the code?

```bash
git diff --stat <previous-tag> vX.Y.Z -- server/.env.example server/deploy server/docker-compose.yml server/Dockerfile
```

**Expected:** no output. Nothing more to do: go to 2.6. Otherwise, for each file listed:

| File listed | What to do |
|---|---|
| `server/.env.example` | New settings. Run the name check of [tutorial 2, C5 step 3a](tutorials/2-VPS-SETUP.md#c5-updating-to-a-new-tag-and-going-back), then add the missing names to `server/.env` (`nano .env`) with the values the release section of `UPDATING.md` gives |
| `server/deploy/monitoring.caddy` (or `server/deploy/oed/monitoring-oed.caddy` once OED is installed) | The owner keeps a copy of the live file (`sudo cp /opt/edge/sites/monitoring.caddy /opt/edge/monitoring.caddy.before-vX.Y.Z`), installs the new one, validates (`sudo caddy validate --config /etc/caddy/Caddyfile`), and reloads **after** 2.6 ([`UPDATING.md`](UPDATING.md) section 2.5 shows it done for `v0.4.0`) |
| `server/docker-compose.yml`, `server/Dockerfile` | Nothing by hand: 2.6 rebuilds with them. Read the release section for anything it says |
| `server/deploy/backup.sh`, other deploy files | Read the release section |

### 2.6 Rebuild and restart (owner approves)

Every `docker compose` command runs in `/opt/arkan-monitoring/server`.

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

**Expected:** the container `Recreated`, then `Started`. For about 30 s there is no live data on the page. The loggers keep their records on the SD card and send them afterwards, so nothing is lost.

`git checkout` alone changes nothing on the page. The code is copied into the image when it is built, so `--build` is needed.

If the Caddy file changed (2.5), the owner reloads Caddy now:

```bash
sudo systemctl reload caddy
```

### 2.7 Checks

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "X.Y.Z", ...}`, the number of the new tag.

```bash
docker compose ps
```

**Expected:** `Up ... (healthy)` after a minute.

```bash
docker compose logs --tail 20 ingest
```

**Expected:** the logger's `POST /api/v1/ingest` lines with `200`.

In the browser, open <https://arkan-monitoring.duckdns.org/live/adab/> and reload once with Ctrl+F5. Then do the checks of the release section in `UPDATING.md`.

### 2.8 Going back

```bash
cd /opt/arkan-monitoring
```

```bash
git checkout <previous-tag>
```

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

Then run the checks of 2.7 again. A code update does not change the data folder, so going back is safe, unless the release section says the data format changed. If the owner installed a new Caddy file, they put back the `.before-vX.Y.Z` copy, validate and reload.

### 2.9 If something is wrong

| What you see | What to do |
|---|---|
| `fatal: not a git repository` | `/opt/arkan-monitoring` is not a git clone. Stop and ask the owner ([tutorial 2, B11](tutorials/2-VPS-SETUP.md#b11-get-the-code)) |
| `no configuration file provided: not found` | You are not in `/opt/arkan-monitoring/server`: `cd` there and run the command again |
| `/health` gives no answer and `docker compose ps` lists nothing | The container is not running. Run `docker compose up -d --build` in `/opt/arkan-monitoring/server`. **Never** `docker rm -f`: the data is in `/srv/arkan-monitoring/data`, not in the container |
| `/health` still shows the old version | `docker compose up -d --build` was not run after `git checkout`, or was run in another folder |
| The page looks unchanged | The browser kept the old page: Ctrl+F5 |
| You want to clean up old Docker images | Do not run `docker system prune` or `docker image prune`: they act on every service of the VPS. Ask the owner |

## 3. The logger, by cable, from VS Code and PlatformIO

Use this for the bench test of a new firmware, for a logger that cannot be reached over the air, or for a first flash. The settings (WiFi, token, offsets) **are kept**: PlatformIO only writes the program.

First time on this PC? Install Git, VS Code and PlatformIO first: [tutorial 1, A2](tutorials/1-LOGGER-ON-SITE.md#a2-installing-the-software-on-windows). [A4](tutorials/1-LOGGER-ON-SITE.md#a4-building-and-flashing-the-firmware) explains every step below in detail, with what to do when it fails.

### 3.1 Open the project

1. In VS Code, open **File > Open Folder...**, choose `C:\dev\esp32-datalogging\firmware` (the folder that contains `platformio.ini`), then **Select Folder**.
2. Open the PlatformIO terminal: `Ctrl+Shift+P`, type `PlatformIO: New Terminal`, then Enter. A plain terminal does not know `pio` ([A4.2](tutorials/1-LOGGER-ON-SITE.md#a42-open-the-platformio-terminal)).

```powershell
pio --version
```

**Expected:** `PlatformIO Core, version 6.x.x`.

### 3.2 Choose the code to flash

Do part 1 first: the folder must be up to date and clean. Then, in the same terminal:

```powershell
cd C:\dev\esp32-datalogging
```

Then **one** of these:

- **A released firmware** (the tag already exists):

  ```powershell
  git checkout fw-vX.Y.Z
  ```

  **Expected:** `HEAD is now at ...`, with a note about `detached HEAD`. That is normal: you are reading the tagged code, not editing it.
- **A new firmware to bench test**, merged in the default branch but not tagged yet: stay on `ccr-a52c0421-oygp4n` (part 1 already pulled it).
- **A pull request not merged yet:** run `git fetch origin`, then `git checkout <branch-name>`.

Check the version you are about to flash, and write down the commit:

```powershell
Select-String '#define FW_VERSION' firmware\include\config.h
```

**Expected:** a line that ends with `#define FW_VERSION "X.Y.Z"`. It must be higher than what the logger runs now.

```powershell
git log -1 --oneline
```

Write this line in the record sheet. A bench-tested firmware is tagged on **this** commit later (4.1).

### 3.3 Flash

Plug the logger into the PC with the USB-C **data** cable. Close every serial monitor first: only one program can use the port.

```powershell
cd C:\dev\esp32-datalogging\firmware
```

```powershell
pio run -e logger -t upload
```

Use `logger` for `LOG-0001` and every board on the native USB. Use `-e logger-uart` only for a board whose USB-C goes through a CH340 or CP210x chip ([A4.3](tutorials/1-LOGGER-ON-SITE.md#a43-choose-the-build-for-this-board-logger-or-logger-uart)). The record sheet says which build each logger uses.

**Expected:** at the end, `Hash of data verified.` and `[SUCCESS]`. The board restarts on its own with the new firmware.

- `Could not open COM4` or `Access is denied`: a serial monitor still holds the port. Close it and run the upload again.
- `Failed to connect to ESP32-S3`: use the BOOT/RESET trick. Hold **BOOT**, press and release **RESET**, then release **BOOT**. Run the upload again, then press **RESET** after `[SUCCESS]` ([A4.6](tutorials/1-LOGGER-ON-SITE.md#a46-flash-upload)).
- Several boards plugged in: add `--upload-port COM4` (the port shown in Device Manager).

### 3.4 Watch 10 minutes

```powershell
pio device monitor -f esp32_exception_decoder -f time -f log2file
```

If several ports exist, add `-p COM4`. The `log2file` filter keeps everything the logger prints in a file in the `firmware` folder.

Type `status`, then Enter. What you type is not shown until you press Enter.

**Expected:** `Logger LOG-0001, firmware X.Y.Z, ...`. After 10 minutes, `status` shows:
- `up 600 s` or more;
- `Uploads: ok n, failed 0`;
- no restart seen in the monitor.

If it restarted: stop. Keep the `log2file` file, do not tag, and do not send this firmware over the air. Flash the previous release again (3.2 with its `fw-v` tag, then 3.3).

To leave the monitor: `Ctrl+C`.

### 3.5 Put the PC folder back

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git checkout ccr-a52c0421-oygp4n
```

**Expected:** `Switched to branch 'ccr-a52c0421-oygp4n'`. The folder is back on the default branch, as [`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md) expects.

### 3.6 Check on the VPS side

<https://arkan-monitoring.duckdns.org/live/adab/#versions> (or `docker compose exec ingest python tools/manage.py list` on the VPS) shows `fw X.Y.Z` with a fresh last record. The alarm log has **A35 Firmware updated**, marked as flashed by hand.

## 4. The logger, over the air, from a GitHub release

This is the normal way for a logger that is online, at the office or on site. Nobody needs to go there.

### 4.1 Make the release on GitHub (PC)

Only after the bench test of part 3 has passed on the same code.

1. `FW_VERSION` in `firmware/include/config.h` is the new number. It is committed, pushed and merged into the default branch, and CI is green.
2. Tag the commit you bench-tested, the one you wrote down in 3.2. It is on GitHub already: a commit of the default branch or of a pushed branch.

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git tag fw-vX.Y.Z <commit>
```

```powershell
git log -1 --oneline fw-vX.Y.Z
```

**Expected:** the commit you flashed in part 3. Anything else: delete the tag with `git tag -d fw-vX.Y.Z` and stop.

```powershell
git push origin fw-vX.Y.Z
```

3. CI builds both variants and makes the release **Logger firmware X.Y.Z** with four files: `logger-X.Y.Z.bin`, `logger-uart-X.Y.Z.bin`, `bootloader-X.Y.Z.bin` and `partitions-X.Y.Z.bin`. It takes about 2 minutes; you can follow it on the **Actions** page. CI stops if the tag is not `fw-v` followed by `FW_VERSION`.

**Done when:** <https://github.com/julien355/esp32-datalogging/releases> shows the release with its four files.

### 4.2 Send it to the logger (site page)

1. Open <https://arkan-monitoring.duckdns.org/live/adab/#firmware> (**Firmware update** in the side menu). It is shown only to the logins in `ADMIN_USERS`.
2. In the panel of the logger, under **From a GitHub release**, choose `fw-vX.Y.Z: logger-X.Y.Z.bin`. The file of the logger's build is already selected; take `logger-uart-...` only for a `logger-uart` board.
3. Click **Send to LOG-0001**.

**Expected:** `Firmware X.Y.Z offered to LOG-0001.`, then the status line goes from *waiting for the logger* to *installed*:
- **Logger online:** within about a minute.
- **Logger offline:** at its next check after it comes back (every `ota_check_h`, 6 h by default).
- **Logger on the cable:** typing `ota` on its console makes it check at once.

The logger restarts once, and there are about 30 s without readings. Nothing is lost.

The VPS terminal can do the same as this panel: [`OTA.md`](OTA.md) and [`UPDATING.md`](UPDATING.md) section 3, `manage.py publish-fw`.

### 4.3 Check

- <https://arkan-monitoring.duckdns.org/live/adab/#versions> shows `X.Y.Z` running and the time it started.
- The alarm log has **A35 Firmware updated** `... -> X.Y.Z, by remote update (OTA)`.
- On the VPS, `docker compose exec ingest python tools/manage.py list` shows `fw X.Y.Z`.

### 4.4 If it goes wrong

- **The logger went back to the old version by itself** (panel: *rolled back*; alarm log: **A36**). The new firmware restarted 3 times within its first 10 minutes. The logger never takes that version again. Do not send it to other loggers. The fix is a new build with a new `FW_VERSION`.
- **Withdraw a bad release:** on GitHub, open **Releases**, **Logger firmware X.Y.Z**, **Edit**, tick **Set as a pre-release**, add the reason, then **Update release**. The pages then mark it `(pre-release)` (done for 0.4.0, [`UPDATING.md`](UPDATING.md) section 5).
- **Go back to an older version on purpose:** send the older release with **force** ticked, or flash it by cable (part 3).
- **Cancel an offer that is still waiting:** **Withdraw the offer** in the same panel.

More on the panel, the checks the server makes, and the security: [`OTA.md`](OTA.md).
