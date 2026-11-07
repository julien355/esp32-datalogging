#!/usr/bin/env bash
# One-time VPS preparation for the monitoring ingest service. Run by the OWNER with sudo:
#   sudo bash setup-vps.sh            (checks only, changes nothing: add --apply to make the changes)
#   sudo bash setup-vps.sh --apply
# What it does with --apply:
#   1. checks Docker and the compose plugin are installed (does not install them: see docs/VPS-SETUP.md)
#   2. creates the dedicated data folder /srv/arkan-monitoring/{data,backups} owned by uid 1000
#   3. creates the data layout (sites/, firmware/, logs/, export/, devices.json)
#   4. checks port 8800 is free and prints the next steps
# It never touches Caddy, Hermes or other services, and never overwrites an existing file.
set -euo pipefail

APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
BASE=/srv/arkan-monitoring
DATA=$BASE/data
OWNER_UID=1000
PORT=8800

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
run()  { if [[ $APPLY == 1 ]]; then say "+ $*"; "$@"; else say "(would run) $*"; fi; }

step "Docker"
if command -v docker >/dev/null; then say "docker: $(docker --version)"; else say "MISSING: install Docker first (docs/VPS-SETUP.md section 2)"; exit 1; fi
if docker compose version >/dev/null 2>&1; then say "compose: $(docker compose version --short)"; else say "MISSING: docker compose plugin"; exit 1; fi

step "Memory (the service is limited to 96 MB)"
free -h || true

step "Port $PORT on the loopback"
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then say "PORT $PORT IS IN USE: set INGEST_PORT in server/.env and in monitoring.caddy"; else say "free"; fi

step "Data folder $DATA"
for d in "$BASE" "$DATA" "$DATA/sites" "$DATA/firmware" "$DATA/logs" "$DATA/export" "$BASE/backups"; do
  if [[ -d $d ]]; then say "exists: $d"; else run mkdir -p "$d"; fi
done
if [[ ! -f $DATA/devices.json ]]; then
  if [[ $APPLY == 1 ]]; then printf '{\n  "devices": {}\n}\n' > "$DATA/devices.json"; say "+ created $DATA/devices.json"; else say "(would create) $DATA/devices.json"; fi
else
  say "exists: $DATA/devices.json (kept)"
fi
run chown -R $OWNER_UID:$OWNER_UID "$BASE"
run chmod 750 "$BASE" "$DATA" "$BASE/backups"

step "Next steps"
cat <<TXT
1. Code:   git clone <repo> /opt/arkan-monitoring   (the whole repository: the image takes docs/alarms/alarms.csv)
2. Start:  cd /opt/arkan-monitoring/server && docker compose up -d --build
3. Check:  curl -s http://127.0.0.1:$PORT/health
           docker compose exec ingest python tools/manage.py init     (copies the alarm register)
4. Site:   docker compose exec ingest python tools/manage.py add-site adab --name "Adab hotel" --contracted-kva 82.5 --rated-a 200
           docker compose exec ingest python tools/manage.py add-device adab LOG-0001
5. Caddy:  copy deploy/monitoring.caddy to /opt/edge/sites/, caddy validate, then reload (owner)
6. Backup: crontab line in deploy/backup.sh
TXT
[[ $APPLY == 1 ]] || say $'\nNothing was changed. Run again with --apply.'
