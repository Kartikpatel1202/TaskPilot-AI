#!/usr/bin/env sh
# Logical PostgreSQL backup (custom format, compressed) with a SHA-256 checksum and retention.
# Usage: deployment/scripts/backup_database.sh [retention_days]
# Requires the production compose stack to be running. Backups land in runtime/backups/ (mounted at /backups).
set -eu

COMPOSE="docker compose -f $(dirname "$0")/../docker-compose.prod.yml --env-file $(dirname "$0")/../.env.production"
RETENTION_DAYS="${1:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="taskpilot_${STAMP}.dump"
BACKUP_DIR="$(dirname "$0")/../../runtime/backups"

mkdir -p "$BACKUP_DIR"
echo "Creating backup $NAME ..."
$COMPOSE exec -T postgres sh -c 'pg_dump --format=custom --compress=9 --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "/backups/'"$NAME"'"'

# Verify the archive is readable before declaring success.
$COMPOSE exec -T postgres pg_restore --list "/backups/$NAME" > /dev/null
( cd "$BACKUP_DIR" && sha256sum "$NAME" > "$NAME.sha256" )
echo "Backup verified: $BACKUP_DIR/$NAME"

# Retention: delete dumps (and their checksums) older than RETENTION_DAYS.
find "$BACKUP_DIR" -name 'taskpilot_*.dump*' -type f -mtime "+$RETENTION_DAYS" -print -delete
echo "Done. Copy backups off-host (encrypted) — a backup on the same disk is not disaster recovery."
