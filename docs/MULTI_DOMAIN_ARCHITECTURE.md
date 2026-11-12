# Multi-domain architecture (Phase 5)

Phase 5 adds four domains on top of the existing Phase 3 BrowserController and Playwright engine:
**YouTube** (search, choose, play and verify), **Gmail** (drafts only), **Google Calendar** (one event,
after an exact-event approval) and **safe file downloads**. One command may span several of these
domains ("find a Python tutorial on YouTube and email the link to a@b.com").

```
command ─► classifier (LLM or offline mock) ─► IntentClassification (+ entities.workflow for MULTI_DOMAIN_WORKFLOW)
        ─► domain_router.route() ─► ordered WorkflowStepEntity list
        ─► IntegrationPlanner (deterministic, trusted) ─► typed plan steps
        ─► PlanValidator + workflow_validator (capabilities, limits, typed hand-offs, no cycles)
        ─► user clicks Run Plan ─► PlanExecutor ─► IntegrationHandler ─► IntegrationManager
        ─► domain adapter (YouTube / Gmail / Calendar) via BrowserController   or   FileDownloader (httpx)
        ─► WorkflowManager records observed results ─► workflow.* / domain telemetry ─► dashboard
```

## Packages

| Path | Role |
| --- | --- |
| `app/integrations/capability_registry.py` | Trusted capability definitions; enabled only by settings. |
| `app/integrations/domain_router.py` | Classified intent → ordered domain steps (never trusts a model-supplied domain). |
| `app/integrations/registry.py` | Domain → site binding (canonical hosts; exact fixture prefixes in dev/test). |
| `app/integrations/integration_planner.py` | Deterministic planning; asks instead of inventing recipients, dates, durations or links. |
| `app/integrations/integration_manager.py` | Runs the five integration action types; choices, approvals, status observation, REST helpers. |
| `app/integrations/policies.py` | `IntegrationPolicy`: purpose-scoped clicks/fills; single-use calendar authorizations. |
| `app/integrations/youtube/` | `adapter.py` (search, extraction, playback verification), `ranking.py` (relevance, auto-select rule). |
| `app/integrations/gmail/` | `adapter.py` (compose, save, verify in Drafts), `composer.py` (fact-free templates). |
| `app/integrations/calendar/` | `datetime_parser.py`, `event_review.py` (labels, event hash, approval details), `adapter.py`. |
| `app/integrations/files/` | `validator.py`, `storage.py`, `downloader.py`. |
| `app/workflow/` | `dependency_resolver.py`, `result_handoff.py`, `workflow_validator.py`, `workflow_manager.py`. |

## Plan actions

`youtube_search`, `youtube_play`, `gmail_create_draft`, `calendar_create_event`, `file_download`
(`app/schemas/integration.py`). They are built **only** by the integration planner, never parsed from
LLM drafts, and re-checked against the capability registry before each step runs.

| Action | Rule risk | Approval |
| --- | --- | --- |
| `youtube_search`, `youtube_play` | LOW | — |
| `gmail_create_draft` | MEDIUM | — (a draft is reversible and is never sent) |
| `file_download` | MEDIUM | — (allow-list + content validation; executables/archives refused) |
| `calendar_create_event` | HIGH | self-gated exact-event approval (see `GOOGLE_CALENDAR_AUTOMATION.md`) |

## Execution integration

- `ExecutionContext.integrations` holds the `IntegrationManager`; `IntegrationHandler` is registered for
  each integration action type in `default_handlers()`.
- Executor additions: integration step timeouts, new cancel codes (calendar rejection/expiry, sign-in
  required, skipped choices), soft `BLOCKED` for integration steps with `continue_on_failure`, and
  **dependency skipping**: a step that needs a soft-failed step's output is recorded as `SKIPPED` while
  independent steps still run. Phase 4 commerce behaviour is unchanged (no commerce step depends on a
  soft-failing step).
- `ExecutionManager._finalize` calls `IntegrationManager.finalize()` (workflow status, `workflow.*`
  events, releases the workflow concurrency slot) and picks a truthful persona message.

## Status model

`/integrations/status` reports per session: `NOT_CONFIGURED` (disabled), `AVAILABLE` (enabled, not yet
used), `CONNECTED` (a page loaded successfully in this session), `AUTHENTICATION_REQUIRED`
(a sign-in page / gate was observed — the user signs in personally), `BLOCKED` (CAPTCHA / bot check),
`ERROR`. Statuses are always observed, never assumed.

## Fixtures (development/test only)

`INTEGRATION_ENABLE_FIXTURES=true` (refused outside `APP_ENV=development|test`) registers local
YouTube-/Gmail-/Calendar-like pages and download test files under
`/api/v1/dev/fixtures/integrations/{youtube,gmail,calendar,files}/…`, selectable with the aliases
"fixture youtube", "fixture gmail", "fixture calendar" and "fixture files". Every fixture page carries a
"LOCAL TEST FIXTURE" banner and plans add a matching assumption. **All Phase 5 automated and dashboard
testing used these fixtures; nothing was run against the real YouTube, Gmail or Google Calendar.**

## Phase 6 — multi-domain persistence and limits

* Workflow state (`workflows`), integration statuses and downloaded-file metadata are persisted and owned by the
  user. Downloads have per-user quotas (`FILE_STORAGE_QUOTA_MB_PER_USER`, `FILE_MAX_COUNT_PER_USER`), an hourly
  rate limit, DNS-pinned transport, the egress proxy, and a malware-scan interface (ClamAV optional; otherwise
  `SCAN_UNAVAILABLE` is shown).
* Calendar event creation consumes its approval in the DB before Save; Gmail drafts are reconciled on retry and
  sending stays blocked.
