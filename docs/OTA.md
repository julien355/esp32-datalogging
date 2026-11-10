# Remote firmware update from the site page

The site page, for example `https://arkan-monitoring.duckdns.org/live/adab/`, has **Firmware update** in its side menu (group *Logger*), with one panel per logger of the site. It shows only for the logins in `ADMIN_USERS` (section 6). From a panel you send a firmware to **that logger only**. You can take it from:

- **a GitHub release**: built by CI from a tag, so the firmware is exactly the code in the repository at that tag;
- **a `.bin` file on your computer**: a build from your own PlatformIO, or a file downloaded from a CI run;
- **a firmware already on the server**: sent earlier to another logger.

`manage.py publish-fw` still works (for every logger at once, or from a script). It uses the same checks.

## 1. How it works

```
 GitHub tag fw-v0.4.1 ──CI──> release: logger-0.4.1.bin, logger-uart-0.4.1.bin
                                      │
 site page, Firmware update, LOG-0001 ┤ (or upload a .bin, or pick a stored file)
                                      ▼
 VPS: checks the file, keeps it in /data/firmware/, offers it to LOG-0001 only
                                      │  the next live snapshot (15 s) answers {"ota":1}
                                      ▼
 LOG-0001: GET /api/v1/ota, downloads, checks MD5, writes the 2nd flash slot, restarts
                                      │
                         new version stays up 10 min: kept (A35 in the alarm log)
                         restarts 3 times before that: goes back by itself (A36),
                         and that version is never offered to it again
```

- **When it happens:** if the logger is online, within about a minute (the answer to its live snapshot tells it to check now). If it is offline, at its next check after it comes back (every `ota_check_h` = 6 h). On the console, `ota` checks at once.
- **What the hotel sees:** the logger restarts once, about 30 s without readings. Nothing is lost: the minute records stay on the SD card and are uploaded after the restart.
- **The logger must have `ota_on=1`** (the default). The panel warns if it is 0.

## 2. Checks before a file is offered

The server refuses the file unless all of these hold (`server/app/firmware.py`):

| Check | Why |
|---|---|
| An ESP32-S3 app image (first byte 0xE9, chip id 9), 64 kB to 1.9 MB | Not `bootloader.bin`, `partitions.bin`, a zip, a file for another chip, or a cut download |
| It carries the marker `ARKAN-LOGGER-FW;ver=x.y.z;env=usb;` | A lab sketch (`docs/install/labs/`) would cut the logger off for good: it has no OTA |
| Its build (`usb` or `uart`) is the logger's build | The UART build on a native USB board loses the console. Each logger reports its build after every boot |
| Its version is newer than the logger's | No step back by mistake. Tick **force** to step back on purpose |
| A version number never gets other content | Loggers already offered that file check its MD5. Change `FW_VERSION` for every new build |

The version is read **from the file**, never typed by hand: it is `FW_VERSION` in [`firmware/include/config.h`](../firmware/include/config.h).

## 3. Making a release on GitHub (the normal way)

1. Change `FW_VERSION` in `firmware/include/config.h`, for example to `0.4.1`. Commit and push. Test the build on the bench logger first.
2. Create the tag **`fw-v0.4.1`** on that commit (same number, with `fw-v` in front), on GitHub ("Releases", "Draft a new release", "Choose a tag", type `fw-v0.4.1`, target the commit) or from a terminal:
   ```bash
   git tag fw-v0.4.1
   ```

   ```bash
   git push origin fw-v0.4.1
   ```
3. CI builds both variants and creates the release **"Logger firmware 0.4.1"** with `logger-0.4.1.bin` (native USB build, the normal one), `logger-uart-0.4.1.bin`, and the bootloader and partition files for a first flash by cable. CI stops if the tag and `FW_VERSION` differ.
4. On the site page, open **Firmware update** in the menu, then the logger's panel. **From a GitHub release** lists the releases, with the file of the logger's build already selected. **Send to LOG-0001**.

The `fw-v` tags are for firmware only. The `v` tags of the VPS code (tutorial 2) are separate.

## 4. Sending from a file on your computer

