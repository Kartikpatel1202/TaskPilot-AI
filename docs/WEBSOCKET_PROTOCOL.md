# WebSocket telemetry protocol (v1)

## Connection
```
ws://localhost:8000/api/v1/ws/{session_id}
```
- `session_id` must be a UUID. Otherwise the server closes with **1008** (policy violation), and the client does not retry.
- When the server is at `WEBSOCKET_MAX_CONNECTIONS`, it accepts the connection and then closes it with **1013** (try again later). The client retries with backoff.
- Only text frames are accepted, at most 4096 bytes each.

After accepting, the server immediately sends **`connection.ready`**. That event goes only to the new connection and is not stored in history.

## Server → client: telemetry envelope
```json
{
  "event_id": "UUID",
  "session_id": "UUID",
  "task_id": "UUID | null",
  "sequence": 12,
  "type": "log.created",
  "occurred_at": "2026-11-05T10:00:00.123456Z",
  "data": { "level": "INFO", "message": "Task accepted successfully" }
}
```
- `event_id` is globally unique. Clients must deduplicate on it.
- `sequence` increases monotonically **per session**. Clients use it to order events and to ignore stale state changes.
- `task_id` is `null` for events that aren't about a task (for example `connection.ready`).

### Event types and `data` payloads
| `type` | `data` |
| --- | --- |
| `connection.ready` | `connection_id`, `server_version`, `assistant_name` (`"Kamlesh Bhai"`), `heartbeat_interval_seconds`, `history_limit`, `demo_endpoints_enabled` |
| `task.accepted` | `task_id`, `state`, `command`, `input_mode`, `created_at`, `is_demo` |
| `task.state_changed` | `previous_state`, `new_state`, `reason?`, `is_demo` |
| `log.created` | `level` (`DEBUG\|INFO\|WARNING\|ERROR\|SUCCESS`), `message` (≤ 2000), `source` (`system\|assistant\|demo`), `language?` (`en\|hi\|hinglish`), `metadata?` (server-redacted), `is_demo` |
| `browser.preview` | `mode` (`DISCONNECTED\|PLACEHOLDER\|FRAME`), `message`, `url?`, `frame_data_url?` (Phase 3 only; must be `data:image/(png\|jpeg\|webp);base64,…`), `is_demo` |
| `approval.required` | the full `ApprovalRequest`: `approval_id`, `task_id`, `session_id`, `action_summary`, `domain`, `reason`, `risk_level` (`LOW\|MEDIUM\|HIGH\|CRITICAL`), `status`, `estimated_impact?`, `expires_at`, `is_demo`, `created_at`, `resolved_at`, `decision` |
| `approval.resolved` | `approval_id`, `decision` (`APPROVE\|REJECT\|null` when expired), `status` (`APPROVED\|REJECTED\|EXPIRED`), `resolved_at`, `is_demo` |
| `task.completed` | `summary`, `is_demo` |
| `task.failed` | `error_code`, `error_message` (safe for display), `is_demo` |
| `system.error` | `code`, `message` |

The frontend validates every frame with Zod (`src/lib/validators.ts`). Frames that are unknown or malformed are dropped and recorded as client-side protocol-error log entries. They never crash the UI.

### Phase 2 agent events
These use the same envelope, ordering, bounded queues, replay and session isolation as the Phase 1 events. They never carry prompts, hidden reasoning, API keys or token usage.

