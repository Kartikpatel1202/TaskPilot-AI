# Production Deployment (Phase 6)

> **Status: NOT TESTED.** The Docker daemon was not running on the development machine. `docker compose config`
> validated the file (including the `monitoring` and `scanning` profiles), but no image was built and the stack
> was never started. Treat the first deployment as a staging exercise.

## Files

| Path | Purpose |
|---|---|
| `backend/Dockerfile` | Python 3.11 slim + Playwright Chromium, non-root uid 10001 |
| `frontend/Dockerfile` | Next.js multi-stage build, non-root |
| `deployment/docker-compose.prod.yml` | nginx, frontend, migrate (one-shot), api, egress (squid), postgres, redis, optional clamav/prometheus |
| `deployment/nginx/nginx.conf`, `security.conf` | TLS, headers, edge rate limits, WS upgrade, blocks `/metrics` and `/health/details` |
| `deployment/egress/squid.conf` | outbound policy (deny private/loopback/link-local/metadata, ports 80/443) |
| `deployment/redis/redis.conf` | AOF persistence, `noeviction`, dangerous commands disabled |
| `deployment/monitoring/prometheus.yml`, `alert_rules.yml` | scraping + alerts |
| `deployment/scripts/*.sh` | backup, restore, health check, cleanup |
| `deployment/.env.production.example` | every required setting |

## Steps

1. **Host:** Linux with Docker Engine ≥ 24 and Compose v2; firewall allows only 80/443 (and SSH).
2. **Secrets:** `cp deployment/.env.production.example deployment/.env.production`; replace every `CHANGE_ME`
   (`APP_SECRET_KEY` ≥ 32 random chars, DB/Redis passwords, `METRICS_TOKEN`, LLM key). `chmod 600`.
   Write `METRICS_TOKEN` to `deployment/monitoring/metrics_token` if using the monitoring profile.
3. **TLS:** place `fullchain.pem` and `privkey.pem` in `deployment/nginx/certs/` (or set `TLS_CERT_DIR`).
4. **Build & start:**
   ```
   docker compose -f deployment/docker-compose.prod.yml --env-file deployment/.env.production up -d --build
   ```
   `migrate` runs `alembic upgrade head` and must succeed before `api` starts.
5. **First OWNER:** set `BOOTSTRAP_OWNER_EMAIL/PASSWORD` for the first start, then remove the password and
   restart. Keep `REGISTRATION_ENABLED=false` unless open signup is intended.

The api refuses to start if any production safety rule is violated (SQLite, auth off, dev bypass, no Redis queue,
no egress proxy, demo endpoints, insecure cookies/CSRF off, persisted browser sessions, rate limiting off, mock LLM
without explicit override).

## Post-deploy verification

Run these before calling the deployment production-ready (none have been run yet):

1. `deployment/scripts/health_check.sh https://<host>` → `ready`.
2. From the api container, prove egress enforcement:
   ```
   docker compose … exec api python -c "import httpx; print(httpx.get('http://169.254.169.254/', proxy='http://egress:3128', timeout=5).status_code)"   # expect 403
   docker compose … exec api python -c "import httpx; httpx.get('https://example.com', timeout=5)"                                                       # expect connection failure (no direct route)
   docker compose … exec api python -c "import httpx; print(httpx.get('https://example.com', proxy='http://egress:3128', timeout=10).status_code)"   # expect 200
   ```
3. Unauthenticated `GET /api/v1/tasks` → 401; `/api/v1/metrics` via nginx → 404.
4. Sign in, run a planning-only command, restart the api (`docker compose restart api`), confirm the task is
   still visible in Task History and pending approvals show WITHDRAWN.
5. Back up and restore into a scratch database ([DISASTER_RECOVERY.md](DISASTER_RECOVERY.md)).

## Known deployment limits

* One api replica (WebSocket fan-out is in-process).
* Chromium runs inside the api container (no separate browser worker).
* No OpenTelemetry exporter is bundled.
* ClamAV is optional; without it downloads are marked `SCAN_UNAVAILABLE` and the UI says so.
* Image tags (`nginx:1.27-alpine`, `postgres:16-alpine`, `redis:7.4-alpine`, `ubuntu/squid:6.6-24.04_beta`,
  `prom/prometheus:v2.55.1`, `clamav/clamav:1.4`) should be pinned by digest and rebuilt regularly.
