# Where everything is, and how to check it is up to date

One rule: **GitHub is the reference.** Work done on the PC is committed and pushed the same day. If it is not on GitHub, it does not exist.

## 1. The four places

| Place | Where | What it must hold |
|---|---|---|
| **GitHub** (the reference) | <https://github.com/julien355/esp32-datalogging>, default branch `ccr-a52c0421-oygp4n` | Everything: code, docs, tags, firmware releases |
| **Our computer** (office PC) | `C:\dev\esp32-datalogging`, **one folder only**, a git clone | The same as GitHub, nothing waiting to be pushed |
| **VPS** | `hermes-vps`, folder `/opt/arkan-monitoring` (a git clone, at a tag). Data: `/srv/arkan-monitoring/data` | The newest `v…` tag |
| **Logger** | `LOG-0001`, site `adab` | The newest `fw-v…` release that is not marked pre-release |

**Latest, 10 November 2026:** code `v0.6.0` (commit `309d57a`), so the VPS runs `v0.6.0`. Logger firmware `0.4.1`, released as `fw-v0.4.1` after its bench test ([`UPDATING.md`](UPDATING.md) section 5). Never `0.4.0` (withdrawn).

## 2. GitHub (browser, 1 minute)

1. <https://github.com/julien355/esp32-datalogging/tags>: the newest `v…` tag is what the VPS must run; the newest `fw-v…` is the logger firmware. Tags named `archive/…` are old branches kept for reference (section 6).
2. <https://github.com/julien355/esp32-datalogging/actions>: the newest run on `ccr-a52c0421-oygp4n` is green.
3. <https://github.com/julien355/esp32-datalogging/branches>: only the default branch, plus the branch of a pull request still open.

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

**Expected:** the newest `v…` tag of section 2 (today `v0.6.0`).

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.6.0", ...}`.

Older? Update with [`UPDATING.md`](UPDATING.md) section A (backup first, the owner approves the restart).

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

## 7. One time, 10 November 2026: tag `v0.6.0` and archive the old branches (owner, PC)

Release `v0.6.0` is merged (pull request 2, CI green) but its tag was never pushed, so the VPS cannot check it out yet. The cloud session that wrote this guide can only push to its own branch, so these steps are done from the PC. First merge the pull request that adds this guide, then:

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
git push origin v0.6.0
```

**Expected:** `* [new tag] v0.6.0 -> v0.6.0`. The VPS can now update (section 4).

Archive the old branches (each one is a tag before its branch is deleted; all are merged except `claude/great-bell-00lrct`, the unreleased "WiFi backup network as a real fallback" firmware change, kept in its archive tag):

```powershell
$old = "ccr-169a541e-mdp7e0","ccr-a844a0a4-8zsp0n","claude/charming-johnson-y2gfhc","claude/clever-ptolemy-f4va3r","claude/fervent-newton-gta7t9","claude/festive-maxwell-s545g8","claude/great-bell-00lrct","claude/great-brahmagupta-9uvj1m","claude/lucid-gauss-ng8n5i","claude/practical-cori-ji7fop","fix-from-pc","claude/clever-noether-vlaqge"
foreach ($b in $old) { git tag "archive/$b" "origin/$b"; git push origin "archive/$b"; if ($LASTEXITCODE -eq 0) { git push origin --delete $b } }
```

**Expected:** for each name, `* [new tag] archive/...`, then `- [deleted] ...`. Then section 2, step 3: only `ccr-a52c0421-oygp4n` is left.
