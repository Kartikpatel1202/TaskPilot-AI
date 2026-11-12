# Architecture (Phases 1–4)

> Phase 2 adds Kamlesh Bhai's planning engine on top of this foundation. Its pipeline, modules and lifecycle are described in [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md). `POST /tasks` now queues a background planning job after creating the task (step 3 below), and planning progress streams over the same WebSocket.

## 1. Overview
TaskPilot AI has two independently runnable applications:

- **Frontend:** a Next.js 14 App Router dashboard (`frontend/`). It is a client-rendered app shell plus one route (`/`).
- **Backend:** a FastAPI service (`backend/`). It exposes a REST API under `/api/v1` and a WebSocket telemetry channel at `/api/v1/ws/{session_id}`.

Commands travel **frontend → backend over REST**. Everything the backend wants the UI to know (acceptance, state changes, logs, browser preview, approvals) travels **backend → frontend over the WebSocket** as typed telemetry events. The frontend never infers backend state on its own. The one exception is the optimistic `TASK_ACCEPTED` it records from the REST response, which the matching event then reconciles.

## 2. Backend layering
```
api/        thin routers: validate input (Pydantic), call a service, shape the response
services/   business logic: TaskService, ApprovalService, interfaces (Phase 2/3 Protocols)
core/       state_machine, event_manager (event generation), logging, persona
websocket/  WebSocketManager: transport only (connections, queues, history, replay)
dev/        DemoSimulator + dev-only routes (404 outside development/test)
schemas/    Pydantic contracts mirroring frontend/src/types/*
container.py  wires everything; one Container per app instance (tests build their own)
```
The main rules:
- **Schemas carry no business logic.**
- **Event generation is separate from transport.** `EventManager` assigns `event_id`, the per-session `sequence` and `occurred_at`, then hands the event to an `EventPublisher` protocol. `WebSocketManager` implements that protocol.
- **Routes hold no business logic.** Domain exceptions (`TaskNotFoundError`, `ApprovalExpiredError`, …) map to `APIError` bodies in `main.py`. Unhandled errors return a generic 500 with no stack traces.

### Configuration
`app/config.py` uses `pydantic-settings`. `.env` is resolved relative to `backend/`, so the working directory doesn't matter. CORS origins are parsed from a comma-separated string, and `*` is dropped because credentials are allowed.

### Logging
`core/logging.py` writes JSON lines to stdout. It redacts keys that look like secrets (`password`, `token`, `authorization`, `cookie`, `card`, `otp`, …). The same `redact()` runs on any `metadata` attached to `log.created` telemetry before it leaves the server. The frontend redacts again before rendering.

## 3. REST request flow (create task)
```
CommandCenter ──submitCommand()──▶ lib/api.createTask (10 s timeout, Zod-validated response)
   POST /api/v1/tasks {command, session_id, input_mode}
      → CreateTaskRequest (strip, reject empty/whitespace, ≤ MAX_COMMAND_LENGTH, UUID session)
      → TaskService.create_task  → in-memory Task (state IDLE, UTC timestamps, bounded LRU)
                                 → emit task.accepted
                                 → emit log.created (Kamlesh Bhai reply in the user's language)
   ◀── 202 TaskAcceptedResponse
UI: "Command accepted — not executing." Task stays IDLE (no planner in Phase 1).
```

## 4. WebSocket event flow
```
EventManager.emit ─▶ WebSocketManager.publish(session_id, event)
   ├─ dedupe by event_id, append to bounded per-session history (deque, maxlen = TELEMETRY_HISTORY_LIMIT)
   └─ put_nowait() into each connection's bounded queue for that session only
        └─ one sender coroutine per connection drains the queue → websocket.send_text
           (never concurrent sends; a full queue = slow consumer → disconnect with 1013)

Browser: useWebSocket ─ onmessage → parseServerMessage (Zod) ─ invalid → client ERROR log, ignored
                                    └ valid → EventDeduplicator → mapEventToActions → reducer → UI
```
`connection.ready` is sent only to the new connection and is not stored in history.

## 5. Frontend state management
- `TaskPilotProvider` owns a single `useReducer` (`context/taskPilotReducer.ts`, which is pure and unit-tested). It exposes three contexts: **state**, **actions** (stable callbacks) and **UI flags**. Components that only dispatch therefore don't re-render on every log.
- No UI component touches the WebSocket. The pipeline is `useWebSocket → validation → dedupe → mapEventToActions → reducer → components`.
- Ordering: the reducer keeps the last applied `sequence` per task and ignores stale `task.state_changed` events. Logs are inserted in sequence order and capped at `MAX_LOGS` (500).
- `ExecutionLogs` memoises entries (`React.memo`), filters per level, auto-scrolls only while the user is at the bottom, and offers "Jump to latest".

