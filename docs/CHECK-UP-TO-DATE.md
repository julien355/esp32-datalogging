# Where everything is, and how to check it is up to date

One rule: **GitHub is the reference.** Work done on the PC is committed and pushed the same day. If it is not on GitHub, it does not exist.

And before pushing a tag, check which commit it points to: `git log -1 --oneline <tag>`. On 10 November an old local `v0.6.0` on the PC was pushed instead of the release commit (fixed the same day).

## 1. The four places

| Place | Where | What it must hold |
|---|---|---|
| **GitHub** (the reference) | <https://github.com/julien355/esp32-datalogging>, default branch `ccr-a52c0421-oygp4n` | Everything: code, docs, tags, firmware releases |
| **Our computer** (office PC) | `C:\dev\esp32-datalogging`, **one folder only**, a git clone | The same as GitHub, nothing waiting to be pushed |
| **VPS** | `hermes-vps`, folder `/opt/arkan-monitoring` (a git clone, at a tag). Data: `/srv/arkan-monitoring/data` | The newest `v…` tag |
| **Logger** | `LOG-0001`, site `adab` | The newest `fw-v…` release that is not marked pre-release |

**Latest, 10 November 2026:** code `v0.8.0` and firmware `0.5.0` (the Modbus link of each meter, the history pages with two dates and a CSV: [`UPDATING.md`](UPDATING.md) section M), after `v0.7.1` (logins for this platform only, a login limited to one site; it includes `v0.7.0`, the site page in the Arkan design: section L). All of it is merged into the default branch: pull request #9, merge commit `bc2bb84` (it closed #8, #10 and #11 as merged). **Not yet done:** the tags `v0.7.1` (on `ce96ffb`) and `v0.8.0` (on `bc2bb84`), the VPS update, the bench test and the tag `fw-v0.5.0`: the general update, [section 7](#7-general-update-to-do-now-in-order-10-november-2026). Before it: the VPS runs `v0.6.0` (commit `309d57a`); `LOG-0001` runs firmware `0.4.1` (release `fw-v0.4.1`, same commit); `0.4.0` is marked withdrawn (pre-release), never send it.

## 2. GitHub (browser, 1 minute)

1. <https://github.com/julien355/esp32-datalogging/tags>: the newest `v…` tag is what the VPS must run; the newest `fw-v…` is the logger firmware. Tags named `archive/…` are old branches kept for reference (section 6).
2. <https://github.com/julien355/esp32-datalogging/actions>: the newest run on `ccr-a52c0421-oygp4n` is green.
3. <https://github.com/julien355/esp32-datalogging/branches>: only the default branch, plus branches of work in progress (today `claude/great-bell-00lrct`, the firmware with two WiFi networks, not released).

## 3. Our computer (PowerShell)

The folder does not exist yet? Create it once:

```powershell
git clone https://github.com/julien355/esp32-datalogging.git C:\dev\esp32-datalogging
```

Check:

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git fetch origin --tags --prune
```

```powershell
git status
```

**Expected:** `On branch ccr-a52c0421-oygp4n`, `Your branch is up to date with 'origin/ccr-a52c0421-oygp4n'`, `nothing to commit, working tree clean`.

- `Your branch is behind ... by N commits`: run `git pull`.
- Another branch (for example `release-0.4.1` after a bench flash): `git checkout ccr-a52c0421-oygp4n`, then `git pull`.
- Modified files listed: commit and push them, or ask before you go on.
- `needs merge` or `you need to resolve your current index first`: an old merge was left unfinished. Do not resolve it: close VS Code, move the whole folder to `C:\dev\_archive\esp32-datalogging-<date>` (`Move-Item`), clone again (above), then check the archived copy with the command below. Done this way on 10 November 2026.

Is there anything on this PC that GitHub does not have?

```powershell
git log --branches --not --remotes --tags --oneline
```

**Expected:** no output. A line is a commit that exists only on this PC: push it (the 0.4.0 lesson, [`UPDATING.md`](UPDATING.md) section 5).

## 4. VPS (`ssh hermes-vps`)

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** the newest `v…` tag of section 2 (today `v0.8.0`, once tagged).

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.8.0", ...}`.

