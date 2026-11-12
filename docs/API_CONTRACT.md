# REST API contract (v1)

- **Base URL:** `http://localhost:8000/api/v1`
- **Content type:** JSON
- **Timestamps:** ISO-8601 UTC (e.g. `2026-11-05T10:00:00.123456Z`)
- **Identifiers:** UUIDs
- **Interactive docs:** `/docs` (Swagger) and `/redoc`

Every response carries an `X-Request-ID` header. Clients may send their own value (alphanumeric/dashes, ≤ 64 chars).

## Error format
Every non-2xx response has this shape:
```json
{ "code": "VALIDATION_ERROR", "message": "Request validation failed.", "request_id": "3f…", "details": [ { "loc": ["body","command"], "msg": "…", "type": "value_error" } ] }
```
`details` appears only for validation errors. Responses never include stack traces or internal exception text.

| HTTP | `code` | When |
| --- | --- | --- |
| 404 | `NOT_FOUND` | Unknown route, or a demo endpoint while disabled |
| 404 | `TASK_NOT_FOUND` / `APPROVAL_NOT_FOUND` | Unknown id |
| 409 | `APPROVAL_ALREADY_RESOLVED` | A decision already exists (decisions are immutable) |
| 409 | `INVALID_STATE_TRANSITION` | An illegal task transition was requested |
| 410 | `APPROVAL_EXPIRED` | The approval expired before the decision arrived |
| 422 | `VALIDATION_ERROR` | Body, path or query validation failed |
| 500 | `INTERNAL_ERROR` | Unexpected server error (details only in server logs) |

---

## `GET /health`
**200**
```json
{ "status": "healthy", "service": "taskpilot-backend", "version": "0.1.0", "timestamp": "2026-11-05T10:00:00Z" }
```
`timestamp` is generated per request, in UTC.

## `POST /tasks`
Records a command. **Phase 1 does not plan or execute anything.**

Request:
```json
{ "command": "Open Blinkit and prepare my grocery cart", "session_id": "UUID", "input_mode": "TEXT" }
```
| Field | Rules |
| --- | --- |
| `command` | string, trimmed, 1–4000 chars after trimming (`MAX_COMMAND_LENGTH`); empty or whitespace-only → 422 |
| `session_id` | UUID → otherwise 422 |
| `input_mode` | `"TEXT"` or `"VOICE"` |

**202 Accepted**
```json
{
  "task_id": "UUID",
  "session_id": "UUID",
  "state": "IDLE",
  "accepted": true,
  "message": "Task accepted. Agent planning will be available in a later phase.",
  "created_at": "2026-11-05T10:00:00Z"
}
```
Side effects on the session's WebSocket: `task.accepted`, then a `log.created` from Kamlesh Bhai (`source: "assistant"`, `language: "en" | "hi" | "hinglish"`).

Errors: 422.

## `GET /tasks/{task_id}`
**200** returns a `Task`:
```json
{ "task_id": "UUID", "session_id": "UUID", "command": "…", "input_mode": "TEXT", "state": "IDLE",
  "created_at": "…", "updated_at": "…", "error_message": null, "is_demo": false }
```
Errors: 404 `TASK_NOT_FOUND`, 422 (malformed UUID).

## `GET /tasks?session_id=UUID&limit=20`
**200** `{ "tasks": [Task, …] }`, newest first, scoped to the session. `limit` must be between 1 and 100.

## `POST /approvals/{approval_id}/decision`
Request:
```json
{ "decision": "APPROVE" }
```
`decision` is `"APPROVE"` or `"REJECT"`.

**200**
```json
{ "approval_id": "UUID", "decision": "APPROVE", "status": "APPROVED", "resolved_at": "2026-11-05T10:00:00Z" }
```
Rules:
- Only `PENDING` approvals can be decided.
- A second decision returns **409** `APPROVAL_ALREADY_RESOLVED`.
- An expired approval returns **410** `APPROVAL_EXPIRED`. It is marked `EXPIRED`, and `approval.resolved` is published with status `EXPIRED`.
- An unknown id returns **404**. A malformed id or decision returns **422**.