## 6. Session management
- On first load each browser tab creates a UUID v4 (`crypto.randomUUID`) and stores it in `sessionStorage`. A reload keeps the session, so the server can replay telemetry. A new tab gets a new session.
- The backend validates the UUID (an invalid one closes with 1008). Sessions are isolated: events go only to sockets of the same `session_id`, and `publish()` refuses events whose envelope session differs.
- Several tabs or sockets can share one session (they all receive its events). The total number of sockets is capped by `WEBSOCKET_MAX_CONNECTIONS` (close code 1013 beyond that).
- Per-session history and sequence counters are bounded (LRU over `max_tracked_sessions`). The history of a live session is never evicted.

## 7. Approval workflow
```
(Phase 1: dev only) POST /dev/demo/approval
  → demo task IDLE→PLANNING→EXECUTING→WAITING_APPROVAL (each emits task.state_changed)
  → ApprovalService.create → approval.required (full ApprovalRequest, is_demo=true)
UI: ApprovalDialog opens (DEMO APPROVAL — NO REAL ACTION banner), countdown to expires_at
User clicks Approve/Reject  → POST /approvals/{id}/decision
  ApprovalService.decide: only PENDING; expired → EXPIRED (410); decided → 409 (immutable)
  → approval.resolved → resolution handlers (DemoSimulator continues the *simulated* task)
```
Safety properties:
- Initial focus goes to the dialog container, so Enter cannot approve by itself.
- A synchronous in-flight guard plus disabled buttons prevents duplicate submissions.
- Closing the dialog leaves the request pending, and a "Review" button reopens it.
- A background sweeper expires overdue approvals every 5 seconds and publishes `approval.resolved` with status `EXPIRED`.
- Phase 1 never executes anything on approval, and payment data is never collected or stored.

## 8. Task state machine
`core/state_machine.py` defines `ALLOWED_TRANSITIONS` (updated in Phase 2):
```
IDLE → PLANNING → {PLANNED, NEEDS_CLARIFICATION}
NEEDS_CLARIFICATION → PLANNING
PLANNED → EXECUTING                      (only via POST /tasks/{id}/execute — Run Plan; the planner never does this)
EXECUTING → {WAITING_APPROVAL, COMPLETED, CANCELLED};  WAITING_APPROVAL → {EXECUTING, CANCELLED}
any active state → FAILED
PLANNING → EXECUTING                     (kept only for the labelled Phase 1 demo simulation)
```
`COMPLETED`, `FAILED` and `CANCELLED` are terminal (`CANCELLED`: stopped by you, approval rejected/expired, a manual-only action refused, or sign-in required). `TaskService.transition()` validates every change, raises `InvalidTransitionError` (HTTP 409 if it ever reaches the API), and emits `task.state_changed`. Entering `COMPLETED` also emits `task.completed`, and entering `FAILED` also emits `task.failed`.

## 9. Extension points for later phases
| Phase | Hook | Where |
| --- | --- | --- |
| 2 – Planner | ✅ Implemented: `AgentOrchestrator`, `PlanningService` and the bounded `PlannerQueue`. See [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) | `agent/*`, `services/planning_service.py`, `core/planner_queue.py` |
| 3 – Execution | ✅ Implemented: `ExecutionManager`, `ExecutionQueue`, `PlanExecutor`, action handlers, approval coordinator. See [EXECUTION_ENGINE.md](EXECUTION_ENGINE.md) | `execution/*`, `browser/executor.py`, `browser/actions/*` |
| 3 – Browser | ✅ Implemented: Playwright `BrowserManager`/`BrowserController`, guards, runtime policy, binary frame stream (not `browser.preview`, which stays the Phase 1 demo channel). See [BROWSER_ARCHITECTURE.md](BROWSER_ARCHITECTURE.md) | `browser/*`, `policies/*`, `api/browser.py` |
| 4 – Monitoring | `system.error`, `task.failed` with `error_code`; bounded replay | `schemas/telemetry.py` |
| 5 – Workflows | `ApprovalService.create()` for real (non-demo) approvals; resolution handlers | `services/approval_service.py` |
| 6 – Persistence/Auth | Swap the in-memory dicts in the services for a repository; add auth middleware | `services/*`, `main.py` |