Older? Update with [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 2, and the release's section in [`UPDATING.md`](UPDATING.md) (today sections L and M; backup first, the owner approves the restart).

## 5. Logger

In the browser (Arkan login): <https://arkan-monitoring.duckdns.org/live/adab/#versions>

**Expected:** `LOG-0001` runs the newest `fw-v…` release (today `0.4.1`; `0.5.0` once released after its bench test, [`UPDATING.md`](UPDATING.md) M5), and its last record is a few minutes old.

Or on the VPS:

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose exec ingest python tools/manage.py list
```

**Expected:** `LOG-0001: fw 0.4.1, last record <a time a few minutes ago, UTC>`.

Older? [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md): part 3 (bench test by cable first), then part 4 (over the air).

## 6. Old copies: archive, do not delete

- **GitHub:** a branch whose pull request is merged becomes a tag `archive/<branch name>`, then the branch is deleted (commands in section 7, step 2). To bring one back: `git push origin archive/<name>:refs/heads/<name>`.
- **Our computer:** only `C:\dev\esp32-datalogging` is used. Any other copy of this project (an older clone, a zip in Downloads or on the Desktop) goes into `C:\dev\_archive\`, with the date in its name, for example `C:\dev\_archive\esp32-datalogging-2026-11-08`.
- **Firmware 0.4.0:** on GitHub, release **Logger firmware 0.4.0**, **Edit**, tick **Set as a pre-release**, add `Withdrawn: restarts every minute behind Caddy. Use 0.4.1.` ([`UPDATING.md`](UPDATING.md) section 5, step 4).
- **VPS (owner):** the hand-made copy of 8 November is no longer used. Archive it next to the data backups, then remove it:

```bash
sudo tar -czf /srv/arkan-monitoring/backups/opt-hand-copy-2026-11-08.tar.gz -C /opt arkan-monitoring.hand-copy-2026-11-08
```

```bash
sudo rm -rf /opt/arkan-monitoring.hand-copy-2026-11-08
```

```bash
ls -d /opt/arkan-monitoring*
```

**Expected:** only `/opt/arkan-monitoring`.

## 7. General update: to do now, in order (10 November 2026)

**What it brings.** The VPS goes from `v0.6.0` to `v0.8.0` in one update. That includes `v0.7.0` (the site page in the Arkan design), `v0.7.1` (logins for this platform only, a technician's login limited to Adab), the history pages with two dates and a CSV of the original records, and the Modbus link of each meter at the top of the open alarms. `LOG-0001` goes from firmware `0.4.1` to `0.5.0` (the logger sends the Modbus link of each meter). What each part needs: [`UPDATING.md`](UPDATING.md) sections M, L and N. The commands, the same for every release: [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md).

**Already done (cloud session, 10 November):** pull request #9 merged into the default branch, merge commit `bc2bb84`. It closed #8 (custom dates and CSV), #10 (Modbus link) and #11 (technician logins) as merged. Checked before the merge: CI green, 43 server tests and 35 simulator tests pass, and both firmware builds pass. A local service with two sites and a login limited to one site answered `302` or `403` on every page and API path of the other site, CSV download included. It showed the meter link sent by a simulated 0.5.0 logger.

A cloud session cannot push tags or delete branches (GitHub access refuses it), and cannot reach the PC, the VPS or the logger. These steps are yours. Tick each one when its **Done when** is true.

| # | Step | Where | Time |
|---|---|---|---|
| 1 | Push the tags `v0.7.1` and `v0.8.0` | PC | 3 min |
| 2 | Archive the merged branches | PC | 2 min |
| 3 | Update the VPS from `v0.6.0` to `v0.8.0` | VPS (owner approves the restart and the Caddy reload) | 30 min |
| 4 | The technician's login | VPS (owner) | 10 min |
| 5 | Bench test firmware 0.5.0 on `LOG-0001` by cable | PC + logger on USB | 20 min |
| 6 | Release firmware 0.5.0 (`fw-v0.5.0`) | PC | 5 min |
| 7 | Archive the old VPS copy (left from section 8) | VPS (owner) | 2 min |
| 8 | Final check: sections 2 to 5 | all | 5 min |

Step 2 after step 1. Steps 4 and 5 after step 3, in any order. Step 6 only after step 5 passed.

**Not in this update:** `claude/great-bell-00lrct`, a firmware change that adds two WiFi networks of equal rank (the logger joins whichever of `wifi_ssid` and `wifi_ssid2` is in range). It is not reviewed or bench tested yet, and it does not change `FW_VERSION`. Its branch has one commit more than its archive tag (`d1a03fa` after `ffb7cbd`), so keep the branch: do not delete it in step 2.

### Step 1. Push the tags `v0.7.1` and `v0.8.0` (PC, PowerShell)

[`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 1 first: the folder on the default branch, up to date and clean.

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

Each tag goes on a named commit, **not** on the newest commit of the branch (documentation commits come after the merge).

```powershell
git log -1 --oneline ce96ffb
```

**Expected:** `ce96ffb Release v0.7.1: logins for this platform only, limited to one site`.

```powershell
git log -1 --oneline bc2bb84
```

**Expected:** `bc2bb84 Release v0.8.0 (firmware 0.5.0) and v0.7.1: Modbus link, history dates and CSV, technician logins, update guide (#9)`.

```powershell
git tag v0.7.1 ce96ffb
```

```powershell
git tag v0.8.0 bc2bb84
```

```powershell
git log -1 --oneline v0.8.0
```

**Expected:** the `bc2bb84` line, now with `(tag: v0.8.0)`. If `git tag` said `already exists`: `git tag -d <tag>`, then tag again.

```powershell
git push origin v0.7.1 v0.8.0
```

**Expected:** `* [new tag] v0.7.1 -> v0.7.1` and `* [new tag] v0.8.0 -> v0.8.0`.

**Done when:** <https://github.com/julien355/esp32-datalogging/tags> lists `v0.8.0` and `v0.7.1`.

### Step 2. Archive the merged branches (PC, PowerShell)

Each branch becomes a tag `archive/<name>`, then the branch is deleted (section 6). All six are merged. The last one is the branch of the cloud session that wrote this section.

```powershell
$old = "claude/affectionate-knuth-l6n5pf","claude/amazing-carson-q6z1lv","claude/compassionate-lovelace-aiyvag","claude/relaxed-cerf-lz6nmi","claude/dreamy-euler-duxu9o","claude/exciting-ritchie-a4bjtk"
foreach ($b in $old) { git tag "archive/$b" "origin/$b"; git push origin "archive/$b"; if ($LASTEXITCODE -eq 0) { git push origin --delete $b } }
```

**Expected:** for each name, `* [new tag] archive/...`, then `- [deleted] ...`.

**Done when:** <https://github.com/julien355/esp32-datalogging/branches> shows only `ccr-a52c0421-oygp4n` and `claude/great-bell-00lrct`.

### Step 3. Update the VPS from `v0.6.0` to `v0.8.0` (`ssh hermes-vps`)

Do it in one update, straight to `v0.8.0`. Follow [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 2, with `<previous-tag>` = `v0.6.0` and `vX.Y.Z` = `v0.8.0`. Its 2.1 is step 1 above. The points below are what this update needs on top, in the order of part 2.

1. **2.2:** `git describe --tags --always` shows `v0.6.0`.
2. **2.3:** the backup.
3. **2.4:** `git log -1 --oneline v0.8.0` shows `bc2bb84 (tag: v0.8.0) Release v0.8.0 (firmware 0.5.0) and v0.7.1: ...`. Then `git checkout v0.8.0`.
4. **2.5:**

```bash
git diff --stat v0.6.0 v0.8.0 -- server/.env.example server/deploy server/docker-compose.yml server/Dockerfile
```

**Expected:** four files: `server/.env.example`, `server/deploy/monitoring.caddy`, `server/deploy/oed/monitoring-oed.caddy`, `server/docker-compose.yml`.

- `.env.example`: one new name, `USER_SITES`. Add the line `USER_SITES=` to `server/.env`, empty for now. The technician's value comes in step 4.
- `docker-compose.yml`: nothing by hand.
- `oed/monitoring-oed.caddy`: nothing, OED is not installed on `hermes-vps`.
- `monitoring.caddy` (owner):
  - First the empty login file for this platform only: [`UPDATING.md`](UPDATING.md) **L3.3**.
  - Then the new Caddy file, with `caddy validate`: [`UPDATING.md`](UPDATING.md) **L3.4**. Name the copy `/opt/edge/monitoring.caddy.before-v0.8.0`. In `v0.6.0` the file was the same as in `v0.7.0`, so the `diff` there expects the same lines.
5. **2.6 (owner approves):** `docker compose up -d --build` in `/opt/arkan-monitoring/server`, then `sudo systemctl reload caddy`.
6. **Checks:**
   - 2.7: `/health` answers `"version": "0.8.0"`, `docker compose ps` shows `healthy`, and the logs show `POST /api/v1/ingest` with `200`.
   - `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8800/live/_ui/arkan-ui.css` answers `200` (N4).
   - `curl -s -u <your-login> https://arkan-monitoring.duckdns.org/api/v1/admin/me` shows `"sites": null` (L4).
   - The `meters` line of M2 to M4 shows `'source': 'values'`, because `LOG-0001` still runs 0.4.1.
   - In the browser, `https://arkan-monitoring.duckdns.org/live/adab/` (Ctrl+F5):
     - the Arkan design, as in the N4 list;
     - **All sites** in the menu, and **Settings** showing `Sites: every site` (L4);
     - on **Live now**, the **Open alarms** card at the top with `Meter EM01 · Modbus connected` (green; red `not connected` if the meter does not answer), marked "from the live values (logger firmware before 0.5.0)";
     - on **Power**, **From … to …** with two calendars, then **Show**. **CSV** downloads `adab-LOG-0001-<from>-to-<to>.csv`, one row per minute, times in UTC.
7. **Going back**, only if something is wrong: the service and the Caddy file go back **together**.
   - `sudo cp /opt/edge/monitoring.caddy.before-v0.8.0 /opt/edge/sites/monitoring.caddy`, then `sudo caddy validate --config /etc/caddy/Caddyfile`.
   - `git checkout v0.6.0`, then `docker compose up -d --build`.
   - The owner reloads Caddy.

**Done when:** `/health` answers `"version": "0.8.0"`, and the Adab page has the Arkan design, the **Open alarms** card with the meter line, and **From … to …** on the history pages.

### Step 4. The technician's login (owner, `ssh hermes-vps`)

After step 3. Follow [`LIVE.md`](LIVE.md#adding-a-technicians-login-owner-on-hermes-vps), steps 1 to 7. Decide two things first:

- **The login name**, for example `tech-adab`. One login per person, so each can be removed alone.
- **Firmware update or not.** A login in `ADMIN_USERS` may send a firmware to the Adab loggers; leave it out and it cannot. Either way, every login can use the **Meter registers** page of its sites. That includes sending a new register table and the meter link settings to the logger, and each change is written in the register history with the login name.

The value of `USER_SITES` (empty since step 3) becomes `tech-adab:adab`.

**Done when:** `curl -s -u tech-adab https://arkan-monitoring.duckdns.org/api/v1/admin/me` shows `"sites": ["adab"]`, and in a private window as `tech-adab`, `https://arkan-monitoring.duckdns.org/live/` lands on the Adab page with no **All sites** in the menu.

### Step 5. Bench test firmware 0.5.0 on `LOG-0001` by cable (PC, logger on USB)

After step 3, so that the site page can show the meter line the logger sends. Follow [`UPDATING.md`](UPDATING.md) M5, steps 1 and 2: `git checkout -B release-0.5.0 v0.8.0`, `pio run -e logger -t upload`, then the serial monitor. [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 3 explains each command and what to do when it fails. Before the upload:

```powershell
git log -1 --oneline
```

**Expected:** the `bc2bb84` line. Write it in the record sheet.

```powershell
Select-String '#define FW_VERSION' firmware\include\config.h
```

**Expected:** `#define FW_VERSION "0.5.0"`.

**Watch 10 minutes.** Expected:
- `firmware 0.5.0` at the boot, and no restart;
- `status` shows `up 600 s` or more, `Uploads: ok n, failed 0`, and a line `Meter EM01 (id 1): ...`. What that line says depends on what is on the RS485 port:
  - the meter simulator on a USB-RS485 adapter ([tutorial 4](tutorials/4-MODBUS-REGISTERS.md)): `answering since ...`;
  - nothing on the port: `NO ANSWER for n reads ...: timeout: ...` (alarm A03 is open, as with 0.4.1);
  - the RS485 pins not set: `RS485 pins not set (pin_rs_tx / pin_rs_rx)`.
- On the site page, the meter line follows within 15 s, **without** "from the live values".

If it restarted: stop. Keep the `log2file` file, and do not do step 6. Flash 0.4.1 again: [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) 3.2 with `fw-v0.4.1`, then 3.3.

Then bring the PC folder back to the default branch: `git checkout ccr-a52c0421-oygp4n`.

**Done when:** 10 minutes without a restart, uploads `failed 0`, and the meter line both on the console and on the site page.

### Step 6. Release firmware 0.5.0 (PC)

Only after step 5 passed. The firmware of `v0.8.0` is the one you flashed in step 5.

```powershell
git tag fw-v0.5.0 bc2bb84
```

```powershell
git log -1 --oneline fw-v0.5.0
```

**Expected:** the `bc2bb84` line, with `(tag: fw-v0.5.0, tag: v0.8.0)`. Anything else: `git tag -d fw-v0.5.0` and stop.

```powershell
git push origin fw-v0.5.0
```

CI builds the firmware and makes the release **Logger firmware 0.5.0**. It stops if the tag and `FW_VERSION` differ.

`LOG-0001` already runs 0.5.0 from the cable in step 5, so there is nothing to send it. The **Firmware update** panel would refuse anyway (`LOG-0001 runs 0.5.0: 0.5.0 is not newer`). The release is for the next loggers, over the air ([`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 4).

**Done when:** <https://github.com/julien355/esp32-datalogging/releases> shows **Logger firmware 0.5.0** with four files: `logger-0.5.0.bin`, `logger-uart-0.5.0.bin`, `bootloader-0.5.0.bin`, `partitions-0.5.0.bin`.

### Step 7. Archive the old VPS copy (owner)

Section 6, the part marked **VPS (owner)**: archive `/opt/arkan-monitoring.hand-copy-2026-11-08`, then remove it.

**Done when:** `ls -d /opt/arkan-monitoring*` shows only `/opt/arkan-monitoring`.

### Step 8. Final check

Run sections 2 to 5 of this guide. Expected:
- the newest tags are `v0.8.0` and `fw-v0.5.0`, and the newest run on the **Actions** page is green;
- the branches are those of step 2;
- the PC folder is clean on the default branch;
- the VPS runs `v0.8.0` (`/health` answers `0.8.0`);
- `LOG-0001` runs `fw 0.5.0` with a fresh last record.

Then write the new state in the status lines: section 1 of this file, the top of [`UPDATING.md`](UPDATING.md), and [`tutorials/README.md`](tutorials/README.md). Commit and push them the same day.

## 8. Earlier list, 10 November 2026 morning (kept for reference)

Steps 1 to 6 were done that morning, and the PC part of step 7. The VPS part of step 7 moved to section 7, step 7, and step 8 is replaced by section 7, step 8.

| # | Step | Where | Time |
|---|---|---|---|
| 1 | ~~Push the tag `v0.6.0`, archive the old branches~~ **Done 10 Nov** | PC | 2 min |
| 2 | ~~Update the VPS to `v0.6.0`~~ **Done 10 Nov** | VPS (owner approves the restart) | 15 min |
| 3 | ~~Bench test firmware 0.4.1 on `LOG-0001` by cable~~ **Done 10 Nov** | PC + logger on USB | 15 min |
| 4 | ~~Release firmware 0.4.1 (`fw-v0.4.1`)~~ **Done 10 Nov** | PC | 5 min |
| 5 | ~~Mark firmware 0.4.0 as withdrawn~~ **Done 10 Nov** | GitHub, browser | 1 min |
| 6 | ~~OTA check back to 6 h~~ **Done 10 Nov** | VPS | 1 min |
| 7 | Archive the old copies: ~~PC~~ **done 10 Nov**; VPS, see section 7 step 7 | PC, VPS (owner) | 5 min |
| 8 | ~~Final check: sections 2 to 5~~ replaced by section 7, step 8 | all | 5 min |

### Step 1. Tag `v0.6.0` and archive the old branches (PC, PowerShell)

**Done on 10 November 2026:** `v0.6.0` points to `309d57a`; the twelve branches below are `archive/…` tags; GitHub keeps only the default branch and the dashboard mockup branch (work in progress). Kept here for reference.

Release `v0.6.0` is merged (commit `309d57a`, CI green) but its tag was never pushed, so the VPS cannot check it out yet.

No folder `C:\dev\esp32-datalogging` on the PC yet? Make it first (section 3, `git clone`).

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git fetch origin --tags --prune
```

```powershell
git tag v0.6.0 309d57a
```

```powershell
git log -1 --oneline v0.6.0
```

**Expected:** a line that starts with `309d57a` (`309d57a (tag: v0.6.0) Release v0.6.0: ...`). If `git tag` said `already exists`, an old local tag has that name: `git tag -d v0.6.0`, then tag again.

```powershell
git push origin v0.6.0
```

**Expected:** `* [new tag] v0.6.0 -> v0.6.0`.

Archive the old branches: each one becomes a tag `archive/<name>`, then the branch is deleted. All are merged except `claude/great-bell-00lrct`, the unreleased "WiFi backup network as a real fallback" firmware change, kept in its archive tag for later.

```powershell
$old = "ccr-169a541e-mdp7e0","ccr-a844a0a4-8zsp0n","claude/charming-johnson-y2gfhc","claude/clever-ptolemy-f4va3r","claude/fervent-newton-gta7t9","claude/festive-maxwell-s545g8","claude/great-bell-00lrct","claude/great-brahmagupta-9uvj1m","claude/lucid-gauss-ng8n5i","claude/practical-cori-ji7fop","fix-from-pc","claude/clever-noether-vlaqge"
foreach ($b in $old) { git tag "archive/$b" "origin/$b"; git push origin "archive/$b"; if ($LASTEXITCODE -eq 0) { git push origin --delete $b } }
```

**Expected:** for each name, `* [new tag] archive/...`, then `- [deleted] ...`.

**Done when:** <https://github.com/julien355/esp32-datalogging/tags> lists `v0.6.0` and twelve `archive/…` tags, and <https://github.com/julien355/esp32-datalogging/branches> shows only `ccr-a52c0421-oygp4n`.

### Step 2. Update the VPS to `v0.6.0` (`ssh hermes-vps`)

**Done on 10 November 2026:** from `v0.5.0` to `v0.6.0`; `/health` answers `0.6.0`, the menu has **Power quality**. Remember: the page changes only after `docker compose up -d --build` in `/opt/arkan-monitoring/server` (the code is copied into the image when it is built; `git checkout` alone changes nothing on the page).

Follow [`UPDATING.md`](UPDATING.md) section A, A2 to A4: write down where you start from, backup, `git fetch --tags`, check that `git log -1 --oneline v0.6.0` starts with `309d57a` (A3.2), `git checkout v0.6.0`, the checks of A3.3, then `docker compose up -d --build` once the owner approves.

**Done when:** `curl -s http://127.0.0.1:8800/health` answers `"version": "0.6.0"`, and the site page <https://arkan-monitoring.duckdns.org/live/adab/> has the menu group **Power quality**.

### Step 3. Bench test firmware 0.4.1 by cable (PC, `LOG-0001` on USB)

**Done on 10 November 2026:** `LOG-0001` was already on 0.4.1 (flashed by cable) and ran 1 h 45 min without a restart, upload backlog 0, SD card OK, outdoor sensor (AM2301, GPIO 1) reading. Its firmware code is the same as in `v0.6.0`.

Follow [`UPDATING.md`](UPDATING.md) section 5, steps 1 and 2: `git checkout -B release-0.4.1 v0.6.0`, `pio run -e logger -t upload`, then watch the serial monitor for 10 minutes.

**Done when:** after 10 minutes, `status` on the console shows `firmware 0.4.1`, `up 600 s` or more, `Uploads: ok n, failed 0`, and no restart was seen. If it restarted: stop here, keep the `log2file` file from the `firmware` folder, and do not do step 4.

Then bring the PC folder back to the default branch:

```powershell
git checkout ccr-a52c0421-oygp4n
```

```powershell
git pull
```

### Step 4. Release firmware 0.4.1 (PC)

**Done on 10 November 2026:** `fw-v0.4.1` on `309d57a`; release **Logger firmware 0.4.1** with its four files.

```powershell
git tag fw-v0.4.1 v0.6.0
```

```powershell
git log -1 --oneline fw-v0.4.1
```

**Expected:** a line that starts with `309d57a` (the firmware code of 0.4.1 is in that commit). Anything else: `git tag -d fw-v0.4.1` and stop.

```powershell
git push origin fw-v0.4.1
```

CI builds the firmware and makes the release (it stops if the tag does not match `FW_VERSION`, 0.4.1).

**Done when:** <https://github.com/julien355/esp32-datalogging/releases> shows **Logger firmware 0.4.1** with four files: `logger-0.4.1.bin`, `logger-uart-0.4.1.bin`, `bootloader-0.4.1.bin`, `partitions-0.4.1.bin` (about 2 minutes after the push; progress on the **Actions** page).

### Step 5. Mark firmware 0.4.0 as withdrawn (GitHub, browser)

**Done on 10 November 2026.** Edit the **0.4.0** release, not 0.4.1: the edit page title must say *Edit Logger firmware 0.4.0*.

**Releases**, **Logger firmware 0.4.0**, **Edit**, tick **Set as a pre-release**, add `Withdrawn: restarts every minute behind Caddy. Use 0.4.1.` to the notes, **Update release**.

**Done when:** the release shows the **Pre-release** label.

### Step 6. OTA check back to 6 h (VPS)

**Done on 10 November 2026:** settings version 2, the logger reported `ota_check_h = 6` after its restart (`boot sw:remote_cfg`). Every `docker compose` command runs in `/opt/arkan-monitoring/server`.

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose exec ingest python tools/manage.py set-config LOG-0001 ota_check_h=@default
```

**Expected:** `settings version ... for LOG-0001: the logger takes it at its next check (15 min, or console 'config')`.

**Done when:** within 15 minutes, `docker compose exec ingest python tools/manage.py show-config LOG-0001` shows `ota_check_h = 6` in the lines reported by the logger.

### Step 7. Archive the old copies

**PC done on 10 November 2026:** the old folder (an unfinished merge from 8 November) is `C:\dev\_archive\esp32-datalogging-2026-11-10`, and `C:\dev\esp32-datalogging` is a fresh clone. VPS copy: see below.

Section 6: other copies on the PC go into `C:\dev\_archive\`; the owner archives and removes `/opt/arkan-monitoring.hand-copy-2026-11-08` on the VPS.

**Done when:** `C:\dev` holds only `esp32-datalogging` and `_archive`; on the VPS, `ls -d /opt/arkan-monitoring*` shows only `/opt/arkan-monitoring`.

### Step 8. Final check

Run sections 2 to 5 of this guide. Everything matches: GitHub, the PC folder, the VPS on `v0.6.0`, `LOG-0001` on `0.4.1`.

From the next release on, only sections 2 to 6 are needed: GitHub first, then the PC folder, then the VPS ([`UPDATING.md`](UPDATING.md)), then the loggers.
