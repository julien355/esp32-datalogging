# Keeping RAM low on hermes-vps

hermes-vps already runs the Hub, the CMMS, Hermes and other services. The monitoring platform adds three processes: PostgreSQL (OED), Node.js (OED) and the ingest service (Python).

## Where the memory goes, and what we do about it

| Part | Default behaviour | What we change | Expected after tuning |
|---|---|---|---|
| **OED web, at start** | OED's compose runs `installOED.sh` at every start: `npm ci` (installs all packages, including the build tools) and `webpack build` (builds the front end). That needs **1 to 2 GB** for a few minutes at each restart, and the image is the full `node:18` | **Build once, run lean.** Our own Dockerfile (multi-stage): stage 1 runs `npm ci` and `webpack build`, **on the laptop or in GitHub Actions, not on the VPS**; stage 2 is `node:18-slim` with production packages and the built bundle, and starts with `node ./src/bin/www`. No build on the VPS, ever | No start-up spike |
| **OED web, running** | Node.js takes heap as it likes | `NODE_OPTIONS=--max-old-space-size=192`; container `mem_limit: 320m` | about 150 to 250 MB |
| **OED scheduled jobs** | OED's cron scripts run `docker compose run --rm web ...`, which starts a **second** web container each time (hourly view refresh) | Run them inside the running container with `docker compose exec web npm run refreshHourlyReadingViews` (and the daily one), or call the refresh from the ingest service after a push | No extra container |
| **PostgreSQL (OED)** | Default settings, sized for a dedicated server | `shared_buffers=48MB`, `max_connections=15`, `work_mem=4MB`, `maintenance_work_mem=32MB`, `effective_cache_size=192MB`, `autovacuum_max_workers=1`; container `mem_limit: 256m` | about 80 to 150 MB |
| **OED data volume** | | Only 1-minute readings go to OED (no 15-second readings, `docs/LIVE.md`), and per-phase V, A, PF only if wanted. One site with ~6 meters is ~3 million rows a year | Small tables, small cache |
| **Ingest service** | | Python standard library, one process, no database; the live buffer is a few kB per site; container `mem_limit: 96m` | about 25 to 40 MB |
| **Docker logs** | Grow without limit | `logging: max-size 10m, max-file 3` on every container | Disk, not RAM, but keeps the VPS healthy |

**Total for the platform: about 300 to 450 MB** in normal running, against 1 to 2 GB (plus build spikes) with OED's default compose. These are estimates: **S3 measures them** with `docker stats` on a local run with a simulated logger, and the numbers go into this file.

## On the VPS itself (owner, with `sudo`)
- Check what is free before S5: `free -h` and `docker stats --no-stream`.
- If no swap file is set up, add one of 1 to 2 GB, as a safety net, not as working memory: `fallocate -l 2G /swapfile`, `mkswap`, `swapon`, plus a line in `/etc/fstab`; `vm.swappiness=10`.
- The `mem_limit` on each container means a leak in the platform stops that container (Docker restarts it) instead of starving the Hub, the CMMS or Hermes.

## If RAM is still short
1. Do not send per-phase V, A, PF to OED; keep them in the site files and on the live page only.
2. Lower the limits above step by step while watching `docker stats` and OED's response times.
3. Last resort: run OED on a small second VPS and keep the ingest service on hermes-vps. The ingest service, the alarms and the live page do not need OED to run, so nothing is lost while OED moves.
