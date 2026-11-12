# Execution engine (Phase 3)

## Flow
```
Run Plan click → POST /tasks/{id}/execute → ExecutionManager.submit (validations) → ExecutionQueue
→ worker: get_or_create_session → session.lock → task EXECUTING → PlanExecutor.run → finalize
```
`202 Accepted` means queued. Progress arrives as telemetry.

## Validation at submit
| Check | Error (HTTP) |
| --- | --- |
| execution enabled and Chromium installed | `BROWSER_UNAVAILABLE` (503, `Retry-After`) |
| task belongs to the session | `TASK_SESSION_MISMATCH` (403) |
| not already queued or run | `EXECUTION_ALREADY_STARTED` (409) |
| plan exists | `PLAN_NOT_FOUND` (404) |
| task `PLANNED`, plan `READY` with steps, not chat, **re-validated** | `PLAN_NOT_READY` (409) |
| no other run in this session's browser | `BROWSER_SESSION_BUSY` (409) |
| queue not full | `EXECUTION_QUEUE_FULL` (503) |

## Queue
`ExecutionQueue` is bounded (`EXECUTION_QUEUE_SIZE` 20) with `EXECUTION_CONCURRENCY` (3) workers. It allows one job per task and per session. A queued job can be withdrawn (it never runs, and the task stays `PLANNED`). A crashing job releases its slot. On shutdown, running jobs are cancelled and finalised and queued jobs are abandoned.

## Executor
- Steps run **sequentially**. A step runs only if every `depends_on` step `SUCCEEDED` (`DEPENDENCY_FAILED` otherwise).
- Each step races the handler against a timeout (`navigation + 2 × action + 10 s`) and the cancel event.
- After each step: `page_updated` (if the page changed), a screenshot is captured and published, and `frame_available` is emitted. A screenshot failure never changes a step's result.
- The first non-successful step stops the run; every later step is reported `SKIPPED` ("Not run"), never as done.

## Final status
| Outcome | Execution | Task state |
| --- | --- | --- |
| every step `SUCCEEDED` | `COMPLETED` | `COMPLETED` |
| `USER_CANCELLED`, `APPROVAL_REJECTED`, `APPROVAL_EXPIRED`, `SENSITIVE_ACTION_BLOCKED`, `AUTHENTICATION_REQUIRED`, `SERVER_SHUTDOWN` | `CANCELLED` | `CANCELLED` |
| anything else (selector, timeout, navigation, crash…) | `FAILED` | `FAILED` |

The completion message notes clicks whose effect was not observed and always states that no payment or order was placed. Kamlesh Bhai then replies (`agent.response_generated`, kind `execution`) in the user's language.

## Approvals during execution
`request_approval` steps:
1. Pre-check the next action against the runtime policy. If it is hard-blocked, the step is `BLOCKED` and no approval is created.
2. Create a **real** approval (`is_demo: false`) through `ApprovalCoordinator`, which allows one pending approval per task.
3. Move the task to `WAITING_APPROVAL` and emit `task.execution_paused` (with `approval_id`).
4. Wait for the decision: **APPROVE** → `EXECUTING` and `task.execution_resumed`; **REJECT** → `APPROVAL_REJECTED`; no answer within `EXECUTION_APPROVAL_TTL_SECONDS` → `APPROVAL_EXPIRED`.
5. If Stop is pressed while waiting, the approval is **withdrawn** (expired), so it can never resume anything later.

A decision only resumes its own task: the coordinator checks the task id.

Approval never unlocks a manual-only action. The runtime policy checks the resolved element again after the approval.

## Stop
`POST /tasks/{id}/stop` (`session_id` must match): a queued run is withdrawn (`CANCELLED`, nothing ran); a running one is signalled and stops after the current browser action (`STOPPING`). Then `task.execution_cancelled` is emitted.

## Results
`GET /tasks/{id}/execution?session_id=` returns the `ExecutionSummary` (status, per-step `ActionResult` with `verified`, `strategy`, `confidence`, `duration_ms`, `extracted_data`, `error_code`). The dashboard uses it to recover after a reload when telemetry history no longer holds the run.

