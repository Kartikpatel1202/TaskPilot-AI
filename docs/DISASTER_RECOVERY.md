# Disaster Recovery (Phase 6)

> Status: scripts written and reviewed; **not executed** — no PostgreSQL/Docker was available on the
> development machine. Run a restore drill before relying on them.

## What must be protected

| Data | Where | Loss impact |
|---|---|---|
| PostgreSQL (`pgdata` volume) | users, tasks, plans, journal, approvals, audit | **Critical** — accounts and audit trail |
| Downloads (`downloads` volume) | user files, TTL-bound | Low — re-downloadable, expire anyway |
| Redis (`redisdata`, AOF) | queued jobs, locks, rate counters | Low — jobs re-derivable; journal prevents repeats |
| Secrets (`.env.production`, TLS keys) | host | Critical — keep in a secret manager |

Browser cookies are never persisted in production, so there is no browser state to back up.

## Objectives (targets, not measured)

* RPO ≤ 24 h with daily backups (lower it with WAL archiving / managed PostgreSQL PITR).
* RTO ≈ 1 h for a single-host rebuild from images + latest dump.

## Backup

```
deployment/scripts/backup_database.sh 14     # pg_dump -Fc, verify with pg_restore --list, sha256, 14-day retention
```

Schedule daily (cron/systemd timer). **Copy dumps off-host, encrypted** (e.g. `age`/`gpg` + object storage with
object lock). Export the audit log monthly: `GET /api/v1/audit/export` → write-once storage.

## Restore

```
deployment/scripts/restore_database.sh runtime/backups/taskpilot_<stamp>.dump
```

The script checks the checksum, asks for confirmation, stops api/nginx, `pg_restore --clean`, runs migrations,
and restarts. On start the api's recovery:

* marks in-flight executions FAILED (`EXECUTION_INTERRUPTED`) and uncertain steps UNKNOWN,
* withdraws every pending approval,
* closes browser sessions.

Nothing resumes automatically. Users must re-run tasks and re-approve sensitive steps — this is deliberate: a
restored database can be hours old, and replaying purchases or drafts from it would be unsafe.

## After restore checklist

1. `deployment/scripts/health_check.sh https://<host>` → ready.
2. OWNER: `GET /api/v1/audit/verify` → chain intact up to the restored point.
3. Tell users that tasks after the backup time are lost and any order/draft/event made after it must be checked
   on the website itself.
4. Rotate `APP_SECRET_KEY` if the incident involved host compromise (invalidates all sessions).

## Full host loss

Provision a host with Docker → restore `.env.production` and TLS certs from the secret manager → `docker compose
… up -d postgres redis` → restore the latest dump → `up -d`.
