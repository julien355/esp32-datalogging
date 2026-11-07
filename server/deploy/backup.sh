#!/usr/bin/env bash
# Nightly backup of the monitoring data folder: one tar.gz per night, the last 14 kept.
# Crontab of the owner (crontab -e), 02:30 server time:
#   30 2 * * * /opt/arkan-monitoring/server/deploy/backup.sh >> /srv/arkan-monitoring/backups/backup.log 2>&1
set -euo pipefail
SRC=/srv/arkan-monitoring/data
DST=/srv/arkan-monitoring/backups
KEEP=14
stamp=$(date -u +%Y%m%dT%H%MZ)
tar -C "$(dirname "$SRC")" -czf "$DST/data-$stamp.tar.gz.part" "$(basename "$SRC")"
mv "$DST/data-$stamp.tar.gz.part" "$DST/data-$stamp.tar.gz"
ls -1t "$DST"/data-*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$(date -u +%FT%TZ) backup ok: $DST/data-$stamp.tar.gz ($(du -h "$DST/data-$stamp.tar.gz" | cut -f1))"
