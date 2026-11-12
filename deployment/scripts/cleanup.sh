#!/usr/bin/env sh
# Housekeeping for a production host. The API itself expires downloads, memory and approvals on its sweeper;
# this script covers host-level leftovers. Safe to run from cron (daily).
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

# Old backups (keep the checksum alongside).
find "$ROOT/runtime/backups" -name 'taskpilot_*.dump*' -type f -mtime "+$BACKUP_RETENTION_DAYS" -print -delete 2>/dev/null || true

# Dangling images from previous builds (never removes volumes or running containers).
docker image prune -f --filter "label!=keep" > /dev/null 2>&1 || true

echo "Cleanup finished. Audit records are never deleted by this script (retention is AUDIT_RETENTION_DAYS, exported first)."
