#!/usr/bin/env bash
# Daily backup of the eb1_annotation Postgres DB (docker container
# eb1-annotation-pg). Writes a timestamped pg_dump custom-format archive to
# backups/ (gitignored) and prunes to the most recent $RETENTION dumps.
#
# Run manually:  scripts/backup-db.sh
# Scheduled via cron (see crontab -l). cron has a minimal PATH, so common
# Docker locations are prepended below.
set -euo pipefail

export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

CONTAINER="eb1-annotation-pg"
DB="eb1_annotation"
DB_USER="eb1"
RETENTION="${RETENTION:-14}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/backups"
mkdir -p "$BACKUP_DIR"

stamp() { date "+%Y-%m-%dT%H:%M:%S"; }

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  echo "[$(stamp)] ERROR: container $CONTAINER is not running; skipping backup" >&2
  exit 1
fi

OUT="$BACKUP_DIR/${DB}-$(date +%Y%m%d-%H%M%S).dump"
echo "[$(stamp)] backing up $DB from $CONTAINER -> $OUT"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB" > "$OUT"

# Keep only the newest $RETENTION dumps.
find "$BACKUP_DIR" -maxdepth 1 -type f -name "${DB}-*.dump" | sort -r \
  | tail -n "+$((RETENTION + 1))" | while read -r old; do
    echo "[$(stamp)] pruning $old"
    rm -f "$old"
  done

echo "[$(stamp)] backup complete ($(du -h "$OUT" | cut -f1))"
