# VPS setup for the monitoring ingest service

Target: **hermes-vps** (Hostinger, Ubuntu), beside the Hub, the CMMS and Hermes, with the house rules of PLAN.md §4.3: loopback port only, its own container and data folder, **the owner runs the `sudo` steps and approves the Caddy reload**, no file overwritten without asking.
Files: [`server/`](../server/). The service is Python standard library only, one container, limited to 96 MB of RAM.

> **Where the code lives.** PLAN.md §4.2 puts the platform in its own repository, `arkan-monitoring`. That repository does not exist yet, so the ingest service is in `server/` here for now. It moves as it is when `arkan-monitoring` is created ([`QUESTIONS.md`](QUESTIONS.md) Q12). The commands below use `/opt/arkan-monitoring/server`, which works with either repository.

## 1. What ends up on the VPS

| Item | Where |
|---|---|
| Code (checked out at a tag) | `/opt/arkan-monitoring/` (this repository, or `arkan-monitoring` later) |
| **Dedicated data folder** | **`/srv/arkan-monitoring/data/`** (owner uid 1000), mounted at `/data` in the container. Layout: [`DATA-FORMAT.md`](DATA-FORMAT.md) §2 |
| Nightly backups | `/srv/arkan-monitoring/backups/` (14 kept) |
| Container | `arkan-monitoring-ingest`, `127.0.0.1:8800`, `restart: unless-stopped`, 96 MB, read-only except `/data`, logs capped at 30 MB |
| Caddy site file | `/opt/edge/sites/monitoring.caddy` (from `server/deploy/monitoring.caddy`) |
| Public address | `https://arkan-monitoring.duckdns.org/` |

## 2. Prerequisites (check, do not reinstall on hermes-vps)

```bash
docker --version
```

```bash
docker compose version
```

```bash
free -h
```

```bash
ss -ltn | grep -E ':(8800|8780|8790)\b'
```

Docker is already on hermes-vps (the Hub and the CMMS run in it). **Only on a new, empty VPS**, install Docker from Docker's repository:
```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker ai
```
Port 8800 must be free (the Hub uses 8780, the CMMS 8790). If it is not, put another port in `server/.env` (`INGEST_PORT=`) and in `monitoring.caddy`.

## 3. DuckDNS name (owner)

1. On duckdns.org, create **`arkan-monitoring`** and point it to the VPS's public IP.
2. Add it to the DuckDNS update job the other names use (same token).
3. Check: `dig +short arkan-monitoring.duckdns.org` gives the VPS IP.

## 4. Code and data folder

```bash
sudo git clone https://github.com/julien355/esp32-datalogging.git /opt/arkan-monitoring
```

```bash
sudo chown -R ai:ai /opt/arkan-monitoring
```

```bash
cd /opt/arkan-monitoring && git checkout <tag>
```

Dry run first (shows what it would do, changes nothing), then for real:
```bash
sudo bash /opt/arkan-monitoring/server/deploy/setup-vps.sh
```

```bash
sudo bash /opt/arkan-monitoring/server/deploy/setup-vps.sh --apply
```

## 5. Start the service

```bash
cd /opt/arkan-monitoring/server && docker compose up -d --build
```

```bash
curl -s http://127.0.0.1:8800/health
```

```bash
docker stats --no-stream arkan-monitoring-ingest
```
Expected: `{"ok": true, ...}` and well under 96 MB.

Then once, to put the alarm register in the data folder (`/srv/arkan-monitoring/data/alarm-register.csv`, the copy you edit in Excel):
```bash
docker compose exec ingest python tools/manage.py init
```

## 6. Site and logger

```bash
cd /opt/arkan-monitoring/server && docker compose exec ingest python tools/manage.py add-site adab --name "Adab hotel" --contracted-kva 82.5 --rated-a 200
```

```bash
docker compose exec ingest python tools/manage.py add-device adab LOG-0001
```
The second command prints the **token** and the logger's own **setup WiFi password** (`portal_pass`) **once**. Copy both to the password manager straight away: only the token's hash is kept on the VPS. Lost token: `rotate-token LOG-0001`. Add `--sd-settings /data/export/settings-LOG-0001.txt` to also get the SD card settings file (then move it off the VPS and delete it).

`site.json` then holds the PLN contract (82.5 kVA, 220 V per phase for the 3 x 125 A limit), the 200 A main breaker and 230 V nominal (owner, 7 November 2026). Edit `/srv/arkan-monitoring/data/sites/adab/site.json` for labels and live values.

## 7. Caddy (owner approves the reload)

