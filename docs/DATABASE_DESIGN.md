# Database Design (Phase 6)

SQLAlchemy 2.0 (async) with Alembic migrations. **PostgreSQL 16 (asyncpg) in production; SQLite (aiosqlite)
for development and tests only** — the production validator rejects any non-`postgresql+asyncpg://` URL.

> Verification: the schema and every repository are exercised by the test suite on SQLite. The Alembic migration
> round-trip (upgrade → check → downgrade → upgrade) was run on SQLite. **PostgreSQL itself was not available on
> the development machine**; the CI workflow `integration-tests.yml` runs the migrations on PostgreSQL but has
> not been executed yet.

## Principles

* **Write-through:** the database is authoritative; in-memory structures (task cache, approval coordinator,
  session ownership cache) are caches rebuilt or validated from the DB.
* **Best-effort writes never block the agent loop,** but they are not fire-and-forget: `Persistence.best_effort`
  runs each write in its own task, shielded from caller cancellation and tracked; shutdown drains them before
  disposing the engine. Failures increment `taskpilot_persistence_write_failures_total` (alerted).
* **Redaction before storage:** conversation turns are stored redacted (emails, phone numbers, OTP-like codes,
  card-like numbers, tokens) with a TTL. Passwords and website credentials are never stored.
* **UTC everywhere:** `UtcDateTime` stores timezone-aware UTC on every backend.
* SQLite: WAL mode, foreign keys on, single-writer asyncio lock (SQLite cannot handle concurrent writers).

## Tables

| Table | Purpose | Key columns / indexes |
|---|---|---|
| `users` | Local accounts | `email` unique, `password_hash` (Argon2id), `role` OWNER/MEMBER/READ_ONLY, `status`, `token_version` (logout-all) |
| `refresh_tokens` | Rotating refresh tokens | `token_hash` (SHA-256, never the token), `family_id`, `used_at`, `revoked_at`; replay of a used token revokes the family |
| `app_sessions` | Dashboard session → owner | `session_id` PK, `user_id`; first authenticated use claims a session |
| `tasks` | Task lifecycle | `state`, `error_code`, `execution_status`, `recovery_note`; idx (session, created), (user, created), state |
| `plans` | Validated plan JSON per task | provider/model/schema version, clarifications |
| `action_journal` | Execution journal (idempotency) | `idempotency_key` unique, `lifecycle` PENDING…UNKNOWN, `mutating`, `attempt`, `worker_id` |
| `approvals` | One-time approvals | `snapshot_hash`, `status` (+WITHDRAWN), `used_at`, `version` (optimistic lock) |
| `workflows` | Multi-domain workflow state | `state_json`, `status` |
| `conversation_turns` | Redacted memory | `expires_at` TTL, idx (session, created) |
| `files` | Downloaded file metadata | `sha256`, `scan_status`, `expires_at`, `deleted_at`; quotas via (user, created) |
| `browser_sessions` | Session lifecycle (no cookies) | `status`, `persisted` (always false in production) |
| `integration_statuses` | Last seen Gmail/Calendar/YouTube status | (session, domain) |
| `llm_usage` | Token/cost accounting | provider, model, tokens, latency, estimated cost |
| `audit_events` | Append-only hash chain | `seq`, `prev_hash`, `hash` = SHA-256(prev_hash ‖ canonical fields) |

## Audit chain

`AuditRepository.append` takes a PostgreSQL advisory transaction lock (SQLite: the writer lock), reads the
last hash, and stores `hash = sha256(prev_hash + canonical_json(fields))`. `GET /api/v1/audit/verify` (OWNER)
recomputes the chain and reports the first broken `seq`. The chain detects modification or deletion of rows; it
does **not** prevent a database superuser from rewriting the whole chain — export it regularly
(`GET /api/v1/audit/export`, NDJSON) to write-once storage.

## Migrations

```
cd backend
python -m alembic upgrade head      # production: run by the one-shot `migrate` service
python -m alembic check             # fails if models and migrations drift
```

`migrations/versions/0001_initial_phase_6_initial_schema.py` creates the full schema. SQLite uses
`render_as_batch`. With `DATABASE_AUTO_CREATE=true` (dev/test default) tables are created on startup; production
requires `false` and refuses to start if the schema is missing.

## Retention

| Data | Retention | Mechanism |
|---|---|---|
| Conversation turns | `MEMORY_TTL_MINUTES` | sweeper `run_maintenance()` (~5 min) |
| Files | `FILE_DOWNLOAD_TTL_HOURS` | disk purge + `files.expire_overdue()` so quotas free up |
| Audit | `AUDIT_RETENTION_DAYS` (365) | **manual** — export, then prune; never automatic |
| Refresh tokens | TTL | expired rows are rejected; pruning is manual |