A successful decision publishes `approval.resolved`. **Phase 1 records the decision in memory only. It never triggers a real-world action.**

## `GET /approvals/{approval_id}`
**200** returns the full `ApprovalRequest` (see the WebSocket protocol). Errors: 404, 422.

---

## Phase 2: agent planning

### Changes to `POST /tasks`
- **Response message:** the 202 response is unchanged, except that `message` is now `"Task accepted. Kamlesh Bhai is preparing an action plan."`. The Phase 1 message is still used when `AGENT_PLANNING_ENABLED=false`.
- **Background planning:** the task is queued for planning. Its state moves `IDLE → PLANNING → PLANNED | NEEDS_CLARIFICATION | FAILED`.
- **503 when busy:** if the planner queue is full, the endpoint returns **503** `PLANNER_BUSY` with a `Retry-After` header. No task is created.

### `GET /tasks/{task_id}/plan?session_id=UUID`
`session_id` is an optional ownership check. **200** returns the validated `TaskPlan`, described in [ACTION_PLAN_SCHEMA.md](ACTION_PLAN_SCHEMA.md):
```json
{
  "plan_id": "UUID", "task_id": "UUID", "session_id": "UUID",
  "status": "READY", "intent": "ECOMMERCE_SHOPPING",
  "summary": "Prepare a shopping cart on Blinkit with Amul milk 2 litre, bread 1 packet, eggs 12 pieces.",
  "user_facing_message": "Haan bhai! Blinkit ka plan ready hai: …",
  "language": "hinglish", "target_website": "blinkit.com", "confidence": 0.95,
  "assumptions": ["…"], "clarification_question": null, "missing_information": [],
  "clarification_history": [], "steps": [ { "step_id": "UUID", "order": 1,
    "action": { "type": "navigate", "url": "https://blinkit.com", "purpose": "Open Blinkit" },
    "description": "Navigate to Blinkit.", "expected_outcome": "Blinkit is opened.",
    "risk_level": "LOW", "requires_approval": false, "depends_on": [] } ],
  "requires_human_approval": false, "provider": "mock", "model": "taskpilot-mock-v1",
  "is_mock": true, "created_at": "2026-11-05T10:00:00Z", "schema_version": "1.0"
}
```
The response never includes prompts, hidden reasoning, provider usage or secrets.

| HTTP | `code` | When |
| --- | --- | --- |
| 403 | `TASK_SESSION_MISMATCH` | `session_id` given and not the task's session |
| 404 | `TASK_NOT_FOUND` | Unknown task |
| 409 | `PLAN_NOT_READY` | Task still `IDLE` / `PLANNING` |
| 404 | `PLAN_NOT_FOUND` | Planning failed, or the task was never planned (e.g. demo tasks) |

### `POST /tasks/{task_id}/clarification`
Request:
```json
{ "session_id": "UUID", "message": "Use Blinkit and add one litre Amul milk.", "input_mode": "TEXT" }
```
**202**
```json
{ "task_id": "UUID", "accepted": true, "state": "PLANNING", "message": "Clarification received. Updating the plan." }
```
Effects:
- The answer is added to session memory and to the plan's `clarification_history`.
- The same task is re-planned. The original command is preserved and no new task is created.
- Telemetry is published as for any planning run.

| HTTP | `code` | When |
| --- | --- | --- |
| 403 | `TASK_SESSION_MISMATCH` | Task belongs to another session |
| 404 | `TASK_NOT_FOUND` | Unknown task |
| 409 | `TASK_NOT_AWAITING_CLARIFICATION` | Task is not `NEEDS_CLARIFICATION` (e.g. planned, completed, failed) |
| 409 | `INVALID_STATE_TRANSITION` | A concurrent clarification already moved the task to `PLANNING` |
| 422 | `VALIDATION_ERROR` | Empty/whitespace message, > 4000 chars, bad UUID |
| 503 | `PLANNER_BUSY` | Planner queue full |