| `type` | `data` |
| --- | --- |
| `agent.planning_started` | `status` (`"PLANNING"`), `message` (localised), `is_clarification` |
| `agent.planning_progress` | `stage` (`UNDERSTANDING_COMMAND` → `CLASSIFYING_INTENT` → `BUILDING_PLAN` → `VALIDATING_PLAN` → `FINALIZING`), `progress` (0–100, derived from the stage's position), `message` |
| `agent.intent_detected` | `intent`, `confidence`, `target_website`, `language`, `requires_clarification`, `is_follow_up` |
| `task.plan_ready` | `plan_id`, `status` (`READY` or `REJECTED`), `intent`, `summary`, `step_count`, `requires_human_approval`, `provider`, `model`, `is_mock`. The full plan is fetched from `GET /tasks/{id}/plan` |
| `task.clarification_required` | `plan_id`, `question`, `missing_information[]` |
| `task.planning_failed` | `code` (e.g. `LLM_PROVIDER_TIMEOUT`, `LLM_AUTH_FAILED`, `PLAN_VALIDATION_FAILED`, `PLANNING_TIMEOUT`), safe `message`, `retryable` |
| `agent.response_generated` | Kamlesh Bhai's reply: `message`, `language`, `kind` (`plan_ready`, `clarification`, `rejected`, `failed` or `chat`) |

Typical successful sequence:
1. `task.accepted`
2. `log.created` (acknowledgement)
3. `task.state_changed` IDLE→PLANNING
4. `agent.planning_started`
5. Progress ×2
6. `agent.intent_detected`
7. Progress ×2
8. `task.state_changed` PLANNING→PLANNED
9. `task.plan_ready`
10. `agent.response_generated`

On failure, `task.planning_failed` is sent, then `task.state_changed` →FAILED, `task.failed` and `agent.response_generated` (`failed`). A failed run never sends `task.plan_ready`.

### Phase 3 browser and execution events
Payload fields (all URLs are reported without query strings, fragments or credentials):

| Type | `data` |
| --- | --- |
| `browser.session_started` / `browser.session_ready` | `status, engine, headless, message?` |
| `browser.navigation_started` / `browser.navigation_completed` | `url, domain?, title?, step_id?, message` |
| `browser.navigation_blocked` | `url, domain?, reason_code, message, step_id?` |
| `browser.page_updated` | `url, domain, title` |
| `browser.frame_available` | `frame_id, sequence, width, height, bytes, captured_at` (the frame itself is on the stream socket) |
| `browser.action_started` / `_completed` / `_failed` | `step_id, action_type, message, strategy?, confidence?, error_code?` |
| `browser.authentication_required` | `domain, message, headless, step_id?` |
| `browser.popup_blocked` | `url, message` |
| `browser.download_blocked` | `filename, message` (never the download URL) |
| `browser.session_closed` | `reason` |
| `browser.session_error` | `code, message` |
| `browser.stream_connected` / `browser.stream_disconnected` | `subscribers` |
| `task.execution_started` | `plan_id, total_steps, engine, headless` |
| `task.step_started` | `step_id, order, action_type, description` |
| `task.step_completed` | `step_id, order, status, duration_ms, message, verified, extracted_data?` |
| `task.step_failed` / `task.step_blocked` | `step_id, order, status, error_code, message, duration_ms?` |
| `task.execution_paused` | `step_id, reason, approval_id?` |
| `task.execution_resumed` | `step_id, message` |
| `task.execution_completed` / `_failed` / `_cancelled` | `status, total_steps, succeeded_steps, failed_steps, blocked_steps, skipped_steps, message, error_code?` |

`agent.response_generated.kind` adds `"execution"`. Task states include `CANCELLED`. The default replay buffer is 500 events per session. Screenshot frames travel on a separate binary socket: [BROWSER_STREAM_PROTOCOL.md](BROWSER_STREAM_PROTOCOL.md).

### Phase 4 commerce events
`commerce.session_detected`, `commerce.location_required`, `commerce.search_started`, `commerce.search_completed`, `commerce.products_found` (`candidate_count`, `exact_match_count`), `commerce.product_selected`, `commerce.product_ambiguous` (`selection_id`), `commerce.product_unavailable`, `commerce.cart_update_started`, `commerce.cart_item_added`, `commerce.cart_item_updated` (`before_quantity`, `after_quantity`), `commerce.cart_verification_started`, `commerce.cart_verification_completed` / `_failed` (`status`, `requested_item_count`, `matched_item_count`, `missing_items`, `mismatched_items`, `warnings`), `commerce.price_changed` (`previous`, `current`, `difference`, `approval_invalidated`), `commerce.checkout_review_ready` (`final_total`, `payment_method`, `is_verified`, `item_count`), `commerce.purchase_approval_required`, `commerce.purchase_rejected`, `commerce.payment_handoff` (`status: USER_ACTION_REQUIRED`), `commerce.order_submission_started`, `commerce.order_confirmed` (`order_reference` only if the site showed one), `commerce.order_status_unknown`, `commerce.workflow_failed` (`code`).

Every payload carries `platform` and a `message`; money is a decimal string. They never contain a full delivery address, credentials, OTPs, cookies or card details. The dashboard validates them with one bounded Zod schema and re-fetches `GET /tasks/{id}/commerce/summary` after each one. A product choice and the final purchase review also emit the existing `task.execution_paused` / `task.execution_resumed`, and the purchase review arrives as `approval.required` with the `purchase` object.

## Server → client: control frames
| Frame | Meaning |
| --- | --- |
| `{"type":"pong"}` | Reply to `ping` |
| `{"type":"subscribed","replayed":N,"complete":true}` | Sent after replaying N events. `complete:false` means the requested anchor had been evicted, so all retained events were sent instead |
| `{"type":"error","code":"INVALID_MESSAGE"\|"MESSAGE_TOO_LARGE"\|"UNSUPPORTED_FRAME","message":"…"}` | The client message was rejected. The connection stays open |

## Client → server messages
```json
{ "type": "subscribe", "after_event_id": null }
{ "type": "ping" }
```
- **`subscribe`:** asks the server to replay history. With `after_event_id: null` the server replays all retained history for the session. With an id, it replays only the events after that one. The client sends it after every (re)connect, passing the id of the highest-sequence event it has processed.
- **`ping`:** the client sends it every 25 s. If no `pong` arrives within 10 s, the client closes the socket (code 4000) and reconnects.

Any other message receives an `error` frame. Unknown types are never executed.

## Reconnection (client)
`useWebSocket` reconnects with exponential backoff of **1 s, 2 s, 4 s, 8 s, 16 s**, plus 0–400 ms of random jitter. After 5 consecutive failures the status becomes `ERROR`. The user can then press **Retry**, or the client reconnects automatically on the browser's `online` event. While the status is not `CONNECTED`, command submission is disabled and the UI says why.

Connection states: `CONNECTING | CONNECTED | RECONNECTING | DISCONNECTED | ERROR`.

## Event replay
- The server keeps a bounded deque of the last `TELEMETRY_HISTORY_LIMIT` (default 100) events per session, and tracks a bounded number of sessions (LRU).
- Because the session id survives page reloads (`sessionStorage`), a reload or reconnect replays missed events. Overlaps are harmless because the client deduplicates by `event_id`.
- History lives in memory only and is lost when the server restarts.

## Session isolation
- `publish(session_id, event)` refuses events whose envelope `session_id` differs from the target.
- Events go only to the sockets registered under that session.
- A session's replay contains only that session's history.
- Multiple tabs that share one session id all receive its events. Different sessions never see each other's data.

## Backpressure and cleanup
- Each connection has a bounded outgoing queue (`WEBSOCKET_SEND_QUEUE_SIZE`, default 256) drained by a single sender coroutine, so sends to a socket never overlap.
- If a consumer's queue fills, the server disconnects it with 1013 rather than buffering without limit. The client reconnects and replays.
- If a send fails because the client vanished, the server marks the connection closed. It is removed in the handler's `finally` block.
- On shutdown, the server closes every connection with 1001.

## Phase 5: integration events

Every integration event uses one bounded payload, validated by the client
(`integrationEventDataSchema`): `{domain?, message, status?, step_id?, capability?, code?, result_count?,
choice_id?, approval_id?, file_id?, bytes_received?, completed_steps?, total_steps?}`. Payloads never contain
email bodies, full addresses, private event details, cookies or file paths.

| Group | Events |
| --- | --- |
| integration | `integration.domain_selected`, `integration.capability_selected`, `integration.authentication_required`, `integration.session_ready`, `integration.error` |
| youtube | `youtube.search_started`, `youtube.search_completed`, `youtube.results_found`, `youtube.video_selected`, `youtube.playback_started`, `youtube.playback_paused`, `youtube.playback_error` |
| gmail | `gmail.draft_started`, `gmail.draft_composed`, `gmail.draft_saved`, `gmail.draft_verified`, `gmail.draft_failed`, `gmail.send_blocked` |
| calendar | `calendar.event_prepared`, `calendar.conflict_detected`, `calendar.approval_required`, `calendar.approval_resolved`, `calendar.event_creation_started`, `calendar.event_created`, `calendar.event_creation_failed` |
| file | `file.download_started`, `file.download_progress`, `file.download_completed`, `file.download_blocked`, `file.download_failed`, `file.validation_completed` |
| workflow | `workflow.step_started`, `workflow.step_completed`, `workflow.step_failed`, `workflow.partial_success`, `workflow.completed` |

The calendar approval itself travels as the existing `approval.required` event with
`data.calendar` (`CalendarApprovalDetails`). The dashboard bumps an integration revision on each event and
re-fetches the REST views (workflow, YouTube results, draft, calendar review, files).

## Phase 6 — WebSocket security

* When auth is enforced the handshake requires the `tp_access` cookie; the `Origin` header must be in
  `CORS_ORIGINS`; the `session_id` must belong to the user (first use claims it). Failures close with policy
  violation codes before any event is sent.
* Per-user connection cap `MAX_WEBSOCKET_CONNECTIONS_PER_USER` (plus the global `WEBSOCKET_MAX_CONNECTIONS`).
* The same rules apply to the browser screenshot stream `/api/v1/browser/sessions/{id}/stream`.
* Events are unchanged; approval events may now carry status `WITHDRAWN` (cancelled run or server restart).
* Telemetry fan-out is in-process, so production runs a single api replica.
