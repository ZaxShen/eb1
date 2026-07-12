#!/usr/bin/env bash
# Daily backup of the annotation Postgres DB to Google Cloud Storage.
#
# Dumps the DB from the running compose container (pg_dump custom format) to a
# local temp file, uploads it to gs://$GCS_BACKUP_BUCKET/, then removes the temp
# file. Retention is handled by a GCS lifecycle rule (see RUNBOOK.md), not here.
#
# Uploads use the VM's default compute service account (keyless) via `gcloud`.
# Run manually or from cron on the VM:
#
#   GCS_BACKUP_BUCKET=my-bucket annotation/deploy/backup-gcs.sh
#
# cron has a minimal PATH, so common tool locations are prepended below.
set -euo pipefail

export PATH="/usr/local/bin:/snap/bin:/opt/homebrew/bin:$PATH"

CONTAINER="${BACKUP_CONTAINER:-eb1-annotation-pg}"
DB="${BACKUP_DB:-eb1_annotation}"
DB_USER="${BACKUP_DB_USER:-eb1}"
BUCKET="${GCS_BACKUP_BUCKET:?set GCS_BACKUP_BUCKET to the target bucket name}"

stamp() { date "+%Y-%m-%dT%H:%M:%S"; }

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  echo "[$(stamp)] ERROR: container $CONTAINER is not running; skipping backup" >&2
  exit 1
fi

TMP="$(mktemp -t "${DB}-backup.XXXXXX.dump")"
trap 'rm -f "$TMP"' EXIT

OBJECT="${DB}-$(date +%Y%m%d-%H%M%S).dump"
echo "[$(stamp)] dumping $DB from $CONTAINER -> $TMP"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB" > "$TMP"

echo "[$(stamp)] uploading -> gs://${BUCKET}/${OBJECT} ($(du -h "$TMP" | cut -f1))"
gcloud storage cp "$TMP" "gs://${BUCKET}/${OBJECT}"

echo "[$(stamp)] backup complete"