```bash
sudo cp -n /opt/arkan-monitoring/server/deploy/monitoring.caddy /opt/edge/sites/monitoring.caddy
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

```bash
sudo systemctl reload caddy
```
`cp -n` never overwrites an existing file. The site file:
- `/api/v1/ingest`, `/api/v1/ota`, `/api/v1/firmware/*`, `/api/v1/config`, `/api/v1/config/report` and `POST /api/v1/live`: **no web login** (the logger cannot log in), the device token is checked by the service, body size capped.
- Everything else (`/live/`, `/api/v1/status`, `/api/v1/live/<site>`, `/api/v1/alarms/<site>`): **Arkan login** (`/opt/edge/secrets/hub-users.caddy`). `/` goes to `/live/` until OED is installed.
- Authorization headers removed from the access log.

Check from the laptop:
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://arkan-monitoring.duckdns.org/live/
```
Expected `401` (login asked). Then open `https://arkan-monitoring.duckdns.org/live/` in a browser and sign in.

## 8. Test with the simulated logger (before the board)

From the laptop (Python 3, no packages), with the token from step 6:
```bash
python server/tools/simulate_logger.py --url https://arkan-monitoring.duckdns.org --token <token> --backlog-hours 3 --resend --event dip --live
```
Expected:
- the alarm log (`manage.py alarms adab`) shows A02 Power interruption (the simulator's first record says `poweron`), A16 Backlog growing (the simulator reports its backlog), and A26 Voltage dip and A05 Undervoltage starting and clearing 30 min into the backlog, at the times of the simulated records;
- 3 batches of 60 rows, `"stored": 60` each; the resent batch `"stored": 0, "duplicates": 60`;
- `/live/adab/` shows tiles updating every 15 s;
- on the VPS: `ls /srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/$(date -u +%Y/%m)/`.

Then remove the simulated data before the real logger starts (it uses the same device code). **Stop the service first**: it keeps an index of stored timestamps in memory, and deleting files under it would make it drop the real logger's rows as duplicates (owner approves the stop and start):
```bash
cd /opt/arkan-monitoring/server && docker compose stop ingest
```

```bash
sudo rm -r /srv/arkan-monitoring/data/sites/adab/LOG-0001/raw /srv/arkan-monitoring/data/sites/adab/LOG-0001/alarm-state.json /srv/arkan-monitoring/data/sites/adab/alarms
```

```bash
docker compose start ingest
```

## 9. Backup (owner's crontab)

```bash
crontab -e
```
Add:
```
30 2 * * * /opt/arkan-monitoring/server/deploy/backup.sh >> /srv/arkan-monitoring/backups/backup.log 2>&1
```
And, if wanted, the daily summary at 00:20 WITA (16:20 UTC on a UTC server):
```
20 16 * * * docker exec arkan-monitoring-ingest python tools/manage.py daily adab >/dev/null
```

## 10. Everyday operations

| Task | Command (in `/opt/arkan-monitoring/server`) |
|---|---|
| Status of every logger | `docker compose exec ingest python tools/manage.py list` |
| Service log | `docker compose logs --tail 100 ingest` |
| Restart | `docker compose restart ingest` (owner approves) |
| Update | `git fetch --tags && git checkout <tag> && docker compose up -d --build` |
| Daily summary | `docker compose exec ingest python tools/manage.py daily adab` |
| Alarm log | `docker compose exec ingest python tools/manage.py alarms adab` (open alarms + last lines); the file: `/srv/arkan-monitoring/data/sites/adab/alarms/2026.csv` |
| Change a threshold | edit `/srv/arkan-monitoring/data/alarm-register.csv` in Excel (or a per-site copy in `sites/adab/alarm-register.csv`); applies at the next record. To see what it would have given on past data: `docker compose stop ingest`, `docker compose run --rm ingest python tools/manage.py alarms adab --rebuild`, `docker compose start ingest` (A01 and A18 lines are kept) |
| Change a logger setting remotely | `manage.py set-config LOG-0001 th1_off_t=-1.2 reboot_hr=19` (taken within 15 min, the logger restarts); `manage.py show-config LOG-0001` to check. Network settings are refused: on site only |
| OED files | `docker compose exec ingest python tools/manage.py export-oed adab --from 2026-11-01` |
| SD card backfill | copy the card's `/data` to `/srv/arkan-monitoring/data/export/sd-LOG-0001/`, then with the service stopped (`docker compose stop ingest`): `docker compose run --rm ingest python tools/manage.py backfill adab LOG-0001 /data/export/sd-LOG-0001`, the same with `alarms adab --rebuild`, then `docker compose start ingest` |
| Firmware update (OTA) | the **Firmware update** panel of the logger on its live page (GitHub release, file upload or stored file; needs `ADMIN_USERS` in `server/.env`): [`OTA.md`](OTA.md). By command: copy `firmware.bin` to the data folder, `manage.py publish-fw /data/firmware.bin --device LOG-0001`. An online logger takes it within a minute, else within 6 h (`ota_on` is on by default) |
| Read the data from the laptop | `scp -r hermes-vps:/srv/arkan-monitoring/data/sites/adab ./adab` |

## 11. Security notes
- The container publishes on `127.0.0.1` only; Caddy is the only way in.
- Tokens: 32 random characters, stored as SHA-256 hashes, revocable (`disable-device`, `rotate-token`).
- Every upload is checked (header names, field count, characters, timestamps); bad rows are counted and dropped, never stored.
- Not done yet: a rate limit per device (Caddy body limits are in place). Low risk with one logger; to add with more sites.
