# Browser session management (Phase 3)

## Lifecycle
- **Lazy start.** Chromium launches on the first Run Plan, never at server start and never during planning. `GET /browser/status` reports `not_started` until then.
- **One context per TaskPilot session.** Each WebSocket session id gets its own `BrowserContext` (separate cookies and storage) and a single page. Pop-ups and new windows are closed immediately (`browser.popup_blocked`).
- **Limits.** `BROWSER_MAX_SESSIONS` (5) contexts; page-created pop-ups are closed; trusted code may open extra pages with `BrowserManager.new_page` up to `BROWSER_MAX_PAGES_PER_SESSION` (3, enforced); one active execution per session (`EXECUTION_MAX_TASKS_PER_SESSION=1`), enforced by the queue and by a per-session `asyncio.Lock`.
- **Idle expiry.** The background sweeper closes contexts idle for `BROWSER_SESSION_IDLE_TIMEOUT_MINUTES` (30).
- **Explicit close.** `POST /browser/sessions/{id}/close` (body `session_id` must match) stops any running execution, ends the stream and closes the context.
- **Crash handling.** If Chromium disconnects, every session is marked `ERROR` and `browser.session_error` (`BROWSER_CRASHED`) is emitted. A running plan fails cleanly and the next Run Plan relaunches Chromium.
- **Shutdown.** Executions are cancelled and finalised (`SERVER_SHUTDOWN`), streams closed, contexts closed, Playwright stopped.

## Statuses
`INITIALIZING → READY ⇄ BUSY`, plus `AUTH_REQUIRED`, `ERROR` and `CLOSED`. The dashboard derives its badge from these and from the stream state.

## Headless vs visible
`BROWSER_HEADLESS=true` (default) runs headless; the dashboard preview shows its real screenshots. With `false`, Chromium opens a visible window on the server machine (local development only).

## Persistence (off by default)
`BROWSER_PERSIST_SESSIONS=true` stores Playwright storage state (cookies/localStorage) on close and restores it on the next start, but only if `BROWSER_STATE_ENCRYPTION_KEY` holds a valid Fernet key (settings validation refuses to start otherwise).
- Files: `BROWSER_STATE_DIRECTORY/<sha256(session_id)>.state.enc`, permissions `0600`. The file name does not reveal the session id.
- Content: Fernet-encrypted JSON with the session id and a timestamp. On load, the id must match and the TTL must not have passed; otherwise the file is ignored and purged.
- Plain-text browser state is never written. `runtime/` is git-ignored.

TaskPilot never automates sign-in. If a site needs it, the run stops with `AUTHENTICATION_REQUIRED`. With a visible browser the user may sign in manually; with persistence enabled, that encrypted state is reused next time.
