# Operations Runbook (Phase 6)

All commands assume `C="docker compose -f deployment/docker-compose.prod.yml --env-file deployment/.env.production"`.

## Daily

* `deployment/scripts/health_check.sh https://<host>`
* Check alerts (Prometheus `--profile monitoring`).
* Backups ran (`ls runtime/backups`), copied off-host.

## Alerts → actions

| Alert | First checks | Action |
|---|---|---|
| TaskPilotApiDown | `$C ps`, `$C logs --tail=200 api` | Restart api; if config error, the log names the unsafe setting |
| TaskPilotPersistenceFailures | `$C logs postgres`, disk space | Fix DB; tasks during the outage may lack history; recovery handles the rest on restart |
| TaskPilotQueueBacklog | `/health/details` queue, Redis memory | Check for a stuck browser session; restart api (jobs are re-delivered; journal prevents repeats) |
| TaskPilotLlmErrors | provider status page; `/health/details` circuit | Wait for the breaker; check key/quota; `LLM_DAILY_TOKEN_BUDGET` |
| TaskPilotBrowserLaunchFailures | `$C logs api`, memory (`docker stats`) | Increase `mem_limit`/`shm_size`, lower `BROWSER_MAX_SESSIONS` |
| TaskPilotHighErrorRate | nginx JSON logs by `request_id` | Correlate with api logs (`correlation_id`) |

## Common tasks

| Task | How |
|---|---|
| Restart api safely | `$C restart api` — in-flight runs become FAILED/UNKNOWN with a note; approvals WITHDRAWN |
| Disable a user | OWNER via `AuthService.disable` (admin UI not built): `$C exec api python -m app.cli disable-user <email>` *(not implemented — use SQL: `UPDATE users SET status='DISABLED', token_version=token_version+1 WHERE email=…`)* |
| Force everyone to sign in again | rotate `APP_SECRET_KEY`, restart api |
| Inspect dead-letter jobs | `$C exec redis redis-cli -a … LRANGE tp:q:execution:dead 0 20` |
| Verify audit chain | OWNER `GET /api/v1/audit/verify` |
| Export audit | OWNER `GET /api/v1/audit/export > audit-$(date +%F).ndjson` |
| Apply migrations | `$C run --rm migrate` |
| Rotate DB password | update `.env.production` + `ALTER USER`, restart api |

## Incident: suspected duplicate order / draft

1. Find the task in Task History; open the recovery note.
2. `action_journal` rows for the task: `SELECT step_order, action_type, lifecycle, attempt, worker_id FROM action_journal WHERE task_id=…`.
3. `UNKNOWN` means TaskPilot could not confirm whether the click landed — check the website's order history.
4. Audit: `purchase.submission` events for the task (`GET /api/v1/audit?…`).

## Incident: suspected SSRF / unexpected outbound traffic

1. `$C logs egress` — squid logs every request with destination and decision.
2. Confirm the api has no direct route: see [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md#post-deploy-verification).

## Weekly / monthly

* `deployment/scripts/cleanup.sh` (cron daily is fine).
* Restore drill into a scratch database (monthly).
* Rebuild images for OS/Chromium security updates; review `security.yml` results (pip-audit, npm audit, bandit).
