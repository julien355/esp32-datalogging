# Updating the VPS and the loggers

How a new version of this repository reaches `hermes-vps` and the loggers. **Newest: firmware `0.5.1`** (section W, below, the loggers only): `wifi_ssid` and `wifi_ssid2` become two networks of equal rank, for a logger moved between two sites; it joins the one in range and stays on it until the link drops. **Next release: VPS `v0.8.0` and firmware `0.5.0`** (section M): the Modbus link of each meter, connected or not, always shown at the top of the open alarms on the site page, and the history pages with two dates and a CSV of the original records. **Before it, VPS `v0.7.1`** (section L): logins for this platform only, and a login limited to one site, for a technician. It includes `v0.7.0` (section N): the site page in the Arkan design of the CMMS, with **View as** and **Settings**. The steps of the earlier releases follow, for reference: `v0.6.0` (section A, power quality pages; firmware `0.4.1`), `v0.5.0` (section B) and `v0.4.0`. **The steps, the same for every release** (the VPS from its terminal, the logger by cable from VS Code and PlatformIO, or over the air from a GitHub release): [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md). This file only says what each release needs on top. More detail: [tutorial 2, C5](tutorials/2-VPS-SETUP.md#c5-updating-to-a-new-tag-and-going-back) (VPS) and [`OTA.md`](OTA.md) (loggers).

**Status, 10 November 2026:** sections L and M are merged into the default branch (pull request #9, merge commit `bc2bb84`), not yet tagged or installed. The general update, from `v0.6.0` straight to `v0.8.0` and firmware `0.5.0`, step by step: [`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md#7-general-update-to-do-now-in-order-10-november-2026) section 7. After it: firmware `0.5.1` (section W, pull request #13; it contains 0.5.0, see W2). `v0.7.0` was tagged but not installed: going from `v0.6.0` straight to `v0.7.1` or `v0.8.0` is fine, then do the N4 browser checks too. Before them: the VPS runs `v0.6.0`, `LOG-0001` runs `0.4.1` (release `fw-v0.4.1`), `0.4.0` is marked withdrawn. Checks: [`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md).

House rules: the VPS only runs **tags**; the owner approves every container restart and the Caddy reload; a backup comes first.

## W. Firmware 0.5.1: two WiFi networks of equal rank, joins the one in range

### W0. What is in it

| Part | What changed | What it needs |
|---|---|---|
| Firmware **0.5.1** | `wifi_ssid` and `wifi_ssid2` are two networks of equal rank, for a logger moved between two sites, each with its own network. Before, `wifi_ssid2` was a backup, tried every other round. Each reconnection round now **scans first** (about 2 s) and tries only the configured network(s) in range, `wifi_ssid` first if both are. If the scan sees neither (hidden network, missed beacon, setup portal open), it tries both. **Once connected it stays on that network** until the link drops: it does not move back. [`FIRMWARE.md`](FIRMWARE.md) 2.4 and 3 | Bench test by cable (W2), then the tag `fw-v0.5.1` (W3) and the **Firmware update** panel (W4) |
| Status and event log | `status`: `WiFi: down for n s, in range at the last scan: ...`. Event log: `WiFi: connection failed (attempt n, status s, in range: ...), next try in n s`. At the boot, with both networks set: `WiFi: networks "<first>" and "<second>": joins the one in range, stays on it until the link drops`. `...` is the network(s) seen by name, `none of the configured networks (n other networks seen)`, `not scanned (setup portal open)`, `not scanned yet` or `scan failed` | Nothing |
| One network only (`LOG-0001` today) | Works as in 0.5.0: the network is tried every round, seen or not. The only changes are the 2 s scan before each attempt and the `in range` text | Nothing |
| Settings | No new key. `wifi_ssid2` and `wifi_pass2` are typed on the logger only (console, setup portal or `/config/settings.txt`), never from the VPS. No network name or password is built into the firmware | Set the second network by hand where a logger moves between two sites ([`FIRMWARE.md`](FIRMWARE.md#3-all-settings)) |
| 0.5.0 | Included (section M): the Modbus link of each meter | See W2 if the bench logger still runs 0.4.1 |
| VPS, records | No change: no VPS tag. `CSV_SCHEMA` stays 3 | Nothing |

### W1. On GitHub: merge

1. Merge pull request #13 into the default branch once CI is green (jobs `firmware`, `server`, `tools`). The VPS does not change: no `v0.x` tag.
2. **Not yet** the `fw-v0.5.1` tag: it comes after the bench test (W3).

### W2. Bench test by cable

Bench first, as in section 5 and M5. 0.5.1 contains 0.5.0. If the bench logger still runs 0.4.1 and `fw-v0.5.0` is not tagged yet, you can go straight to 0.5.1: do the M5 step 2 checks (the `Meter EM01` line) in this bench test too. The `fw-v0.5.0` tag is then not needed.

You need a **phone hotspot** (2.4 GHz; on an iPhone, turn on "Maximise Compatibility") and the **office WiFi password**: `show` does not display secrets.

1. **Flash 0.5.1 by cable** on the merge commit, from the PC:

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
git log -1 --oneline
```

**Expected:** `<commit> Firmware 0.5.1: two WiFi networks of equal rank, joins the one in range (#13)`, the merge commit of pull request #13. Write the commit (its first 7 characters) on the record sheet: the tag goes on **this** commit (W3). If the first line is a later merge, find the line of #13 with `git log --oneline -10`.

```powershell
Select-String '#define FW_VERSION' firmware\include\config.h
```

**Expected:** `#define FW_VERSION "0.5.1"`.

```powershell
cd firmware
```

```powershell
pio run -e logger -t upload
```

```powershell
pio device monitor -p COM4 -b 115200 -f esp32_exception_decoder -f time -f log2file
```

2. **One network, 10 minutes**, as on site today. Expected: `firmware 0.5.1` at the boot, `WiFi connected to "<office network>"`, then no restart. `status`: `WiFi: up, <office network> ...`, `Uploads: ok n, failed 0`.
3. **Two networks.** Make the hotspot the first network and the office the second, so that switching the hotspot off makes the logger move:

```
set wifi_ssid <hotspot name>
```

```
set wifi_pass <hotspot password>
```

```
set wifi_ssid2 <office network name>
```

```
set wifi_pass2 <office network password>
```

```
reboot
```

Then, for each line, `status` and `tail /log/<YYYY-MM>.log 20`:

| Do | Expected |
|---|---|
| a. Both on, after the reboot | `WiFi: networks "<hotspot name>" and "<office network name>": joins the one in range, stays on it until the link drops`, then `WiFi connected to "<hotspot name>"` (both in range: `wifi_ssid` first) |
| b. Switch the hotspot off | `WiFi lost`, then within about 30 s `WiFi connected to "<office network name>" ... (after n s offline)`. `status`: `WiFi: up, <office network name>` |
| c. Switch the hotspot on again, wait 5 min | It stays on the office network: `status` still shows `WiFi: up, <office network name>` |
| d. Switch the hotspot off, `set wifi_ssid2 NOT-HERE`, `reboot` | Neither network in range: `WiFi: connection failed (attempt 1, status n, in range: none of the configured networks (n other networks seen)), next try in 10 s`. `status`: `WiFi: down for n s, in range at the last scan: none of the configured networks (...)`. The `Last record` line still moves every minute |
| e. Still offline: hold **BOOT** 3 s (setup portal), open http://192.168.4.1 | After the next try (a few minutes at most), the status box shows `in range at the last scan: not scanned (setup portal open)`. The list of WiFi networks seen is still filled (reload once if it says `scanning`). Then tap **Close the setup WiFi** |
| f. Switch the hotspot on | It joins the hotspot at the next try (the back-off reached by then: 10, 20, 40, 80, 160 s, then every 5 min) |

Throughout, no restart that you did not ask for: the first line of `status` says `boot sw:console` after your `reboot`, never `task_wdt` or `panic`.

4. **Put the settings back**, one network as on site:

```
set wifi_ssid <office network name>
```

```
set wifi_pass <office network password>
```

```
unset wifi_ssid2
```

```
unset wifi_pass2
```

```
reboot
```

**Expected:** `WiFi connected to "<office network name>"`, no `networks ... and ...` line at the boot. `status`: `WiFi: up, <office network name>`. Then put the PC folder back ([`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) 3.5).

If anything above fails: keep the `log2file` file, do not tag, and flash the previous release again ([`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) 3.2 with its `fw-v` tag, then 3.3).

### W3. Tag `fw-v0.5.1` on the merge commit of #13

Only after W2 has passed. On the PC:

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git tag fw-v0.5.1 <commit written down in W2>
```

```powershell
git log -1 --oneline fw-v0.5.1
```

**Expected:** `<commit> (tag: fw-v0.5.1, ...) Firmware 0.5.1: two WiFi networks of equal rank, joins the one in range (#13)`. Anything else: `git tag -d fw-v0.5.1` and stop.

```powershell
git push origin fw-v0.5.1
```

CI makes the release **Logger firmware 0.5.1** with its four files. It stops if the tag and `FW_VERSION` differ ([`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) 4.1).

### W4. The loggers

- **`LOG-0001`**, the bench logger flashed in W2, already runs 0.5.1 from the cable: the panel refuses it (`LOG-0001 runs 0.5.1: 0.5.1 is not newer`), and the logger would ignore it anyway. Nothing to send. **Firmware versions** (<https://arkan-monitoring.duckdns.org/live/adab/#versions>) shows `0.5.1`, and the alarm log has **A35**, marked as flashed by hand.
- **Any other logger:** from **Firmware update** on the site page ([`OTA.md`](OTA.md)), **From a GitHub release**, `logger-0.5.1.bin`, **Send to ...**. Within a minute the logger restarts once; **A35** in the alarm log after 10 minutes; **Firmware versions** shows `0.5.1`. Then set its second network by hand if it moves between two sites.

---

## M. Release v0.8.0 and firmware 0.5.0: the Modbus link of each meter

### M0. What is in it

| Part | What changed | What it needs |
|---|---|---|
| Site page, **Live now** | The **Open alarms** card is always shown. At its top, one line per meter, kept in every state: `Meter EM01 · Modbus connected` (green, for how long, last answer), `not connected` (red, since when and why: timeout, CRC error...), `partial` (amber: some registers refused), `state unknown` (grey: no live data for 60 s). It reacts within 15 s; alarm **A03** still comes after a whole minute record, and still goes on WhatsApp. "No open alarm" moves into the card's title. [`LIVE.md`](LIVE.md#meter-link-modbus-connection-state) | VPS update |
| API | `GET /api/v1/live/<site>`: each logger gets `meters` (state, since, last answer, reason, counters) | Nothing: same path, same login |
| Firmware **0.5.0** | The logger keeps the Modbus link of each meter (answering or not, since when, last answer, last error, reads without answer) and sends it in every live snapshot (`sys.mb`). `status` on the console and the setup portal show one line per meter: `Meter EM01 (id 1): answering since ...` or `NO ANSWER for n reads ...: timeout: check wiring, A/B, meter id, baud, meter supply`. Records (CSV) unchanged: `CSV_SCHEMA` stays 3 | Bench test by cable, then the tag `fw-v0.5.0` and the **Firmware update** panel (M5) |
| Older firmware | A logger on 0.4.1 has no `sys.mb`: the service tells the state from its live values (connected when the snapshot has meter values), without the reason or the counters. The line says "from the live values (logger firmware before 0.5.0)" | Nothing: the VPS can go first |
| History pages: the period, and a CSV of the records | **Power**, **Energy per day**, **Temperature**, **Humidity**, the three power quality pages and the **Weather log**: 7, 14 or 31 days, or **From … to …** with two calendars (at most 92 days). **CSV** downloads the original 1-minute records of the period (and of the day on **One day**), every column and row of the logger's day files. API: every `?days=N` can be `?from=YYYY-MM-DD&to=YYYY-MM-DD`; new `GET /api/v1/records/<site>?from=&to=` ([`LIVE.md`](LIVE.md), [`DATA-ACCESS.md`](DATA-ACCESS.md)). Pull request #8 | Nothing: behind the same login; a login limited to some sites (`USER_SITES`, section L) gets the records of its own sites only |
| Simulated logger | Sends `sys.mb` (firmware `sim-0.5.0`); `--meter-off N` makes the meter silent for 5 minutes, N minutes after the start | Nothing |
| Caddy, `.env`, Docker files, alarm register | No change since `v0.7.1` | Nothing if the VPS runs `v0.7.1`. From `v0.6.0` or `v0.7.0`: the login file and the Caddy file of section L too (M2 to M4) |
| `v0.7.1` | Included (section L): logins for this platform only, limited to one site | See M2 to M4 |

**Order:** VPS first (it works with 0.4.1), then the firmware. Firmware 0.5.0 on a VPS still on `v0.7.0` or `v0.7.1` is harmless too: the extra field is saved and not shown.

### M1. On GitHub: merge, then tag

1. Merge the pull request into the default branch once CI is green (jobs `firmware`, `server`, `tools`). It brings `v0.7.1` (section L), the history pages (#8) and this release together: tag `v0.7.1` first (L1), then `v0.8.0`.
2. On the PC, as in N1: `git checkout ccr-a52c0421-oygp4n`, `git pull`, then `git log -1 --oneline bc2bb84` (the merge commit of #9), `git tag v0.8.0 bc2bb84` and `git push origin v0.8.0`. Name the commit: documentation commits came after the merge, so `git tag v0.8.0` alone would tag the wrong one ([`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md) section 7, step 1).
3. **Not yet** the `fw-v0.5.0` tag: it comes after the bench test (M5).

### M2 to M4. The VPS

Same steps as N2 to N4 ([`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md) part 2), with `v0.7.1` as the version you start from and go back to, and `v0.8.0` as the new tag. **If the VPS is still on `v0.6.0` or `v0.7.0`:** do section L first, or go straight to `v0.8.0` and do L3.3 (the login file) and L3.4 (the Caddy file) before the rebuild; going back is then as in L4: the service and the Caddy file together. Expected after the update:

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.8.0", ...}`.

```bash
curl -s http://127.0.0.1:8800/api/v1/live/adab | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['devices']['LOG-0001']['meters'])"
```

**Expected (LOG-0001 still on 0.4.1):** `[{'meter': 'EM01', 'state': 'ok', 'source': 'values', ...}]` if the meter answers, `'state': 'no_answer'` if it does not.

In the browser, `https://arkan-monitoring.duckdns.org/live/adab/` (Ctrl+F5): the **Open alarms** card is at the top even with no alarm (`✓ No open alarm` in its title), with the line `Meter EM01 · Modbus connected` in green (or `not connected` in red if the meter does not answer: then A03 is open too).

**Going back:** `git checkout v0.7.1`, then `docker compose up -d --build`. Nothing in the data folder or in Caddy is left to undo (from `v0.7.1`; coming from an older tag, see L4).

### M5. The loggers: firmware 0.5.0

Bench first, as in section 5 (the lessons at its end).

1. **Flash 0.5.0 by cable** on the bench logger, from the PC, on the merge commit:

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git fetch origin
```

```powershell
git checkout -B release-0.5.0 v0.8.0
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

2. **Watch 10 minutes.** Expected: `firmware 0.5.0` at the boot, then no restart. `status` shows the line `Meter EM01 (id 1): ...`: with a meter (or `tools/modbus_sim/`) on the RS485 port, `answering since ...`; with nothing on the port, `NO ANSWER for n reads, since ...: timeout: ...`. On the site page the line `Meter EM01 · Modbus ...` follows within 15 s, without `from the live values`. Disconnect the meter (or stop the simulator): the line goes red within 15 s; reconnect: green again.
3. **Only then:** tag `fw-v0.5.0` on the commit of `v0.8.0`: `git tag fw-v0.5.0 v0.8.0`, check `git log -1 --oneline fw-v0.5.0` shows the merge commit, then `git push origin fw-v0.5.0`. CI makes the release **Logger firmware 0.5.0** (it stops if the tag and `FW_VERSION` differ).
4. **Send it to the other loggers** from **Firmware update** on the site page ([`OTA.md`](OTA.md)): **From a GitHub release**, `logger-0.5.0.bin`, then **Send to** in that logger's panel. Within a minute the logger restarts once; **A35** in the alarm log after 10 minutes; **Firmware versions** shows `0.5.0`. `LOG-0001` is the bench logger of step 1: it already runs 0.5.0 from the cable, and the panel refuses it (`LOG-0001 runs 0.5.0: 0.5.0 is not newer`). Today it is the only logger, so there is nothing to send.

---

## L. Release v0.7.1 (10 November 2026): logins for this platform only, limited to one site

### L0. What is in it

| Part | What changed | What it needs |
|---|---|---|
| Logins for this platform only | A second Caddy login file, `/opt/edge/secrets/monitoring-users.caddy`, for people who need only this platform (a technician). It opens the site pages and their API, not OED and not the other Arkan dashboards | The file must exist before the new Caddy file is installed (L3.3), empty while nobody is in it |
| `USER_SITES` in `server/.env` | Limits a login to some sites (`tech-adab:adab`): `/live/` and another site's page send it to its own site, **All sites** leaves its menu, every API path of another site or of another site's logger answers `403` (firmware update and register table included). Logins not listed: no change | An optional `.env` line, with the first such login ([`LIVE.md`](LIVE.md#logins)) |
| Site page | **All sites** hidden for those logins; **Settings** shows the login's sites | VPS update |
| `GET /api/v1/admin/me` | New field `sites`: `null` (every site) or the login's sites | Nothing |
| Caddy files | `monitoring.caddy`: the second `import`. `oed/monitoring-oed.caddy` (only if OED is installed): OED takes the Arkan logins only, the platform logins reach only the ingest service. Not tested on a machine yet: `caddy validate` before any reload | The owner installs the file and reloads |
| `v0.7.0` | Included: if the VPS still runs `v0.6.0`, this release also brings section N0 | The N4 browser checks |
| Loggers, data folder, firmware, Dockerfile | No change | Nothing |

### L1. On GitHub: tag the release commit

`v0.7.1` came into the default branch with `v0.8.0` and the history pages, in one pull request (M1). It has no merge commit of its own, so the tag goes on its release commit `ce96ffb`, which holds exactly `v0.7.0` plus this release (CI green on its branch). From the PC, after the merge:

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
git log -1 --oneline ce96ffb
```

**Expected:** `ce96ffb Release v0.7.1: logins for this platform only, limited to one site`. Then:

```powershell
git tag v0.7.1 ce96ffb
```

```powershell
git log -1 --oneline v0.7.1
```

**Expected:** the same line, now with `(tag: v0.7.1)`.

```powershell
git push origin v0.7.1
```

No `fw-v` tag comes with it (no firmware change).

### L2. Before: where you start from

**Where:** VPS, user ai (`ssh hermes-vps`), except the steps marked owner.

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** `v0.6.0` (or `v0.7.0` if section N was done). Write it down: it is what you go back to.

```bash
git status
```

**Expected:** `nothing to commit, working tree clean` (an untracked `server/.env` is fine). Modified files: stop and ask the owner.

### L3. Update

**L3.1 Backup**

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**L3.2 Get the new version**

```bash
git fetch --tags
```

```bash
git log -1 --oneline v0.7.1
```

**Expected:** a line with `Release v0.7.1`. Anything else: stop and ask the owner.

```bash
git checkout v0.7.1
```

**L3.3 The login file for this platform only (owner)**

Create it empty, with the same owner and rights as the Arkan login file (Caddy must be able to read it):

```bash
sudo touch /opt/edge/secrets/monitoring-users.caddy
```

```bash
sudo chown --reference=/opt/edge/secrets/hub-users.caddy /opt/edge/secrets/monitoring-users.caddy
```

```bash
sudo chmod --reference=/opt/edge/secrets/hub-users.caddy /opt/edge/secrets/monitoring-users.caddy
```

```bash
sudo ls -l /opt/edge/secrets/
```

**Expected:** `monitoring-users.caddy` with the same owner and rights as `hub-users.caddy`. The technician's line goes in later ([`LIVE.md`](LIVE.md#adding-a-technicians-login-owner-on-hermes-vps), steps 1 to 3), or now.

**L3.4 `.env`, Caddy and Docker files**

```bash
git diff --stat v0.7.0 v0.7.1 -- server/.env.example server/deploy server/docker-compose.yml server/Dockerfile
```

**Expected:** `server/.env.example`, `server/deploy/monitoring.caddy`, `server/deploy/oed/monitoring-oed.caddy` and `server/docker-compose.yml` (`v0.7.0` changed none of them, so this is also the list from `v0.6.0`). `.env`: nothing to add now; `USER_SITES` comes with the first login limited to a site.

```bash
diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy
```

**Expected:** the new comment lines at the top, the comment `# People: Arkan login, or a login for this platform only.`, and one new line, `import /opt/edge/secrets/monitoring-users.caddy`, under the `hub-users.caddy` one. (If OED is installed, compare with `server/deploy/oed/monitoring-oed.caddy` and install that one: there the people part is split in two, see L0.) Other differences: someone changed the live file, stop and compare with the owner.

The owner keeps a copy of the current file, installs the new one and validates:

```bash
sudo cp /opt/edge/sites/monitoring.caddy /opt/edge/monitoring.caddy.before-v0.7.1
```

```bash
sudo cp /opt/arkan-monitoring/server/deploy/monitoring.caddy /opt/edge/sites/monitoring.caddy
```

If the port is not 8800 (tutorial 2, B14), edit the three `reverse_proxy 127.0.0.1:8800` lines again now.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

**Expected:** `Valid configuration`. **If** an error names `monitoring-users.caddy`: the file is missing (L3.3), or Caddy refuses it empty: add the technician's line first ([`LIVE.md`](LIVE.md#adding-a-technicians-login-owner-on-hermes-vps), steps 1 to 3) and validate again. Nothing has changed on the live site until the reload.

**L3.5 Rebuild, restart and reload (owner approves)**

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

**Expected:** the container `Recreated`, `Started`. About 30 s without live data on the page. Then the Caddy reload:

```bash
sudo systemctl reload caddy
```

### L4. Checks

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.7.1", ...}`.

```bash
curl -s -u <your-login> https://arkan-monitoring.duckdns.org/api/v1/admin/me
```

**Expected:** your login and `"sites": null` (every site).

In the browser, with your login: `https://arkan-monitoring.duckdns.org/live/` lists the sites as before, the Adab page has **All sites** in its menu, and **Settings** shows `Sites: every site`. Coming from `v0.6.0`: the N4 browser checks too.

Then the technician's login: [`LIVE.md`](LIVE.md#adding-a-technicians-login-owner-on-hermes-vps).

**Going back:** the service and the Caddy file go back **together**. Version `v0.7.0` ignores `USER_SITES`, so with the new Caddy file a limited login would see every site; the old Caddy file does not take the platform logins at all.

```bash
sudo cp /opt/edge/monitoring.caddy.before-v0.7.1 /opt/edge/sites/monitoring.caddy
```

Then `sudo caddy validate --config /etc/caddy/Caddyfile`, `git checkout <the tag of L2>`, `docker compose up -d --build`, and the owner reloads Caddy. `monitoring-users.caddy` can stay: nothing reads it then.

### L5. The loggers

Nothing in this release.

---

## N. Release v0.7.0 (10 November 2026): the site page in the Arkan design

### N0. What is in it

| Part | What changed | What it needs |
|---|---|---|
| Site page `/live/<site>/` and `/live/` | Same content, new look: the Arkan UI kit of the CMMS (side bar with the logo, cards, tables, light, dark and high contrast). Icon rail on a tablet, bottom tabs and a **More** list on a phone. Every chart shows both axes with their scales; in a row of cards the figures and the charts line up. The link to Open Energy Dashboard is gone from the menu | VPS update |
| **View as** (side bar) | Who is logged in and with which rights: `Admin · <login>` for a login in `ADMIN_USERS`, `Viewer · <login>` for the others. An admin can switch to Viewer to see the pages as the others do (Firmware update hidden). It changes that browser only, never the rights on the server | Nothing new: it reads `GET /api/v1/admin/me`, as the firmware panel did |
| **Settings** (bottom of the side bar, `#prefs`) | Display settings of the kit (mode, density, text size, motion, reset), saved in the browser; who is logged in; the site details of `site.json`, read only | Nothing |
| Meter registers | Now a page of the site, `/live/<site>/#register`. The old address `/live/<site>/register` sends the browser there. `server/app/registers.html` is removed | Nothing: old links and bookmarks keep working |
| UI kit files | `server/app/arkan-ui/arkan-ui.css` and `arkan-ui.js`, served at `/live/_ui/<file>` | Nothing: under `/live/`, so behind the Arkan login like the page (checked in N3.3) |
| API, data folder, firmware, Caddy, `.env`, Docker files | No change | Nothing |
| Mockup | [`mockup/arkan/`](mockup/arkan/README.md): the same page with saved answers, one file, for reviews | Nothing on the VPS |

### N1. On GitHub: merge, then tag

1. Merge the pull request "Release v0.7.0" into the default branch once CI is green (jobs `firmware`, `server`, `tools`).
2. Tag the merge commit `v0.7.0` from the PC, after checking what it points to ([`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md), first lines):

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
git log -1 --oneline
```

**Expected:** a line that ends with `Release v0.7.0: ...`. Then:

```powershell
git tag v0.7.0
```

```powershell
git push origin v0.7.0
```

No `fw-v` tag comes with it (no firmware change).

### N2. Before: where you start from

**Where:** VPS, user ai (`ssh hermes-vps`), except the steps marked owner.

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** `v0.6.0`. Write it down: it is what you go back to.

```bash
git status
```

**Expected:** `nothing to commit, working tree clean` (an untracked `server/.env` is fine). Modified files: stop and ask the owner.

### N3. Update

**N3.1 Backup**

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**N3.2 Get the new version**

```bash
git fetch --tags
```

```bash
git log -1 --oneline v0.7.0
```

**Expected:** a line that ends with `Release v0.7.0: ...`. Anything else: stop and ask the owner.

```bash
git checkout v0.7.0
```

**N3.3 `.env`, Caddy and Docker files: nothing to change, check only**

```bash
git diff --stat v0.6.0 v0.7.0 -- server/.env.example server/deploy server/docker-compose.yml server/Dockerfile
```

**Expected:** no output (none of these files changed).

```bash
diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy
```

**Expected:** no output (if OED is installed, compare with `server/deploy/oed/monitoring-oed.caddy`). The kit files are under `/live/`, which both files already send to the service behind the Arkan login.

**N3.4 Rebuild and restart (owner approves)**

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

**Expected:** the container `Recreated`, `Started`. About 30 s without live data on the page; the loggers keep their records on the SD card and send them after.

### N4. Checks

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.7.0", ...}`.

```bash
docker compose ps
```

**Expected:** `Up ... (healthy)` after a minute.

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8800/live/_ui/arkan-ui.css
```

**Expected:** `200`.

In the browser, `https://arkan-monitoring.duckdns.org/live/adab/` (reload once with Ctrl+F5):
- the side bar: Arkan logo, the site, **View as** with your login, the menu groups, **Settings** at the bottom with the green pill `Live · updated n s ago`;
- **Live now** shows the same values as before, each small chart with its scales;
- **Settings**: Mode **Dark** turns the page dark at once; **Reset display settings** puts it back;
- **Meter registers** opens in the same page; the old address `https://arkan-monitoring.duckdns.org/live/adab/register` lands on it too;
- with a login in `ADMIN_USERS`: **Firmware update** is in the menu; **View as**, **Viewer** hides it;
- `https://arkan-monitoring.duckdns.org/live/` lists the sites in the same design.

If the page shows plain text without any design, the kit files did not load: check the `curl` line above, then the Caddy file (N3.3).

**Going back:** `git checkout v0.6.0`, then `docker compose up -d --build`. This release only changes the page files: nothing in the data folder or in Caddy is left to undo.

### N5. The loggers

Nothing in this release.

---

## A. Release v0.6.0 (10 November 2026): power quality pages

### A0. What is in it

| Part | What changed | What it needs |
|---|---|---|
| Power quality pages | Menu group **Power quality** on the site page: **Power quality** (minutes inside the voltage limits, dips and swells, unbalance, frequency, power factor, day by day, the power quality alarms of the period), **Voltage** (each phase hour by hour with the lowest and highest 15 s sample, unbalance, one day minute by minute), **Power factor** (power factor from the kWh and kVArh counters, time below 0.85, the kVArh PLN bills as excess, an indicative capacitor size). The limits are read from the alarm register in use ([`LIVE.md`](LIVE.md#option-a-in-detail)) | VPS update |
| API | `GET /api/v1/quality/<site>?days=N` and `GET /api/v1/quality/<site>/day/<date>` ([`DATA-ACCESS.md`](DATA-ACCESS.md)) | Nothing: behind the Arkan login like the other read paths (checked in A3.3) |
| Simulated logger | Its power factor drops at light load and its voltage sags a little with the load, so the new pages have something to show | Nothing |
| Firmware **0.4.1** | Now in the code (the 9 November work): no more restart every minute behind Caddy (0.4.0 is withdrawn), AM2301 default on GPIO 1, console `tail` fixed. RS485 docs: GPIO 17 (TX) and 18 (RX), terminal labels | **Not released by this tag.** Bench test by cable, then the tag `fw-v0.4.1` (section 5, steps 1 to 5, at the end). The VPS update does not touch the loggers |
| Caddy, `.env`, Docker files | No change | Nothing (checked in A3.3) |

### A1. On GitHub: merge, then tag

The pull request "Release v0.6.0" was merged into the default branch once CI was green (jobs `firmware`, `server`, `tools`): merge commit `309d57a`. Tagged `v0.6.0` on 10 November, pushed from the PC ([`CHECK-UP-TO-DATE.md`](CHECK-UP-TO-DATE.md) section 8, step 1). Its `/health` answers `"version": "0.6.0"`. No `fw-v` tag comes with it (firmware: A0).

### A2. Before: where you start from

**Where:** VPS, user ai (`ssh hermes-vps`), except the steps marked owner.

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** `v0.5.0`. Write it down: it is what you go back to. If it says `fatal: not a git repository`, stop and ask the owner (section 5, "The VPS code is a git clone").

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
git log -1 --oneline v0.6.0
```

**Expected:** a line that starts with `309d57a`, for example `309d57a (tag: v0.6.0) Release v0.6.0: power quality pages; firmware 0.4.1 merged (#2)`. If it starts with `f4527ba` (a wrong `v0.6.0` was on GitHub for a few minutes on 10 November), run `git fetch --tags --force` and check again. Anything else: stop and ask the owner.

```bash
git checkout v0.6.0
```

**A3.3 `.env`, Caddy and Docker files: nothing to change, check only**

```bash
git diff --stat v0.5.0 v0.6.0 -- server/.env.example server/deploy server/docker-compose.yml server/Dockerfile
```

**Expected:** no output (none of these files changed).

```bash
diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy
```

**Expected:** no output (if OED is installed, compare with `server/deploy/oed/monitoring-oed.caddy`). The new `/api/v1/quality/*` paths fall under the Arkan login like every path that is not a logger's.

**A3.4 Rebuild and restart (owner approves)**

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

**Expected:** the container `Recreated`, `Started`. About 30 s without live data on the page; the loggers keep their records on the SD card and send them after.

### A4. Checks

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.6.0", ...}`.

```bash
docker compose ps
```

**Expected:** `Up ... (healthy)` after a minute.

```bash
curl -s "http://127.0.0.1:8800/api/v1/quality/adab?days=1" | head -c 300; echo
```

**Expected:** JSON that starts with `{"site": "adab", "device": "LOG-0001", "meter": "EM01", ...`.

In the browser, `https://arkan-monitoring.duckdns.org/live/adab/`:
- the menu has a group **Power quality** with **Power quality**, **Voltage**, **Power factor**;
- while the logger reads no meter (the bench logger has none), each of the three pages says `No meter records for this period.`: that is expected. With a meter (on site, or the simulated logger of tutorial 2, B25), they show tiles, tables and charts;
- the other pages are unchanged.

**Going back:** `git checkout v0.5.0`, then `docker compose up -d --build`. The new pages only read the data folder, so nothing is left to undo.

### A5. The loggers

Nothing in this release. Firmware 0.4.1 goes to the bench logger by cable first, then gets its own tag `fw-v0.4.1`: section 5, steps 1 to 5 (at the end of this file). Never send 0.4.0.

---

## B. Release v0.5.0 (9 November 2026): weather, saved live data, firmware versions page, for reference

### B0. What is in it

| Part | What changed | What it needs |
|---|---|---|
| Weather | Menu group **Weather**: Today (forecast hour by hour), Tomorrow (next day forecast), Weather log (actual weather against the forecast and the outdoor sensor, CSV). One weather line on Live now. Open-Meteo, no key ([`WEATHER.md`](WEATHER.md)) | VPS update, then **once**: the site's position (B3.5). The container must reach `api.open-meteo.com` |
| Live data saved | Every 15 s snapshot is also saved in the data folder (`live.json`, `live/<day>.jsonl`, 7 days, about 3 MB a day per logger); the live page refills after a restart; a second dashboard can read everything from one place ([`DATA-ACCESS.md`](DATA-ACCESS.md)) | VPS update. Optional `.env` key `LIVE_KEEP_DAYS` |
| Firmware versions page | **Firmware versions** in the menu (group Logger), for everyone: running firmware, since when, last restart, offers, history, GitHub releases ([`OTA.md`](OTA.md) section 5) | VPS update |
| Docker network | The service's network is now named `arkan-monitoring` (a second dashboard's container joins it) | Nothing: the restart creates it (B3.4) |
| Firmware | No change: stays `0.4.0`, **no `fw-v` tag** this time | Nothing on the loggers |
| Caddy | No change: the new pages and `/api/v1/weather/*`, `/api/v1/versions/*` are behind the Arkan login like the others | Nothing (checked in B3.3) |

### B1. On GitHub (owner): merge, then tag

1. Merge the pull request from `claude/practical-cori-ji7fop` into the default branch. Wait for CI to be green (jobs `firmware`, `server`, `tools`).
2. Tag the merge commit `v0.5.0`, on GitHub (**Releases**, **Draft a new release**, **Choose a tag**, type `v0.5.0`, target the default branch, publish) or from a terminal on the merged commit:

```bash
git tag v0.5.0
```

```bash
git push origin v0.5.0
```

Its `/health` answers `"version": "0.5.0"`.

### B2. Before: where you start from

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

### B3. Update

**B3.1 Backup**

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**B3.2 Get the new version**

```bash
git fetch --tags
```

```bash
git checkout v0.5.0
```

**B3.3 `.env` and Caddy: nothing to change, check only**

```bash
diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy
```

**Expected:** no output (if OED is installed, compare with `server/deploy/oed/monitoring-oed.caddy`). The new `.env` keys are optional; without them the defaults apply: `WEATHER` (on), `WEATHER_EVERY_MIN` (60), `LIVE_KEEP_DAYS` (7); see `server/.env.example`.

**B3.4 Rebuild and restart (owner approves)**

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

**B3.5 Weather: the hotel's position (once)**

Adab Sidemen Resort, from the Google Maps pin:

```bash
docker compose exec ingest python tools/manage.py weather adab --lat -8.4766 --lon 115.4319
```

**Expected:** `fetched ... hours`, then `now (...)`, then three lines, today, tomorrow and the day after, each with a weather, a temperature range and rain. If it says `Open-Meteo not reachable`, the container cannot open an HTTPS connection to `api.open-meteo.com`: check the VPS outbound firewall rules (the firmware panel reaches `api.github.com` the same way), then run the command again. The rest of the release works without it.

### B4. Checks

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

The general steps are now in [`HOW-TO-UPDATE.md`](HOW-TO-UPDATE.md).

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

1. **Flash 0.4.1 by cable** from VS Code. In the VS Code terminal, bring your copy `C:\dev\esp32-datalogging` to the code of 0.4.1 (your own commit is in it; since 10 November it is in the default branch and in the tag `v0.6.0`):

```powershell
cd C:\dev\esp32-datalogging
```

```powershell
git fetch origin
```

```powershell
git checkout -B release-0.4.1 v0.6.0
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
3. **Only then:** tag `fw-v0.4.1` on the commit of `v0.6.0` (already in the default branch since 10 November; the firmware code is the same), from your copy: `git tag fw-v0.4.1 v0.6.0`, check that `git log -1 --oneline fw-v0.4.1` starts with `309d57a`, then `git push origin fw-v0.4.1`. No new VPS tag is needed. CI makes the release **Logger firmware 0.4.1**.
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
