# Browser architecture (Phase 3)

Phase 3 turns a validated plan into real actions in **Chromium via Playwright (Python, async)**, but only after the user clicks **Run Plan**. Planning never starts a browser.

```
Dashboard ── POST /tasks/{id}/execute (confirm_execution: true) ──▶ ExecutionManager
                                                                       │ validate + queue
                                                                       ▼
                                                            ExecutionQueue (bounded)
                                                                       │ one job per task / per session
                                                                       ▼
 BrowserManager ◀── get_or_create_session ── PlanExecutor ── per step ─▶ action handler
 (Playwright, 1 browser,                          │                     navigate/click/type/
  1 context per session)                          │                     extract/approval/stop
        │                                         │                          │
        │ context.route("**/*")                   │                          ▼
        ▼                                         │                 BrowserController
 NavigationGuard + download guard                 │        (DOMInspector, SelectorResolver,
                                                  │         BrowserActionPolicy, screenshots)
                                                  ▼
                                  telemetry (WebSocket JSON) + frames (binary WebSocket)
```

## Components (backend `app/`)
| Module | Responsibility |
| --- | --- |
| `browser/manager.py` | Lazily launches one Chromium; one isolated `BrowserContext` + page per TaskPilot session (`accept_downloads=False`, service workers blocked, HTTPS errors not ignored). Session limit, idle expiry, crash detection, shutdown. |
| `browser/session.py` | `BrowserSession` (context, page, status, lock, latest frame only, safe URL/title). `safe_url()` strips query, fragment and credentials. |
| `browser/navigation_guard.py` | Allow-list, scheme and private-network checks for every request; redirect validation. See [BROWSER_SECURITY.md](BROWSER_SECURITY.md). |
| `browser/download_guard.py` | Cancels every download and reports only the sanitised file name. |
| `browser/dom_inspector.py` | Trusted JS that lists visible interactive elements (roles, names, labels, nearby text, sensitivity flags; **never values**), page summary (auth detection), region extraction. |
| `browser/selector_resolver.py` | Maps a planned `TargetDescription` to exactly one element. See [PLAYWRIGHT_CONTROLLER.md](PLAYWRIGHT_CONTROLLER.md). |
| `browser/controller.py` | The only Playwright-facing action API: `navigate`, `resolve`, `click`, `type_text`, `extract`, `get_page_state`, `capture_screenshot`. |
| `browser/actions/*` | One handler per action type; each returns an `ActionResult` built from observed behaviour. |
| `policies/browser_action_policy.py` | Runtime policy checked immediately before every click/type, using the element actually found on the page. |
| `browser/executor.py` | Runs steps sequentially, enforces dependencies, step timeouts and cancellation, emits telemetry and frames. See [EXECUTION_ENGINE.md](EXECUTION_ENGINE.md). |
| `browser/screenshot_manager.py`, `browser/stream_manager.py` | Real JPEG viewport screenshots and the binary stream. See [BROWSER_STREAM_PROTOCOL.md](BROWSER_STREAM_PROTOCOL.md). |
| `execution/*` | Queue, manager, approval coordinator, context, results. |
| `browser/session_store.py` | Optional Fernet-encrypted storage state (off by default). See [BROWSER_SESSION_MANAGEMENT.md](BROWSER_SESSION_MANAGEMENT.md). |

## Frontend
- `lib/browserApi.ts` (Zod-validated REST), `lib/browserStream.ts` (strict binary frame parser).
- `hooks/useBrowserStream.ts` (stream socket, newest frame only, object URLs revoked, backoff reconnect), `hooks/useExecution.ts` (Run Plan / Stop / reload recovery), `hooks/useBrowserSession.ts` (status, session info, Close).
- Reducer: `execution` (per active task) and `browser` (session-level) state, driven by the new telemetry events.
- Components: `BrowserPreview`, `LiveBrowserFrame`, `BrowserToolbar`, `BrowserStatus`, `BrowserControls`, `BrowserErrorBanner`, `BrowserSessionInfo`, `BrowserEmptyState`; `ExecutionControls`, `ExecutionTimeline`, `ExecutionStep`, `ExecutionSummary`.

## What is real and what is not
- Frames are genuine Chromium viewport screenshots; there are no placeholder images.
- Step statuses come only from observed behaviour (navigation, DOM mutation, input value). A click without an observed change is reported as such.
- Tested against the **local fixture shop** (`backend/tests/fixtures/browser_site/`) only. Public sites (Blinkit, Amazon, YouTube, Google) are allow-listed but **were not tested** in Phase 3, and their markup, bot protection and sign-in walls may stop a run.

## Phase 5 additions
- `BrowserController.fill_checked(..., rich=True)` fills and verifies contenteditable editors (Gmail body);
  `press_checked()` presses only Tab/Enter/Escape on an element the caller's policy already allowed.
- Integration adapters (`app/integrations/*/adapter.py`) use only `navigate`, `evaluate` (fixed trusted scripts),
  `page_for` locators and the checked click/fill/press primitives with an allowed `IntegrationPolicy` decision.
- `INTEGRATION_ALLOWED_DOMAINS` (youtube.com, youtu.be, mail.google.com, calendar.google.com) is merged into the
  browser allow-list when integrations are enabled. Browser downloads stay disabled; files use the separate safe
  downloader.