### `GET /agent/status?probe=false`
**200**
```json
{ "agent_name": "Kamlesh Bhai", "provider": "mock", "model": "taskpilot-mock-v1", "status": "available",
  "planning_enabled": true, "browser_execution_enabled": false, "is_mock": true, "provider_reachable": null }
```
- **`status` values:** `available`, `disabled`, `misconfigured` or `unavailable`.
- **`probe=true`:** runs a cheap provider reachability check. This is a model-metadata lookup with no generation or token spend, and it fills in `provider_reachable`.

The response never includes credentials or environment details.

## Phase 3: execution and browser

### `POST /tasks/{task_id}/execute` → 202
Body: `{"session_id": "UUID", "confirm_execution": true}` (`false`/missing → 422). Sent only by **Run Plan**.
```json
{"task_id": "…", "session_id": "…", "status": "ACCEPTED", "message": "Browser execution has been queued."}
```
Errors: `BROWSER_UNAVAILABLE` 503 (+`Retry-After`), `TASK_SESSION_MISMATCH` 403, `PLAN_NOT_FOUND` 404, `PLAN_NOT_READY` 409, `EXECUTION_ALREADY_STARTED` 409, `BROWSER_SESSION_BUSY` 409, `EXECUTION_QUEUE_FULL` 503, `TASK_NOT_FOUND` 404.

### `POST /tasks/{task_id}/stop` → 202
Body: `{"session_id": "UUID", "reason": "optional, ≤200 chars"}` → `{"task_id", "status": "STOPPING" | "CANCELLED", "message"}`. `EXECUTION_NOT_ACTIVE` 409 when nothing runs; 403 for another session.

### `GET /tasks/{task_id}/execution?session_id=UUID`
`ExecutionSummary`: `task_id, session_id, plan_id, status (QUEUED|EXECUTING|WAITING_APPROVAL|COMPLETED|FAILED|CANCELLED), total_steps, results[], started_at, finished_at, message, error_code`. Each result: `step_id, order, action_type, status (PENDING|RUNNING|SUCCEEDED|FAILED|BLOCKED|SKIPPED), started_at, completed_at, duration_ms, message, error_code, extracted_data, retry_count, verified, strategy, confidence`. 409 `EXECUTION_NOT_ACTIVE` if the task never ran.

### `GET /browser/status`
`{"available", "status": "ready|not_started|unavailable", "engine": "chromium", "active_sessions", "max_sessions", "headless", "message"}` — no paths or secrets.

### `GET /browser/sessions/{session_id}`
`{"session_id", "status", "current_url" (no query/fragment), "current_title", "active_task_id", "created_at", "last_activity_at", "stream_status", "stream_subscribers", "has_screenshot", "auth_required", "headless"}`; 404 `BROWSER_SESSION_NOT_FOUND`.

### `POST /browser/sessions/{session_id}/close`
Body `{"session_id": "UUID"}` (must equal the path) → `{"session_id", "closed": true, "message"}`. Stops a running execution first.

### `GET /browser/sessions/{session_id}/screenshot`
Latest real frame, `image/jpeg`, `Cache-Control: no-store`, headers `X-Frame-Id`, `X-Frame-Sequence`, `X-Captured-At`; 404 `SCREENSHOT_NOT_AVAILABLE`.

### WebSocket `/browser/sessions/{session_id}/stream`
Binary frame stream — see [BROWSER_STREAM_PROTOCOL.md](BROWSER_STREAM_PROTOCOL.md).

### Changes
- `TaskState` adds `CANCELLED` (terminal).
- `GET /agent/status`: `browser_execution_enabled` is true only when execution is enabled **and** Chromium is installed.

