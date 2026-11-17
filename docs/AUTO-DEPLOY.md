# Automatic deploy to the VPS, without the PC: plan

Status: **DRAFT v0.2, 17 November 2026. Nothing built yet; to approve** (section 7).
v0.2 replaces v0.1 ("Connecting the Claude chats to hermes-vps"), after the owner's answer: the office PC is broken, so the deploy over SSH from the PC must go; it should not need a manual push anyway; and **Claude Code now runs on the VPS, connected to the Claude app** (Remote Control).

## 1. Today and the target

Today ([`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 2): you merge on GitHub, then from the PC you tag and push the tag, then over SSH from the PC you back up, fetch, check out, compare, rebuild and check. Two of those three steps need the PC.

**Target: you merge the release pull request on GitHub (on the phone). Within about 5 minutes the VPS runs it and has checked it, or it has gone back to the previous version by itself and says why. No PC, no SSH, no command to type.**

| Step | Today | Target |
|---|---|---|
| Merge the release pull request | you, GitHub | **you, GitHub: the only tap** |
| Tag `vX.Y.Z` | you, PC | GitHub Actions, once the tests pass |
| Backup, fetch, checkout, compare, rebuild, checks | you, SSH from the PC | **the deployer on the VPS**, every 5 minutes, user `ai` |
| Going back if the new version does not start | you | the deployer, by itself |
| Caddy file, new `.env` values, data format change | you and the owner | the deployer **stops and waits**; the Claude session on the VPS does the user-level part, the owner the `sudo` part |
| Knowing it worked | browser and terminal | a line on the **Firmware versions** page, and WhatsApp through Hermes once the route exists |

## 2. How it works

```
cloud session: release pull request (VERSION bumped, UPDATING.md section)
      |  you merge it (phone)
      v
GitHub Actions: tests green -> tag v0.8.2 on that commit
      |  the VPS pulls; nothing on GitHub can reach into the VPS
      v
hermes-vps, crontab of ai, every 5 min: arkan-auto-deploy
   a newer v* tag?  -> checks -> backup -> checkout -> docker compose up -d --build -> /health shows the new version?
        yes: done, one line in the deploy log (Firmware versions page)
        no:  back to the previous tag, rebuilt, the tag marked failed (never retried), one line in the log
   a manual step in this release?  -> nothing changed, "waiting" in the log
        -> you, in the Claude app, to the VPS session: "finish the v0.8.2 update"
```

### 2.1 Merge, then tag (GitHub Actions)

A new CI job, `tag-release`, on pushes to the default branch only, after the jobs `firmware`, `server` and `tools` pass:
- reads `VERSION` in `server/app/server.py`;
- if the tag `v<VERSION>` does not exist yet, tags this commit and pushes the tag (the workflow's own token, `contents: write`);
- a merge that does not change `VERSION` (docs, firmware only) makes no tag; a red CI makes no tag; an existing tag is never moved.

This replaces the tag step of HOW-TO-UPDATE 2.1, and its rule "the tag goes on the named commit": the tag lands on the first green commit of the default branch with that version, which is the release merge.

**Firmware is not part of it.** A `fw-v` tag still comes only after a bench test (CHECK-UP-TO-DATE step 5). Without the PC, that tag is made on GitHub: **Releases, Draft a new release**, new tag `fw-vX.Y.Z` on the tested commit. The existing `release` job then adds the four files to that release (`ci.yml` already handles a release made on that page).

### 2.2 The deployer on the VPS

`server/deploy/auto-deploy.sh`, kept in the repository and tested in CI like the rest of the code. It is installed as a copy, `/home/ai/bin/arkan-auto-deploy`, so a `git checkout` never swaps the script while it runs. Line in the crontab of `ai`:

```
*/5 * * * * /home/ai/bin/arkan-auto-deploy >> /srv/arkan-monitoring/backups/deploy.log 2>&1
```

No `sudo`, no open port, no GitHub secret: the repository is public, so `git fetch` needs no login, and user `ai` owns `/opt/arkan-monitoring` and `/srv/arkan-monitoring/backups` (`setup-vps.sh`).

Each run does the steps of HOW-TO-UPDATE part 2, in that order:

| # | Step | It stops, changing nothing, when |
|---|---|---|
| 0 | One run at a time (a lock). The **hold file** `/home/ai/.arkan-deploy/hold` stops everything | the hold file exists |
| 1 | `git ls-remote --tags origin 'v*'`: is there a version tag newer than the one running? (`archive/...` ignored) | nothing newer, or that tag is marked failed |
| 2 | `git fetch --tags` (never `--force`); the tag must be in the history of the default branch | a tag was moved on GitHub; the tag is not on the default branch |
| 3 | Where it starts (2.2): `git describe` gives a tag, no tracked file modified (`server/.env` is not tracked), `/health` answers the running version | modified files; the service is already unhealthy (it does not update a sick service) |
| 4 | More than the code? (2.5) | the release has a file `server/deploy/hold/vX.Y.Z.md` (its manual steps); `server/deploy/monitoring.caddy` changed; `.env.example` has a setting name that `server/.env` lacks |
| 5 | Backup: `server/deploy/backup.sh` (2.3) | the backup failed |
| 6 | `git checkout vX.Y.Z`, then `docker compose up -d --build` (2.4, 2.6) | |
| 7 | Checks for up to 3 minutes (2.7): `/health` shows the new version, `docker compose ps` shows `healthy` | |
| 8 | If 7 failed: `git checkout <previous tag>`, `docker compose up -d --build`, checks again; the new tag is marked failed, never retried (2.8) | |
| 9 | One line in `/srv/arkan-monitoring/data/deploy.jsonl`: time, from, to, result, reason | |

It also:
- has `--dry-run`, which prints what it would do and changes nothing;
- skips the nightly backup window (02:15 to 02:45 server time);
- never touches Caddy, Hermes, the Hub, the CMMS or other containers, and never runs `docker system prune` or `docker image prune` (HOW-TO-UPDATE 2.9);
- writes "new deployer in vX.Y.Z" in the log when the script in the repository changed; it does not replace itself. You then ask the VPS session to install it.

### 2.3 Knowing what happened

- **Firmware versions** page (`/live/adab/#versions`), a new block **Service updates**: the last 10 lines of the deploy log. On the phone, in the browser.
- Optional: one WhatsApp message per deploy through Hermes, on the webhook route PLAN.md §5.3 plans for the alarms, once the owner has added it.
- The VPS session, if asked "what did the deployer do?", reads the log.

### 2.4 The Claude session on the VPS

It is not needed for a normal release: the deployer runs without it, even when the session is not running. Its job:
- **Once:** the setup (section 4).
- **When the deployer waits or went back:** "finish the vX.Y.Z update". It reads the deploy log and the release's section in [`UPDATING.md`](UPDATING.md), does the steps user `ai` can do (new `.env` names with the values the section gives; it asks you for anything secret), and writes out the `sudo` commands for the owner.
- **Going back by hand**, if a release starts but behaves badly: "go back to v0.8.1". It creates the hold file first, so the deployer does not bring the newer version back 5 minutes later, then follows HOW-TO-UPDATE 2.8.
- **Questions:** is the VPS healthy, what does the log say, how much memory and disk is left.

Its rules (in the repository's `CLAUDE.md`, section 3):
- never edits files in `/opt/arkan-monitoring`: a modified file stops the deployer, and fixes come through GitHub;
- never commits or pushes from the VPS;
- no `sudo`; leaves the Hub, the CMMS and Hermes alone;
- asks you before every live change (`docker compose up`, `restart`, `stop`; `git checkout`; `manage.py set-config`, `set-registers`, `publish-fw`, `rotate-token`, `disable-device`, `backfill`, `alarms --rebuild`).

User `ai` is in the `docker` group, which can do on the VPS what root can. The permission prompts are what keep the session to its job, so it never runs in an auto-approve mode there.

Today the session works in `~/ai-workspace`. It needs one line in its notes pointing to this project: "monitoring platform: `/opt/arkan-monitoring`, read its `CLAUDE.md` first".

### 2.5 The house rule that changes (PLAN.md §4.3)

Today: "Caddy reloads and container restarts are live changes: the owner approves each one."
Proposed: **"Merging a release pull request is the owner's approval of the restart that follows. The VPS deploys only `v` tags made by CI. Caddy changes, new settings and data format changes stay manual: the release says so in `server/deploy/hold/vX.Y.Z.md` and the deployer waits."**

## 3. Release `v0.8.1` (one cloud session, one pull request)

1. `.github/workflows/ci.yml`: the job `tag-release` (2.1).
2. `server/deploy/auto-deploy.sh` with `--dry-run` (2.2). CI tests it on a throwaway git repository with two tags and stand-ins for `docker` and `curl`. It must deploy a newer tag; stop on a hold file, a Caddy change, a missing `.env` name, a modified file and a tag not on the default branch; go back when `/health` does not show the new version; and not retry a failed tag. Plus `shellcheck`.
3. `/api/v1/versions/<site>` and the Firmware versions page: the block **Service updates** (2.3), with a test.
4. `CLAUDE.md` at the root of the repository:
   - for cloud sessions, the release checklist: bump `VERSION`, write the `UPDATING.md` section, and add `server/deploy/hold/vX.Y.Z.md` when the release has a manual step;
   - for the VPS session, the rules of 2.4.
5. Docs: HOW-TO-UPDATE part 2 (automatic; the manual steps kept for held releases and for going back by hand); CHECK-UP-TO-DATE (the PC is out of the VPS path); an `UPDATING.md` section for `v0.8.1` (installing the deployer, section 4 below); PLAN.md §4.3 (2.5).
6. `VERSION = "0.8.1"`.

**Done when:** CI green and you merge. **CI then makes the tag `v0.8.1` by itself:** the first proof of 2.1, still without the PC.

## 4. Setup on the VPS (the VPS Claude session; you approve in the app; about 20 min)

`v0.8.1` is the last release installed by hand, and the VPS session does it, so the PC is not needed for this either.

1. In the Claude app, to the VPS session: "Update the monitoring platform to v0.8.1 with docs/HOW-TO-UPDATE.md part 2, then install the deployer as the v0.8.1 section of docs/UPDATING.md says." It runs 2.2 to 2.7 and **asks you** before `docker compose up -d --build`.
2. Install, as `ai`:
   - `mkdir -p ~/bin ~/.arkan-deploy`;
   - `install -m 755 /opt/arkan-monitoring/server/deploy/auto-deploy.sh ~/bin/arkan-auto-deploy`;
   - `~/bin/arkan-auto-deploy --dry-run`, expected: `v0.8.1 running, nothing newer`.
3. The crontab line of 2.2 (`crontab -e` as `ai`, no `sudo`). It asks you first.
4. Optional, owner: the Hermes webhook route for the WhatsApp message (2.3).

**Done when:** the Firmware versions page shows `v0.8.1` under **Service updates**, the dry run has nothing to do, and `crontab -l` shows the line.

**First real test:** the next release, `v0.8.2`, kept small. Merge it on the phone and watch the page: it should show `v0.8.2` within 5 to 10 minutes. Section 6 is a good candidate for it.

## 5. What still needs a computer

| Task | Without the PC |
|---|---|
| VPS release | automatic (this plan) |
| Tag `fw-vX.Y.Z` after a bench test | GitHub on the phone: Releases, Draft a new release (2.1) |
| Firmware to a logger over the air | the site page, **Firmware update** (as today) |
| **Firmware bench test by cable** (CHECK-UP-TO-DATE step 5, still to do for 0.5.1) | **needs a computer with USB and PlatformIO.** Blocked until a computer is back |
| Owner `sudo` steps (Caddy file and reload) | SSH from the tablet, or choice 2 of section 7 |

## 6. Optional, later: cloud sessions read the VPS

From v0.1: a read-only login for Claude (`READONLY_USERS`, `403` on every POST) and read-only endpoints `/api/v1/ops/*` (service log, logger settings, events, memory and disk), saved as a network secret of a cloud environment kept for this repository. Anthropic's proxy adds the login to requests to `arkan-monitoring.duckdns.org` only, and the chat never sees it. The coding session could then check its own release once it is deployed. **Not needed for the deploys.**

## 7. Choices for you

1. **Deploy on merge**, which changes PLAN.md §4.3 (2.5): yes (proposed).
2. **Caddy changes:**
   - (a) `sudo` stays with the owner, over SSH from the tablet (proposed);
   - (b) one narrow `sudo` rule for user `ai`, allowing a single root-owned script. The script installs the Caddy file from the checked-out tag, keeps the old file, validates, reloads, and puts the old file back if validation fails. The VPS session could then do it after you approve in the app.
3. **Notification:** the Firmware versions page (proposed for `v0.8.1`); WhatsApp through Hermes once the owner adds the route.
4. **When it deploys:** any time except the backup window (proposed), or only in working hours (for example 10:00 to 16:00 WITA), when someone can look at the page.

## 8. Risks

| Risk | Mitigation |
|---|---|
| A bad release goes live by itself | The tests pass before any tag; a backup before every deploy; the deployer goes back by itself if `/health` does not show the new version; the hold file stops everything |
| A release starts but behaves wrongly (a page broken, an alarm wrong) | `/health` cannot see that, as today. The loggers keep their records on the SD card. "Go back to vX.Y.Z" to the VPS session (2.4) |
| A tag that should not be deployed | Only CI makes `v` tags; the deployer takes only tags in the default branch's history, never a moved tag. Keep two-factor sign-in on the GitHub account, and protect the default branch (pull request and green CI required) |
| The deployer itself has a bug | Tested in CI; `--dry-run`; it never replaces itself; the hold file; the VPS session can fix it |
| Old Docker images fill the disk | One unnamed image per release (a few tens of MB). The VPS session checks `df -h` on request; cleanup stays with the owner |
| The Claude session on the VPS runs a wrong command | Not needed for normal releases; asks before every live change; no `sudo`; never in an auto-approve mode |
