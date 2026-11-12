#!/usr/bin/env sh
# Restore a PostgreSQL backup made by backup_database.sh.
# Usage: deployment/scripts/restore_database.sh runtime/backups/taskpilot_YYYYMMDDTHHMMSSZ.dump
# Stops the api first so no task runs against a half-restored database. After restore, the api's startup
# recovery marks interrupted work FAILED/UNKNOWN and withdraws pending approvals — nothing resumes automatically.
set -eu

DUMP="${1:?usage: restore_database.sh <path-to-dump>}"
NAME="$(basename "$DUMP")"
DIR="$(dirname "$DUMP")"
COMPOSE="docker compose -f $(dirname "$0")/../docker-compose.prod.yml --env-file $(dirname "$0")/../.env.production"

if [ -f "$DUMP.sha256" ]; then
  ( cd "$DIR" && sha256sum -c "$NAME.sha256" )
else
  echo "WARNING: no checksum file for $NAME; continuing." >&2
fi

printf "This REPLACES the current database with %s. Type RESTORE to continue: " "$NAME"
read -r answer
[ "$answer" = "RESTORE" ] || { echo "Aborted."; exit 1; }

$COMPOSE stop api nginx
$COMPOSE exec -T postgres sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB" "/backups/'"$NAME"'"'
$COMPOSE run --rm migrate
$COMPOSE start api nginx
echo "Restore complete. Verify with deployment/scripts/health_check.sh and GET /api/v1/audit/verify (OWNER)."
