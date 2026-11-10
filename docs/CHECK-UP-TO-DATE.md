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

**Latest, 10 November 2026:** code `v0.7.1` (logins for this platform only, a login limited to one site; it includes `v0.7.0`, the site page in the Arkan design; to install: [`UPDATING.md`](UPDATING.md) section L). Checked the same day before it: the VPS runs `v0.6.0` (commit `309d57a`); `LOG-0001` runs firmware `0.4.1` (release `fw-v0.4.1`, same commit); `0.4.0` is marked withdrawn (pre-release), never send it.

## 2. GitHub (browser, 1 minute)

1. <https://github.com/julien355/esp32-datalogging/tags>: the newest `v…` tag is what the VPS must run; the newest `fw-v…` is the logger firmware. Tags named `archive/…` are old branches kept for reference (section 6).
2. <https://github.com/julien355/esp32-datalogging/actions>: the newest run on `ccr-a52c0421-oygp4n` is green.
3. <https://github.com/julien355/esp32-datalogging/branches>: only the default branch, plus branches of work in progress (for example the dashboard mockup).

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

**Expected:** the newest `v…` tag of section 2 (today `v0.7.0`).

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.7.1", ...}`.

Older? Update with [`UPDATING.md`](UPDATING.md) section L (backup first, the owner approves the restart).

## 5. Logger

In the browser (Arkan login): <https://arkan-monitoring.duckdns.org/live/adab/#versions>

**Expected:** `LOG-0001` runs the newest `fw-v…` release (today `0.4.1`), and its last record is a few minutes old.

Or on the VPS:

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose exec ingest python tools/manage.py list
```

**Expected:** `LOG-0001: fw 0.4.1, last record <a time a few minutes ago, UTC>`.

Older? [`UPDATING.md`](UPDATING.md) section 5 (bench test by cable first, then over the air) and section 3.

## 6. Old copies: archive, do not delete

- **GitHub:** a branch whose pull request is merged becomes a tag `archive/<branch name>`, then the branch is deleted (commands in section 7). To bring one back: `git push origin archive/<name>:refs/heads/<name>`.
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

## 7. To do now, in order (10 November 2026)

The cloud session that wrote this guide could not push tags, delete branches or reach the PC and the VPS, so these steps are yours. Tick each one when its **Done when** is true.

| # | Step | Where | Time |
|---|---|---|---|
| 1 | ~~Push the tag `v0.6.0`, archive the old branches~~ **Done 10 Nov** | PC | 2 min |
| 2 | ~~Update the VPS to `v0.6.0`~~ **Done 10 Nov** | VPS (owner approves the restart) | 15 min |
| 3 | ~~Bench test firmware 0.4.1 on `LOG-0001` by cable~~ **Done 10 Nov** | PC + logger on USB | 15 min |
| 4 | ~~Release firmware 0.4.1 (`fw-v0.4.1`)~~ **Done 10 Nov** | PC | 5 min |
| 5 | ~~Mark firmware 0.4.0 as withdrawn~~ **Done 10 Nov** | GitHub, browser | 1 min |
| 6 | ~~OTA check back to 6 h~~ **Done 10 Nov** | VPS | 1 min |
| 7 | Archive the old copies (PC and VPS) | PC, VPS (owner) | 5 min |
| 8 | Final check: sections 2 to 5 | all | 5 min |

Steps 2 and 3 do not depend on each other. Step 4 only after step 3 passed.

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