### Development-only: fixture shop
`GET /dev/fixtures/shop/{file}` serves the local demo shop (whitelisted files) when `BROWSER_DEV_FIXTURES_ENABLED=true` (dev/test only); 404 otherwise.

## Phase 4: commerce
All responses are observations from the session's browser (fixture or real site). None of these endpoints places an order.

| Method & path | Body | Returns |
| --- | --- | --- |
| `GET /tasks/{task_id}/commerce/summary?session_id=` | — | `ShoppingSummary` (requirements with observed candidates and deterministic matches, pending choice, cart, verification, checkout, order, price changes) |
| `POST /tasks/{task_id}/commerce/selection` | `{session_id, selection_id, candidate_id \| null}` | 202 `{accepted}`; null skips the product |
| `GET /browser/sessions/{session_id}/commerce/cart` | — | last observed `CartSnapshot`; 404 if no browser or no cart was read |
| `POST /browser/sessions/{session_id}/commerce/cart/refresh` | `{session_id}` (must match the URL) | re-read `CartSnapshot` |
| `POST /browser/sessions/{session_id}/commerce/cart/items/{item_id}/quantity` | `{session_id, quantity}` | verified `CartSnapshot` (only that item changes; checkout reviews become stale) |
| `POST /tasks/{task_id}/commerce/checkout/review` | `{session_id}` | live `CheckoutSummary` (needs a VERIFIED cart) |
| `GET /tasks/{task_id}/commerce/checkout?session_id=` | — | latest `CheckoutSummary` |
| `GET /tasks/{task_id}/commerce/order-status?session_id=` | — | `OrderState` (`NOT_STARTED`, `REVIEW_REQUIRED`, `APPROVAL_PENDING`, `REJECTED`, `PAYMENT_HANDOFF`, `SUBMISSION_PENDING`, `CONFIRMED`, `UNKNOWN`, `FAILED`) |

Purchase decisions reuse `POST /approvals/{approval_id}/decision`. `ApprovalRequest` gains an optional `purchase` object: `platform, checkout_id, cart_id, summary_hash, summary_version, items[], subtotal, delivery_fee, handling_fee, tax, discount, final_total, currency, masked_delivery_address, delivery_slot, payment_method, places_real_order, warnings`. Money is serialised as decimal strings.

Endpoints needing an idle browser return `409 BROWSER_SESSION_BUSY` while a plan runs. Error codes: `COMMERCE_PLATFORM_UNSUPPORTED`, `COMMERCE_SESSION_REQUIRED`, `COMMERCE_LOCATION_REQUIRED`, `COMMERCE_PRODUCT_NOT_FOUND`, `COMMERCE_PRODUCT_AMBIGUOUS`, `COMMERCE_VARIANT_MISMATCH`, `COMMERCE_QUANTITY_MISMATCH`, `COMMERCE_CART_UNVERIFIED`, `COMMERCE_PRICE_CHANGED`, `COMMERCE_CHECKOUT_UNVERIFIED`, `COMMERCE_SUMMARY_NOT_FOUND`, `COMMERCE_SELECTION_NOT_PENDING`, `PURCHASE_APPROVAL_REQUIRED`, `PURCHASE_APPROVAL_EXPIRED`, `PURCHASE_APPROVAL_STALE`, `PURCHASE_POLICY_BLOCKED`, `PURCHASE_REJECTED`, `PAYMENT_USER_HANDOFF_REQUIRED`, `ORDER_SUBMISSION_UNKNOWN`, `CAPTCHA_REQUIRED`, `TASK_SESSION_MISMATCH`, `BROWSER_SESSION_NOT_FOUND`, `BROWSER_SESSION_BUSY`.

Plans: `SupportedAction` adds `{"type": "commerce", operation, platform, site_key, requirement?, payment_preference?, continue_on_failure}`. These are built only by the deterministic commerce planner. `IntentType` adds `ECOMMERCE_CART_REVIEW`, `ECOMMERCE_CHECKOUT_REVIEW` and `ECOMMERCE_PURCHASE`.