Use this for a bench build that has no release. Build with `pio run`, then in the panel **From a file on this computer**, choose `firmware/.pio/build/logger/firmware.bin` and click **Upload and send**. Any file name works: the server names it `logger-<version>.bin` from the marker inside.

## 5. The panel

Loggers report their build (`usb` or `uart`) from firmware **0.4.0** on, the first version that carries the build marker. A logger on an older firmware can still be updated from the panel (it already has OTA), but the panel cannot check its build: send the `usb` build unless you know it runs the UART build.

- **Status line:** running version and build, what is offered, by whom and when, then one of: *waiting for the logger*, *installed*, *rolled back* (the logger kept restarting on it), *not newer*.
- **Recent events:** offered, withdrawn, rolled back, firmware changes seen in the records.
- **force:** allows an older version or the other build variant. Only on purpose.
- **Withdraw the offer:** removes what was offered to this logger. If an offer to every logger (`manage.py publish-fw` without `--device`) exists, that one applies again.
- The panel shows only to the logins listed in `ADMIN_USERS`. The live values stay visible to everyone with a login.

**Firmware versions** (`#versions`, everyone with a login, read only, service 0.5.0): what each logger runs and since when, its last restart and why, the offer and its state, the versions it refused, the full history of firmware changes and offers (and every restart if asked), the GitHub releases with the logger running each, and the files on the server. Use it to check an update went through; the panel above is only for sending.

A version that rolled back is not offered to that logger again. To try it again anyway, send it again from the panel. The logger also remembers it and skips it, until someone types `ota` on its console. The real fix is a new build with a new version number.

## 6. Server settings (once, on the VPS)

In `/opt/arkan-monitoring/server/.env` (not in git; `chmod 600 .env`):

```
ADMIN_USERS=<your-login>
FW_GITHUB_REPO=julien355/esp32-datalogging
FW_GITHUB_TOKEN=
```

- `ADMIN_USERS`: the login names (of `hub-users.caddy` or `monitoring-users.caddy`) that may send firmware, comma separated. Empty = the panel is off. `*` = everyone who can log in. A login limited to some sites by `USER_SITES` sends firmware only to the loggers of its sites ([`LIVE.md`](LIVE.md#logins)).
- `FW_GITHUB_REPO`: where the releases are.
- `FW_GITHUB_TOKEN`: only if the repository is private. On GitHub: Settings, Developer settings, Fine-grained tokens, "Only select repositories" = this one, Permissions "Contents: Read-only". Nothing else.

Then apply it (the owner approves the restart, house rule):

```bash
cd /opt/arkan-monitoring/server && docker compose up -d
```

No Caddy change is needed for the panel: its requests go through the same login as the site page, and the loggers' OTA endpoints are unchanged. (Version 0.4.0 of the repository does change the Caddy file for another reason, the register table: tutorial 2, C5 step 3b.)

## 7. Security

- Only people who pass the Caddy login **and** are in `ADMIN_USERS` can send firmware. Caddy passes the login name to the service (`X-Auth-User`), and the service listens on the loopback only.
- Every change request must carry the header `X-Requested-With: arkan`, and the `Origin`, if sent, must be this site. A page on another site cannot send such a request with your saved login.
- Every offer is logged with the login name (`events.jsonl` of the logger, and the service's log).
- The logger downloads only from its own `srv_url` with its own token, over verified TLS, and checks the MD5 before switching slots.
- The GitHub token, if any, only reads this repository, and it is never sent to the logger or the browser.

## 8. Changes this needed

- Firmware: the build marker `FW_TAG` (`config.h`, variant per env in `platformio.ini`); `env` and `fw_tag` in the boot report; the "check now" answer to the live snapshot (at most one check every 5 min); a rolled-back version is remembered (`ota_bad`) and skipped.
- Service: `server/app/firmware.py` (checks, offers, rollback memory, GitHub releases); the `/api/v1/admin/...` endpoints in `server.py`; the panel in `live.html`; `manage.py publish-fw` uses the same checks, and `--version` is now optional.
- CI: the `release` job on `fw-v*` tags.
