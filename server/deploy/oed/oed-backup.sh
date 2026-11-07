#!/usr/bin/env bash
# DRAFT, NOT TESTED.
# Nightly dump of OED's database (pg_dump), gzip, the last 14 kept. Beside backup.sh (the data folder).
# Crontab of user ai (crontab -e), 02:40 server time:
#   40 2 * * * /opt/arkan-monitoring/server/deploy/oed/oed-backup.sh >> /srv/arkan-monitoring/backups/backup.log 2>&1
set -euo pipefail
DST=/srv/arkan-monitoring/backups
KEEP=14
stamp=$(date -u +%Y%m%dT%H%MZ)
docker exec arkan-oed-db pg_dump -U oed oed | gzip > "$DST/oed-$stamp.sql.gz.part"
mv "$DST/oed-$stamp.sql.gz.part" "$DST/oed-$stamp.sql.gz"
ls -1t "$DST"/oed-*.sql.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$(date -u +%FT%TZ) oed backup ok: $DST/oed-$stamp.sql.gz ($(du -h "$DST/oed-$stamp.sql.gz" | cut -f1))"