Dev only: `GET /dev/fixtures/commerce/{blinkit|amazon}/{file}` serves the local fixture shops when `COMMERCE_ENABLE_FIXTURES=true` (development/test only).

## Phase 5: integrations

All task endpoints take `session_id` and return 403 `TASK_SESSION_MISMATCH` for another session. Errors use the
standard format; integration errors carry codes such as `WORKFLOW_NOT_FOUND`, `CHOICE_NOT_PENDING`,
`DRAFT_NOT_EDITABLE`, `FILE_NOT_FOUND`, `FILE_ACCESS_DENIED`, `CONFIRMATION_REQUIRED`, `CAPABILITY_DISABLED` (503).

| Method & path | Purpose |
| --- | --- |
| `GET /integrations/capabilities` | Trusted capability list (`CapabilityDefinition[]`). |
| `GET /integrations/status?session_id=` | Per-domain status: `NOT_CONFIGURED` / `AVAILABLE` / `AUTHENTICATION_REQUIRED` / `CONNECTED` / `BLOCKED` / `ERROR`. |
| `GET /tasks/{id}/workflow?session_id=` | `WorkflowState` (planned view before Run Plan; observed afterwards). 404 if the plan has no integration steps. |
| `POST /tasks/{id}/workflow/choice` | `{session_id, choice_id, option_id\|null}` — answer a pending video/file choice (null = skip). 202. |
| `GET /tasks/{id}/youtube/results?session_id=` | `{results, selected, playback, pending_choice}` (observed). |
| `GET /tasks/{id}/gmail/draft?session_id=` | `{draft: EmailDraftSummary, body, editable, recipients?}` — `draft.sent` is always `false`. |
| `PUT /tasks/{id}/gmail/draft` | `{session_id, subject, body}` — edit the planned draft; only while the task is `PLANNED` (else 409 `DRAFT_NOT_EDITABLE`). |
| `GET /tasks/{id}/calendar/review?session_id=` | `CalendarEventReview` (labels, conflicts, `event_hash`, status). |
| `GET /tasks/{id}/calendar/status?session_id=` | `{status, message, verified_reference, approval_id, event_hash}`. |
| `GET /files?session_id=` | `DownloadedFile[]` of this session (no paths). |
| `GET /files/{id}?session_id=` | Metadata (name, type, size, SHA-256, source domain, expiry). |
| `GET /files/{id}/download?session_id=` | The file as an attachment (`nosniff`, `CSP: sandbox`, `no-store`). |
| `DELETE /files/{id}` | `{session_id, confirm: true}` — permanent delete; 400 `CONFIRMATION_REQUIRED` without `confirm`. |

Calendar events are created only inside a run after `POST /approvals/{id}/decision` approves the
`ApprovalRequest` whose `calendar` field describes the exact event. No endpoint sends email.

Development-only (with `INTEGRATION_ENABLE_FIXTURES=true`): `GET /dev/fixtures/integrations/{youtube|gmail|calendar|files}/{name}`
and `GET /dev/fixtures/integrations/files/redirect/{inside|outside}`.

## Development-only endpoints
These are available only when `ENABLE_DEMO_ENDPOINTS=true` **and** `APP_ENV` is `development` or `test`. Otherwise they return **404**. They run fixed scenarios: clients cannot choose event types or payloads, and every emitted event has `is_demo: true`.

### `POST /dev/demo/telemetry`
Request: `{ "session_id": "UUID" }`

**202**
```json
{ "accepted": true, "message": "Demo telemetry started. No real actions will be performed.", "task_id": "UUID", "is_demo": true }
```
Streams these events, in order:
1. Demo `task.accepted`.
2. Logs at DEBUG, INFO, WARNING and SUCCESS.
3. State changes `IDLE→PLANNING→EXECUTING→COMPLETED`.
4. `browser.preview` with `mode: "PLACEHOLDER"`, then `mode: "DISCONNECTED"`.