## 10. Phase 3: browser execution (summary)
```
Run Plan ─▶ POST /tasks/{id}/execute ─▶ ExecutionManager (re-validate) ─▶ ExecutionQueue
          ─▶ PlanExecutor ─▶ handlers ─▶ BrowserController ─▶ Playwright/Chromium
                 │                                   ▲
                 ├─ telemetry: task.execution_* / task.step_* / browser.*  (JSON WebSocket)
                 └─ frames: /browser/sessions/{id}/stream                  (binary WebSocket)
```
Every request of a browser context passes the `NavigationGuard`; every click/type passes the runtime `BrowserActionPolicy`. Details: [BROWSER_ARCHITECTURE.md](BROWSER_ARCHITECTURE.md), [PLAYWRIGHT_CONTROLLER.md](PLAYWRIGHT_CONTROLLER.md), [BROWSER_SECURITY.md](BROWSER_SECURITY.md), [BROWSER_SESSION_MANAGEMENT.md](BROWSER_SESSION_MANAGEMENT.md), [EXECUTION_ENGINE.md](EXECUTION_ENGINE.md), [BROWSER_STREAM_PROTOCOL.md](BROWSER_STREAM_PROTOCOL.md).

## 11. Phase 4: commerce (summary)
Shopping intents on a domain-validated platform (blinkit.com, amazon.in; or the dev fixtures) are planned by the deterministic `CommercePlanner` into `commerce` steps. They run through the same queue and executor, via `CommerceHandler` → `CommerceManager` → platform adapter → `BrowserController`. Purchases are only possible through the self-gated `place_order` step: an exact-order approval (existing ApprovalService, `purchase` details), a reload and re-check, the `PurchasePolicy` authorisation, and one COD click. Prepaid payments are handed to the user. Details: [COMMERCE_ARCHITECTURE.md](COMMERCE_ARCHITECTURE.md), [PRODUCT_MATCHING.md](PRODUCT_MATCHING.md), [CART_VERIFICATION.md](CART_VERIFICATION.md), [CHECKOUT_AND_PURCHASE_SAFETY.md](CHECKOUT_AND_PURCHASE_SAFETY.md), [BLINKIT_ADAPTER.md](BLINKIT_ADAPTER.md), [AMAZON_ADAPTER.md](AMAZON_ADAPTER.md).

## 12. Phase 5: multi-domain integrations (summary)
- `app/integrations/` adds a trusted **capability registry**, a **domain router** and an **integration planner**
  that turns classified requests into typed `youtube_search`, `youtube_play`, `gmail_create_draft`,
  `calendar_create_event` and `file_download` steps; `app/workflow/` adds dependency resolution, typed result
  hand-off, workflow validation and `WorkflowState`.
- Steps run through the unchanged Phase 3 executor via `IntegrationHandler` → `IntegrationManager` → adapters
  that act only through `BrowserController` (plus an `httpx` downloader for files).
- Gmail never sends; calendar creation is self-gated by an exact-event approval (`ApprovalRequest.calendar`);
  downloads are allow-listed and validated. See [MULTI_DOMAIN_ARCHITECTURE.md](MULTI_DOMAIN_ARCHITECTURE.md).

## Phase 6 — production hardening

* **Persistence:** SQLAlchemy 2 async + Alembic; PostgreSQL in production, SQLite in dev/test. The DB is
  authoritative; in-memory services are write-through caches. See [DATABASE_DESIGN.md](DATABASE_DESIGN.md).
* **Identity:** local accounts (Argon2id), JWT access + rotating refresh cookies, CSRF, roles, and a central
  middleware that checks ownership of every session/task/approval/file id. See
  [AUTHENTICATION_AND_AUTHORIZATION.md](AUTHENTICATION_AND_AUTHORIZATION.md).
* **Resilience:** execution journal (idempotency), Redis job queue with heartbeat/reaper/dead-letter, startup
  recovery, circuit breakers, bounded retries. See [RESILIENCE_AND_RECOVERY.md](RESILIENCE_AND_RECOVERY.md).
* **Self-correction:** bounded, verifiable selector recovery. See [SELF_CORRECTION_ENGINE.md](SELF_CORRECTION_ENGINE.md).
* **Network:** SSRF checks + DNS pinning + egress proxy. See [NETWORK_SECURITY.md](NETWORK_SECURITY.md).
* **Operations:** metrics, health, audit chain, deployment, DR. See [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md),
  [OBSERVABILITY.md](OBSERVABILITY.md), [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md),
  [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md), [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

New backend packages: `app/database`, `app/auth`, `app/queue`, `app/resilience`, `app/observability`,
`app/agent/self_correction`; new browser modules `selector_memory`, `mutation_monitor`, `recovery_engine`.
