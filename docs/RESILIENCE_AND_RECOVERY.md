# Resilience and Recovery (Phase 6)

Guiding rule: **after any failure, TaskPilot may re-check, re-plan or ask — it never silently repeats an action
that changes something in the outside world.**

## Execution journal and idempotency

Every executed step is recorded in `action_journal` with an idempotency key
`{task_id}:{plan_id}:{step_id}:v{action_version}` (unique) and moves through:

```
PENDING → PREPARED → RUNNING → SUCCEEDED | FAILED | BLOCKED | CANCELLED | UNKNOWN
```

* A step already **SUCCEEDED** (duplicate queue delivery, retry after a crash) is skipped with
  "Already completed by an earlier attempt — not repeated."
* A **mutating** step found in RUNNING (we cannot know whether the click landed) becomes **UNKNOWN** and the
  run stops with `ACTION_STATE_UNKNOWN`, asking the user to check the website.
* Exception — *reconcilable* steps whose effect can be observed safely: `gmail_create_draft`,
  `calendar_create_event`, `commerce:search_and_add`. These run with `ctx.reconciling = True`; the handler first
  inspects the site (draft exists? event exists? item already in cart?) and only acts if the effect is absent.
* A timeout or cancellation during a mutating step is recorded as UNKNOWN, never as FAILED-and-retryable.
* **Purchases:** the COD "Place order" click additionally consumes the one-time approval in the DB
  (`approvals.used_at`, optimistic `version`). A second attempt fails with `PURCHASE_APPROVAL_REUSED`.

## Queue (Redis)

`RedisJobQueue` (`app/queue/redis_queue.py`): bounded depth (Lua check → `QueueFullError` → HTTP 503), dedupe
key (one live execution per task), `BRPOPLPUSH` into a per-worker processing list, worker heartbeat, a reaper
that re-queues jobs of dead workers, bounded attempts then dead-letter list. Delivery is **at-least-once**; the
journal makes it effectively-once for side effects. `SessionLocks` (Redis lock with ownership token) serialise
work per browser session.

## Startup recovery (`app/resilience/recovery.py`)

| Persisted state found at startup | Action |
|---|---|
| PLANNED (or PLANNING with a READY plan) | restored as PLANNED — user can press Run Plan |
| NEEDS_CLARIFICATION | restored |
| IDLE / PLANNING without a plan | re-planned once (planning has no side effects) |
| EXECUTING / WAITING_APPROVAL | journal: RUNNING mutating → UNKNOWN, PREPARED → CANCELLED; task FAILED `EXECUTION_INTERRUPTED` with a recovery note |
| PENDING approvals | **WITHDRAWN** (never resumable) |
| Browser sessions | CLOSED (cookies are not persisted in production) |
| `.part` download files | deleted; live files re-registered |

The recovery note tells the user exactly which steps finished and which are uncertain.

## Failure catalogue

| Failure | Behaviour |
|---|---|
| API process crash/restart | startup recovery above |
| Database unavailable | requests 503 `DATABASE_UNAVAILABLE`; readiness fails; best-effort writes counted + alerted |
| Redis unavailable | queue 503 `QUEUE_UNAVAILABLE`; rate limiter degrades to per-process (reported in `/health/details`) |
| LLM provider errors | retry with jitter (bounded), then circuit breaker opens → fast `LLM_UNAVAILABLE` |
| Chromium crash / launch failure | session closed, step FAILED, `taskpilot_browser_launch_failures_total` |
| Selector broken by DOM change | self-correction (bounded); see [SELF_CORRECTION_ENGINE.md](SELF_CORRECTION_ENGINE.md) |
| Worker died mid-job | heartbeat expires → reaper re-queues → journal prevents repeats |
| Network to site lost mid-action | mutating → UNKNOWN; read-only → retried |
| Approval timed out | EXPIRED; run stops |
| User cancels | pending approvals WITHDRAWN; in-flight mutating step → UNKNOWN |
| Download interrupted | `.part` removed; never served |
| Disk quota exceeded | `FILE_QUOTA_EXCEEDED` before download |

## Retries and circuit breakers

`app/resilience/retry.py`: exponential backoff with full jitter, capped attempts; only for idempotent
operations. `app/resilience/circuit_breaker.py`: CLOSED → OPEN after `CIRCUIT_BREAKER_FAILURE_THRESHOLD`
consecutive failures → HALF_OPEN after `CIRCUIT_BREAKER_RECOVERY_SECONDS`.

## Tests

`tests/security/test_execution_recovery.py`, `test_idempotency.py` (scenarios 6 and 8: duplicate delivery
against COD and Gmail fixtures), `tests/resilience/test_queue_redis.py` (real local Redis), `test_chaos.py`,
`test_circuit_breaker.py`, `test_maintenance.py`.