### `POST /dev/demo/approval`
Request: `{ "session_id": "UUID" }`

**201** returns the created `ApprovalRequest` (`is_demo: true`, `risk_level: "HIGH"`, TTL `DEMO_APPROVAL_TTL_SECONDS`, default 120 s).

The demo task moves to `WAITING_APPROVAL` first. After the decision:
- **APPROVE:** `EXECUTING → COMPLETED`.
- **REJECT or expiry:** `EXECUTING → FAILED` with `error_code` `APPROVAL_REJECTED` or `APPROVAL_EXPIRED`.

## Phase 6 additions

**Versioning:** all routes stay under `/api/v1`; breaking changes will use `/api/v2` alongside v1.
**Errors:** unchanged envelope `{code, message, request_id}`; new codes: `AUTHENTICATION_REQUIRED`,
`TOKEN_EXPIRED`, `INVALID_TOKEN`, `INVALID_CREDENTIALS`, `CSRF_FAILED`, `READ_ONLY_ACCOUNT`,
`SESSION_ACCESS_DENIED`, `RESOURCE_ACCESS_DENIED`, `RATE_LIMITED` (429, `Retry-After`), `PAYLOAD_TOO_LARGE`,
`DATABASE_UNAVAILABLE`/`QUEUE_FULL`/`QUEUE_UNAVAILABLE` (503), `ACTION_STATE_UNKNOWN`, `EXECUTION_INTERRUPTED`,
`PURCHASE_APPROVAL_REUSED`, `FILE_QUOTA_EXCEEDED`, `LLM_BUDGET_EXCEEDED`.

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | `{email, password}` → user (first user OWNER) |
| POST | `/auth/login` | sets `tp_access`, `tp_refresh`, `tp_csrf`; returns `{user, access_expires_in, csrf_token}` |
| POST | `/auth/refresh` | rotates refresh; replay revokes family |
| POST | `/auth/logout`, `/auth/logout-all` | 204 |
| GET | `/auth/me`, `/auth/config` | current user; whether auth is required |
| GET | `/task-history?session_id=&cursor=&limit=` | persistent history, keyset pagination `{tasks, next_cursor}` |
| GET | `/audit`, `/audit/verify`, `/audit/export` | own events; OWNER: all, chain verification, NDJSON |
| GET | `/health/live`, `/health/ready`, `/health/details`, `/metrics` | see [OBSERVABILITY.md](OBSERVABILITY.md) |

Mutating cookie-authenticated requests must send `X-CSRF-Token`. Approval `status` adds `WITHDRAWN`.

## Conversation, voice, activity and settings additions

| Method | Path | Notes |
|---|---|---|
| GET / PUT | `/preferences` | Settings: `display_name`, `language` (auto/en/hinglish/hi), `voice_input_enabled`, `voice_output_enabled`, `voice_auto_submit`, `voice_auto_execute`, `voice_continuous`, `speech_rate` (0.5–1.5), `preferred_store` (none/blinkit/amazon). PUT is a partial update. Stored in `user_preferences` (per user; one `local` profile when sign-in is off). |
| GET | `/activity/events?kind=&status=&q=&task_id=&before=&limit=` | Persisted timeline: tasks, browser steps (execution journal) and audit events, owner-scoped. `next_before` pages backwards. |
| GET | `/activity/tasks/{task_id}` | One task: command, plan summary, planner, each step with lifecycle/message/duration, related events, conversation. |

`POST /tasks/{id}/execute` accepts `trigger`: `run_plan_click` (default) or `voice_auto`. `voice_auto` is refused with
409 `AUTO_RUN_NOT_ALLOWED` when voice auto-run is off in Settings or the plan has any HIGH/CRITICAL or approval-gated step.

`GET /agent/status` adds `planner_kind` (`ai` | `offline_rules`) and `setup_hint` (what to configure when no AI planner is active).