## Telemetry
`task.execution_started`, `task.step_started`, `task.step_completed`, `task.step_failed`, `task.step_blocked`, `task.execution_paused`, `task.execution_resumed`, `task.execution_completed`, `task.execution_failed`, `task.execution_cancelled`, plus `browser.*` events. See [WEBSOCKET_PROTOCOL.md](WEBSOCKET_PROTOCOL.md).

## Phase 4: commerce steps
- `commerce` steps are handled by `CommerceHandler` → `CommerceManager`. Their step timeout covers searches, several cart clicks, a possible product choice and up to two purchase approvals.
- Item steps (`search_and_add` / `search_products`) set `continue_on_failure`: an unavailable or skipped item is reported as FAILED but later independent items still run. The cart verification step then reports `PARTIAL`, and the run ends FAILED (never COMPLETED) if any item failed.
- A product choice or purchase review moves the task to `WAITING_APPROVAL` and emits `task.execution_paused` / `task.execution_resumed`. Stop cancels the wait and withdraws a pending approval.
- Additional cancel codes (the run ends CANCELLED): `PURCHASE_REJECTED`, `PURCHASE_APPROVAL_EXPIRED`, `PURCHASE_APPROVAL_STALE`, `COMMERCE_LOCATION_REQUIRED`, `COMMERCE_SESSION_REQUIRED`, `CAPTCHA_REQUIRED`, `PURCHASE_POLICY_BLOCKED`, `PAYMENT_USER_HANDOFF_REQUIRED`.
- The completion message stays truthful. After an approved COD order it says an order was placed (with the site's reference); after a handoff it says payment is up to the user. Otherwise it says no order was placed.

## Phase 5: integration steps
- Handlers: `IntegrationHandler` for `youtube_search`, `youtube_play`, `gmail_create_draft`, `calendar_create_event`,
  `file_download` → `IntegrationManager.run_step()` (capability re-check, workflow bookkeeping, `workflow.*` events).
- Timeout per integration step: `4 × step timeout + approval TTL + 60 s` (one user choice or one exact-event approval).
- New cancel codes: `CALENDAR_EVENT_REJECTED`, `CALENDAR_APPROVAL_EXPIRED`, `CALENDAR_APPROVAL_STALE`,
  `GMAIL_LOGIN_REQUIRED`, `CALENDAR_LOGIN_REQUIRED`, `YOUTUBE_LOGIN_REQUIRED`, `YOUTUBE_SELECTION_SKIPPED`,
  `FILE_SELECTION_SKIPPED`.
- Partial success: in multi-domain plans a FAILED or BLOCKED integration step with `continue_on_failure` does not stop
  independent steps; steps that need its output are recorded as SKIPPED. The summary message starts with
  "Partial result:" and the run is FAILED (or CANCELLED for a user decision) — never COMPLETED.
- `ExecutionManager._finalize()` calls `IntegrationManager.finalize()` and chooses persona messages such as
  `draft_saved`, `event_created`, `integration_completed` or `workflow_partial`.

## Phase 6 — journal, queue and recovery

* Every step: `PREPARED → RUNNING → SUCCEEDED/FAILED/BLOCKED/CANCELLED/UNKNOWN` in `action_journal`, keyed by
  `{task}:{plan}:{step}:v{version}`.
* With `QUEUE_BACKEND=redis`, Run Plan enqueues a job (`RedisExecutionQueue`); the embedded `QueueWorker`
  reserves it, takes the per-session Redis lock, runs it, acks, or retries/dead-letters. Duplicate delivery is
  safe because of the journal.
* Reconcilable steps (`gmail_create_draft`, `calendar_create_event`, `commerce:search_and_add`) inspect the site
  before acting on a retry.
* Click/type steps may use bounded self-correction when a selector disappears (never on ambiguity).
* Startup recovery marks interrupted runs FAILED with `EXECUTION_INTERRUPTED` and a recovery note.
* Span `browser.step` per step.
