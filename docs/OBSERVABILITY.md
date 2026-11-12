# Observability (Phase 6)

## Logs

Structured JSON to stdout (`app/core/logging`), one object per line, with `correlation_id` (from
`X-Request-ID` or generated), `user_id` when authenticated, and component. Secrets, cookies, tokens, passwords,
OTPs, email bodies and form values are never logged; URLs are reduced to host where they could carry query
secrets. nginx emits JSON access logs with the same request id.

## Metrics (Prometheus)

`GET /api/v1/metrics` — enabled by `METRICS_ENABLED`, protected by `METRICS_TOKEN` (Bearer) and blocked at nginx.

| Metric | Type | Labels |
|---|---|---|
| `taskpilot_http_requests_total` | counter | method, status_class |
| `taskpilot_http_request_duration_seconds` | histogram | method |
| `taskpilot_tasks_total`, `taskpilot_tasks_failed_total` | counter | state / error code |
| `taskpilot_task_duration_seconds` | histogram | |
| `taskpilot_planning_duration_seconds` | histogram | |
| `taskpilot_llm_requests_total`, `taskpilot_llm_errors_total`, `taskpilot_llm_tokens_total` | counter | provider, model, direction |
| `taskpilot_browser_sessions_active` | gauge | |
| `taskpilot_browser_action_duration_seconds`, `taskpilot_browser_action_failures_total`, `taskpilot_browser_launch_failures_total` | histogram/counter | action |
| `taskpilot_selector_recovery_total`, `taskpilot_selector_recovery_success_total` | counter | |
| `taskpilot_approval_pending` (gauge), `taskpilot_approval_expired_total` | | |
| `taskpilot_queue_depth` (gauge), `taskpilot_queue_wait_duration_seconds` (histogram) | | queue |
| `taskpilot_websocket_connections_active` (gauge), `taskpilot_websocket_reconnect_total` | | |
| `taskpilot_file_download_bytes`, `taskpilot_file_download_failures_total` | | |
| `taskpilot_workflow_partial_success_total` | counter | |
| `taskpilot_persistence_write_failures_total`, `taskpilot_errors_total` | counter | component |

Alert rules: `deployment/monitoring/alert_rules.yml` (API down, 5xx ratio, persistence failures, queue backlog,
LLM errors, browser launch failures, slow planning, approvals piling up).

## Tracing

`app/observability/tracing.py` creates OpenTelemetry spans through `opentelemetry-api` around planning jobs (`planning.job`), LLM
calls (`llm.structured_output`) and browser steps (`browser.step`), tagged with the correlation id and redacted, low-cardinality attributes. **No exporter/SDK is bundled**: without
an OpenTelemetry SDK configured in the deployment, spans are no-ops. Add `opentelemetry-sdk` + an OTLP exporter
to ship traces.

## Health endpoints

| Endpoint | Auth | Meaning |
|---|---|---|
| `GET /api/v1/health/live` | public | process is up (no dependency checks) |
| `GET /api/v1/health/ready` | public | 200 only if database, Redis (when configured), planner and configuration are OK; 503 otherwise with per-check status |
| `GET /api/v1/health/details` | OWNER or `METRICS_TOKEN` | versions, provider/model, circuit state, pending approvals, write failures, rate-limiter degradation, queue backend, egress proxy configured |
| `GET /api/v1/health` | public | Phase 1 compatible summary |

The dashboard's **System status** card (Task History page) shows readiness to everyone and details to OWNERs.

## Audit trail

Security-relevant events (login success/failure, logout, refresh replay, role/disable changes, approvals
created/decided/consumed/withdrawn, purchases, drafts, calendar events, file download/delete, recovery decisions)
are appended to the hash-chained `audit_events` table by `AuditService` (fed by a telemetry tap). Metadata is
filtered to a safe key list; URLs keep the host only.

* `GET /api/v1/audit` — own events (OWNER: `?all_users=true`), keyset pagination.
* `GET /api/v1/audit/verify` — OWNER: recompute the chain.
* `GET /api/v1/audit/export` — OWNER: NDJSON export for archival.
