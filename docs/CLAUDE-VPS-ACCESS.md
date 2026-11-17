# Connecting the Claude chats to hermes-vps: plan

Status: **DRAFT v0.1, 17 November 2026. Nothing built yet; to approve** (section 7).

Goal: the Claude sessions of this project see the running service on `hermes-vps` directly, instead of handing every check and every update back to you as a list of commands ([`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md) section 7: "A cloud session ... cannot reach the PC, the VPS or the logger").

## 1. Where we stand (checked from a cloud session, 17 November 2026)

| Check | Result | What it means |
|---|---|---|
| `https://arkan-monitoring.duckdns.org/live/` | `401` | HTTPS reaches the VPS; Caddy asks for a login, as it should |
| TCP port 22 of the VPS, and of `github.com` as a control | refused, both | Cloud sessions cannot open SSH at all. Only HTTPS leaves the container, through Anthropic's proxy |
| The cloud environment | `Default`, network unrestricted, no secrets | Shared by the sessions of every repository you use |
| This GitHub repository | public | Anything written in an Actions log is public |
| Folders of your computers that a cloud session can use (Remote Control) | none | A cloud session cannot attach the VPS as a machine today |

What the service already gives over HTTPS, behind the login: `/health` (version), `/api/v1/status` (every logger: last record, firmware), live values, alarms, firmware versions, history, original records, power quality, weather. What is missing for operations: the service log, the remote settings (`manage.py show-config`), the logger events, disk and memory.

One gap: every login can send a register table and meter settings to a logger today ([`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md) step 4). A login for Claude must not.

## 2. The plan in one view

Two lanes, in this order. Lane 1 lets the chats **read** the VPS; lane 2 lets a session **act** on it, with your approval for each change.

| | **Lane 1: cloud sessions read the VPS** | **Lane 2: a Claude session on the VPS** |
|---|---|---|
| How | Cloud sessions call the service's HTTPS API with their own **read-only login** | Claude Code runs on `hermes-vps` as user `ai`, in `/opt/arkan-monitoring`. You chat with it from the Claude app (browser or phone) through **Remote Control** |
| It can | Check the version and health, every logger, alarms, data, the service log, the logger settings; check that an update went well; analyse the real data | What user `ai` can do: `git fetch` and `git checkout` of a tag, `docker compose`, `manage.py`, the logs, the data folder |
| It cannot | Change anything (`403` on every POST); no shell | `sudo`: Caddy files, Caddy reloads and `/opt/edge` stay yours |
| Secret | A Caddy login, saved as a **network secret** of the cloud environment. Anthropic's proxy adds it to requests to `arkan-monitoring.duckdns.org` only; the chat never sees it | Your Claude sign-in, in `/home/ai/.claude` on the VPS |
| Your approvals | None needed: it only reads | Every command that is not on its read-only list asks you in the app. Your tap is the owner's go of PLAN.md §4.3 |
| Effort | One small release (`v0.8.1`), 20 min on the VPS, 5 min in the Claude app | 30 min on the VPS |
| Runs | Always | Only when you start it (RAM, exposure) |

Ruled out:
- **SSH from cloud sessions:** blocked (section 1), and a private key would have to sit in the cloud container.
- **GitHub Actions as an SSH bridge** (a session starts a workflow that logs in to the VPS): the repository is public, so the VPS output would land in public logs; SSH would also have to accept GitHub's runners.
- **VPN (Tailscale, WireGuard) inside the cloud container:** only HTTPS leaves it.

## 3. Lane 1: cloud sessions read the VPS

### 3.1 Release `v0.8.1` (cloud session, one pull request)

1. **`READONLY_USERS`** in `server/.env`, the same pattern as `ADMIN_USERS` and `USER_SITES`: the logins listed get every GET of their sites and `403` on every POST (register table, meter settings, firmware). If a login is also in `ADMIN_USERS`, read-only wins and the service writes a warning line at start. `/api/v1/admin/me` gains `"readonly": true/false`.
2. **Read-only operations endpoints**, for logins that see every site (not the logins limited by `USER_SITES`, so a technician never reads the service log):

| Path | Gives | Same as, on the VPS |
|---|---|---|
| `GET /api/v1/ops/log?lines=200` | The last lines of the service log, kept in memory (the last 2,000 lines). No tokens, as today | `docker compose logs --tail 200 ingest` |
| `GET /api/v1/ops/config/<device>` | The settings asked and the settings reported by the logger | `manage.py show-config <device>` |
| `GET /api/v1/ops/events/<device>?lines=100` | The last lines of the logger's `events.jsonl`: boots, gaps, setting changes, OTA | `tail` of the file |
| `GET /api/v1/ops/host` | Service version and uptime, container memory used and its limit, data folder size, free disk | `docker stats --no-stream`, `df -h`, `du -sh` |

3. The login name in the service log line of every `/api/v1/ops/*` call and of every refused POST, so the log shows who asked what.
4. Tests in `server/tests/test_ingest.py`: a read-only login gets `200` on the GETs and `403` on each POST path; a `USER_SITES` login gets `403` on `/api/v1/ops/*`.
5. **`CLAUDE.md` at the root of the repository** (lane 2 reads it too): where everything is, the house rules of PLAN.md §4.3, and how a session looks at the VPS (`curl -s https://arkan-monitoring.duckdns.org/health` and the paths above, never a password on the command line).
6. [`UPDATING.md`](UPDATING.md): a section for `v0.8.1` (one new `.env` name, no Caddy change: the login goes into `monitoring-users.caddy`, which the Caddy file already imports).

**Done when:** CI green, the pull request merged, and you have pushed the tag `v0.8.1` from the PC (cloud sessions cannot push tags).

### 3.2 VPS (owner, 20 min, `ssh hermes-vps`)

1. Update to `v0.8.1` as for every release: [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 2 and the new `UPDATING.md` section.
2. Claude's login: [`LIVE.md`](LIVE.md#adding-a-technicians-login-owner-on-hermes-vps) steps 1 to 3 and 5, with these differences:
   - a name such as `claude-ops` (the real name stays out of git, as for every login);
   - the password goes into the password manager only. You type it once more in step 3.3 below, on a secure card, never in a chat;
   - in `server/.env`: `READONLY_USERS=<the login>`. Not in `ADMIN_USERS`, not in `USER_SITES` (it sees every site, read-only).
3. **The owner approves** `docker compose up -d` and `sudo systemctl reload caddy`.

**Done when**, from the PC:
- `curl -s -u <the login> https://arkan-monitoring.duckdns.org/api/v1/admin/me` shows `"admin": false`, `"sites": null`, `"readonly": true`;
- the same login on a POST (for example the register check of `LOG-0001`) answers `403`.

### 3.3 Claude app (owner, 5 min)

1. **A cloud environment of its own for this repository**, named `esp32-datalogging`, personal, with the same network as today. Not `Default`: every session on your other repositories uses `Default`, and the VPS login must only go out from the sessions of this project. A cloud session proposes it; you approve one card.
2. **The login as a network secret** for the host `arkan-monitoring.duckdns.org`, type username and password. The session asks for it on a secure card; you type it there.
3. New sessions for this repository start in that environment.

**Done when:** in a new session, `curl -s https://arkan-monitoring.duckdns.org/health` answers `{"ok": true, "version": "0.8.1", ...}`, with no password anywhere in the command.

### 3.4 What changes for you after lane 1

- [`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md) sections 4 and 5 (VPS version, logger firmware, last record): the session does them itself.
- After you run an update, "check the VPS" is enough: the session reads `/health`, `ops/log`, `ops/host` and the logger status and says whether the update went well.
- Questions on the data (yesterday's peak, a dip at 14:00, a logger offline since when) are answered from the real files, not from screenshots.
- Commands that change the VPS stay with you, or go to lane 2.

## 4. Lane 2: a Claude session on the VPS

### 4.1 How it works

Claude Code (the command-line version) runs on `hermes-vps` as user `ai`, started with `claude remote-control` in `/opt/arkan-monitoring`. The session then shows up in the Claude app, on the web and on the phone, and you chat with it from there. It runs the commands on the VPS itself: no SSH from outside, no key leaves the VPS. It reads the repository's `CLAUDE.md` (lane 1, step 5) from the tag that is checked out.

### 4.2 Its rules (in `CLAUDE.md`, and enforced by its settings where possible)

- No `sudo`. Caddy files, Caddy reloads and anything in `/opt/edge` or `/etc` stay with the owner: the session prints the command, you run it.
- Never commits or pushes from the VPS: GitHub is the reference, the VPS only checks out tags.
- Leaves the Hub, the CMMS and Hermes alone.
- Asks before every live change: `docker compose up`, `restart`, `stop`, `start`; `git checkout`; `manage.py set-config`, `set-registers`, `publish-fw`, `rotate-token`, `disable-device`, `backfill`, `alarms --rebuild`.
- Updates follow [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 2 and the release's [`UPDATING.md`](UPDATING.md) section step by step, backup first, and stop at every step marked owner.

Draft of `/home/ai/.claude/settings.json` (outside the repository, so a `git checkout` never changes it; checked line by line when lane 2 is set up):

```json
{
  "permissions": {
    "defaultMode": "default",
    "allow": [
      "Bash(git describe:*)", "Bash(git log:*)", "Bash(git status)", "Bash(git fetch:*)", "Bash(git diff:*)",
      "Bash(docker compose ps:*)", "Bash(docker compose logs:*)", "Bash(docker stats --no-stream:*)",
      "Bash(docker compose exec ingest python tools/manage.py list)",
      "Bash(docker compose exec ingest python tools/manage.py show-config:*)",
      "Bash(curl -s http://127.0.0.1:8800/health)",
      "Bash(free -h)", "Bash(df -h:*)"
    ],
    "deny": [
      "Bash(sudo:*)", "Bash(git push:*)", "Bash(git commit:*)",
      "Bash(docker compose down:*)", "Bash(docker system prune:*)", "Bash(rm -rf:*)",
      "Edit(//opt/edge/**)", "Edit(//etc/**)", "Write(//opt/edge/**)", "Write(//etc/**)"
    ]
  }
}
```

These rules keep the session to its job. They are not the security boundary: user `ai` is in the `docker` group, which can do on the VPS what root can. So the session always runs in the mode that asks, never in an auto-approve mode.

### 4.3 Setup (owner, 30 min, `ssh hermes-vps` as `ai`)

1. Memory first: `free -h`. Claude Code takes a few hundred MB while it runs; measure it on the first run and write it in [`VPS-MEMORY.md`](VPS-MEMORY.md). If memory is short, start it only for update windows (proposed anyway).
2. Install for user `ai`, without `sudo` (it goes into `~/.local/bin`): `curl -fsSL https://claude.ai/install.sh | bash`, then `claude --version`.
3. Sign in once: `claude`, then `/login`; open the link in your browser and paste the code back. Then `chmod 700 ~/.claude`.
4. Write `~/.claude/settings.json` (section 4.2).
5. Check that `ai` cannot use `sudo` without a password: `sudo -n true` must answer `a password is required`.
6. Start it: `tmux new -s claude`, `cd /opt/arkan-monitoring`, `claude remote-control`. Leave tmux with Ctrl+B then D; the session keeps running and shows up in the Claude app.
7. Stop it after the work: `tmux attach -t claude`, Ctrl+C, `exit`.

**Done when:** from the Claude app on your phone, the VPS session answers "which version runs?" with the tag from `git describe` and the version from `/health`, and refuses `sudo ls`.

### 4.4 A release after lane 2

1. A cloud session prepares the release and its [`UPDATING.md`](UPDATING.md) section (as today).
2. You push the tag from the PC (as today).
3. In the VPS session: "update to `vX.Y.Z`, HOW-TO-UPDATE part 2". It makes the backup, fetches, checks the tag's commit, checks out, compares `.env.example` and the deploy files, and **asks you** before `docker compose up -d --build`.
4. If the Caddy file changed, it prints the `sudo` commands; you run them and approve the reload (as today).
5. It checks `/health`, the logs and the logger status, and writes the result for the status lines of [`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md), which a cloud session then commits.

## 5. Order and owners

| # | Step | Who | Where | Time |
|---|---|---|---|---|
| 1 | Approve this plan and the choices of section 7 | you | | |
| 2 | Release `v0.8.1`: `READONLY_USERS`, ops endpoints, `CLAUDE.md`, tests (3.1) | cloud session | pull request | one session |
| 3 | Push the tag `v0.8.1` | you | PC | 3 min |
| 4 | VPS on `v0.8.1`, Claude's login (3.2) | you (owner) | VPS | 20 min |
| 5 | Cloud environment `esp32-datalogging` and the network secret (3.3) | you, from a cloud session | Claude app | 5 min |
| 6 | First check from a new session: CHECK-UP-TO-DATE sections 4 and 5 done by the session | cloud session | | 5 min |
| 7 | Lane 2 setup (4.3), if chosen | you (owner) | VPS | 30 min |
| 8 | Next release done with lane 2 (4.4) | you + VPS session | Claude app | as any release |

Lane 2 does not depend on lane 1, but it uses the `CLAUDE.md` of step 2, so it comes after it.

## 6. Later, only if needed: ordinary claude.ai chats

Lane 1 works in Claude Code sessions. Ordinary chats on claude.ai (for example the chats of a claude.ai Project) cannot use a network secret. For them: a small MCP server on the VPS with the same read-only calls (status, alarms, history, log), added as a custom connector in the claude.ai settings. A custom connector signs in with OAuth, not with the Caddy password, so most of the work is that sign-in. Worth it only if these questions often come up outside Claude Code.

## 7. Choices for you

1. **Claude's login:** every site, read-only (proposed), or limited to some sites with `USER_SITES`.
2. **Lane 2:** yes or not yet. If yes, started only for update windows (proposed) or always on.
3. **Lane 3 (section 6):** not now (proposed).

## 8. Risks

| Risk | Mitigation |
|---|---|
| Claude's login leaks | Read-only (`403` on every POST); one login, removed with one line in `monitoring-users.caddy`; never in git, in a chat or in an environment variable: only in the password manager and the cloud environment's network secrets |
| Anthropic's proxy decrypts the HTTPS on the way (TLS is re-terminated there) | The same as for everything else the sessions fetch; only the read-only login passes there |
| The VPS session runs a wrong command | Every live command asks you first; deny list; no `sudo`; backup first (HOW-TO-UPDATE part 2); started only for the work |
| User `ai` can do what root can through Docker | The session never runs in an auto-approve mode on the VPS |
| Your Claude sign-in stored on the VPS | `~/.claude` readable by `ai` only; stop the session after use; `/logout` if more people get `ai` access |
| RAM on a shared VPS | Measured on the first run; started only when needed ([`VPS-MEMORY.md`](VPS-MEMORY.md)) |
| The service log over HTTPS shows IP addresses and paths | No tokens are logged (as today); only logins that see every site may read it |
