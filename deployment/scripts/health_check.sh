#!/usr/bin/env sh
# Probe liveness and readiness. Exit 0 only when the API reports ready.
# Usage: deployment/scripts/health_check.sh [base_url]   (default https://localhost)
set -u

BASE="${1:-https://localhost}"
CURL="curl -fsS --max-time 8 ${HEALTH_CHECK_INSECURE:+-k}"
status=0

if $CURL "$BASE/api/v1/health/live" > /dev/null; then
  echo "live:  ok"
else
  echo "live:  FAILED"; status=1
fi

ready="$($CURL "$BASE/api/v1/health/ready" 2>/dev/null)" || { echo "ready: FAILED ${ready:-}"; status=1; }
[ "$status" -eq 0 ] && echo "ready: $ready"

if [ -n "${METRICS_TOKEN:-}" ] && [ -n "${INTERNAL_API_URL:-}" ]; then
  $CURL -H "Authorization: Bearer $METRICS_TOKEN" "$INTERNAL_API_URL/api/v1/health/details" || status=1
fi
exit "$status"
