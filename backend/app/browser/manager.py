"""Playwright browser lifecycle.

* Chromium is launched lazily, on the first accepted execution — never during
  planning — and the API stays up when Chromium is missing (status reports why).
* Every TaskPilot session gets its own BrowserContext (separate cookies, storage,
  cache); contexts are never shared or reused across sessions.
* Session count is bounded, idle sessions expire, a browser crash invalidates all
  sessions and the next execution relaunches Chromium.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.browser.download_guard import attach_download_guard
from app.browser.errors import (
    BrowserPageLimitError,
    BrowserSessionNotFoundError,
    BrowserCrashedError,
    BrowserSessionLimitError,
    BrowserUnavailableError,
)
from app.browser.navigation_guard import GuardDecision, NavigationGuard
from app.browser.session import BrowserSession, safe_url
from app.browser.session_store import SessionStore
from app.config import Settings
from app.core.execution_events import ExecutionEvents
from app.core.logging import get_logger
from app.schemas.browser import (
    BrowserSessionClosedPayload,
    BrowserSessionErrorPayload,
    BrowserSessionPayload,
    BrowserSessionStatus,
    DownloadBlockedPayload,
    NavigationBlockedPayload,
    PopupBlockedPayload,
)
from app.schemas.common import utc_now
from app.schemas.telemetry import TelemetryEventType

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright

logger = get_logger("browser.manager")

INSTALL_HINT = "Install it with: python -m playwright install chromium"


class BrowserManager:
    def __init__(
        self,
        settings: Settings,
        *,
        guard: NavigationGuard,
        telemetry: ExecutionEvents,
        store: SessionStore | None = None,
    ) -> None:
        self._settings = settings
        self.guard = guard
        self.egress_guard: Any = None  # LocalEgressGuardProxy in proxy mode without an external egress proxy
        self._telemetry = telemetry
        self._store = store
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._sessions: dict[UUID, BrowserSession] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._unavailable_reason: str | None = None
        self._install_checked: bool | None = None
        self._closing = False

    # ---------------------------------------------------------------- status

    @property
    def is_started(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    @property
    def active_session_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.is_active)

    @property
    def headless(self) -> bool:
        return self._settings.browser_headless

    @property
    def human_check_wait_seconds(self) -> int:
        return self._settings.browser_human_check_wait_seconds

    def installation_available(self) -> bool:
        """Cheap check that the Chromium binary exists, without launching it."""
        if self._unavailable_reason:
            return False
        if self.is_started:
            return True
        if self._install_checked is None:
            try:
                from playwright._impl._driver import compute_driver_executable  # noqa: F401

                self._install_checked = _chromium_installed()
            except Exception:  # noqa: BLE001
                self._install_checked = False
        return bool(self._install_checked)

    @property
    def unavailable_reason(self) -> str | None:
        if self._unavailable_reason:
            return self._unavailable_reason
        return None if self.installation_available() else f"Chromium is not installed. {INSTALL_HINT}"

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self.is_started:
                return
            if self._closing:
                raise BrowserUnavailableError("The browser is shutting down.")
            try:
                from playwright.async_api import async_playwright

                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                proxy_server = self._settings.egress_proxy_url or None
                if self._settings.browser_network_guard == "proxy":
                    if proxy_server is None:
                        from app.browser.egress_guard_proxy import LocalEgressGuardProxy

                        if self.egress_guard is None:
                            self.egress_guard = LocalEgressGuardProxy(
                                resolver=self.guard._resolver, trusted_origins=sorted(self.guard.trusted_origins))
                        proxy_server = await self.egress_guard.start()
                    self.guard.network_enforced = True
                self._browser = await asyncio.wait_for(
                    self._playwright.chromium.launch(
                        headless=self._settings.browser_headless,
                        args=["--disable-features=Translate,MediaRouter", "--no-default-browser-check"],
                        # Phase 6: in production every browser request leaves through the egress proxy, which
                        # resolves and checks the destination once (DNS-rebinding-resistant, network enforced).
                        # "<-loopback>" sends loopback through the proxy too, so local addresses are refused there.
                        **({"proxy": {"server": proxy_server, "bypass": "<-loopback>"}} if proxy_server else {}),
                    ),
                    timeout=self._settings.browser_start_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - reported as a safe status, never a crash
                text = str(exc)
                missing = "Executable doesn't exist" in text or "playwright install" in text
                self._unavailable_reason = (
                    f"Chromium is not installed. {INSTALL_HINT}" if missing else "Chromium failed to start."
                )
                logger.error("browser.launch_failed", extra={"missing_binary": missing, "error": type(exc).__name__})
                raise BrowserUnavailableError(self._unavailable_reason) from exc
            self._unavailable_reason = None
            self._browser.on("disconnected", lambda _b: self._on_browser_disconnected())
            logger.info("browser.started", extra={"version": self._browser.version, "headless": self.headless})

    def _on_browser_disconnected(self) -> None:
        if self._closing:
            return
        logger.error("browser.disconnected")
        self._browser = None
        for session in self._sessions.values():
            session.status = BrowserSessionStatus.ERROR
        crashed = list(self._sessions)
        self._sessions.clear()
        for session_id in crashed:
            asyncio.ensure_future(
                self._telemetry.emit(
                    session_id,
                    TelemetryEventType.BROWSER_SESSION_ERROR,
                    BrowserSessionErrorPayload(code="BROWSER_CRASHED", message=BrowserCrashedError.default_message),
                )
            )

    async def shutdown(self) -> None:
        self._closing = True
        for session_id in list(self._sessions):
            with contextlib.suppress(Exception):
                await self.close_session(session_id, reason="Server shutting down")
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
        self._browser = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
        self._playwright = None
        if self.egress_guard is not None:
            await self.egress_guard.stop()

    # ---------------------------------------------------------------- sessions

    async def get_session(self, session_id: UUID) -> BrowserSession | None:
        session = self._sessions.get(session_id)
        if session is not None and not session.is_active:
            self._sessions.pop(session_id, None)
            return None
        return session

    def session_count(self) -> int:
        return len(self._sessions)

    def peek_session(self, session_id: UUID) -> BrowserSession | None:
        session = self._sessions.get(session_id)
        return session if session is not None and session.is_active else None

    async def get_or_create_session(self, session_id: UUID) -> BrowserSession:
        existing = await self.get_session(session_id)
        if existing is not None:
            existing.touch()
            return existing
        await self.start()
        async with self._lifecycle_lock:
            existing = self._sessions.get(session_id)
            if existing is not None and existing.is_active:
                return existing
            if self.active_session_count >= self._settings.browser_max_sessions:
                raise BrowserSessionLimitError()
            assert self._browser is not None
            await self._telemetry.emit(
                session_id,
                TelemetryEventType.BROWSER_SESSION_STARTED,
                BrowserSessionPayload(
                    status=BrowserSessionStatus.INITIALIZING, engine="chromium", headless=self.headless,
                    message="Starting an isolated Chromium context.",
                ),
            )
            storage_state = self._store.load(session_id) if self._store else None
            context = await self._browser.new_context(
                viewport={"width": self._settings.browser_viewport_width, "height": self._settings.browser_viewport_height},
                device_scale_factor=1,
                accept_downloads=False,
                ignore_https_errors=False,
                java_script_enabled=True,
                permissions=[],
                service_workers="block",  # service workers would bypass request interception
                storage_state=storage_state,  # type: ignore[arg-type]
                locale="en-IN",
            )
            context.set_default_timeout(self._settings.browser_action_timeout_ms)
            context.set_default_navigation_timeout(self._settings.browser_navigation_timeout_ms)
            page = await context.new_page()
            session = BrowserSession(session_id=session_id, context=context, page=page, headless=self.headless)
            await self._wire(session)
            self._sessions[session_id] = session

        await self._telemetry.emit(
            session_id,
            TelemetryEventType.BROWSER_SESSION_READY,
            BrowserSessionPayload(status=BrowserSessionStatus.READY, engine="chromium", headless=self.headless),
        )
        logger.info("browser.session_created", extra={"session": str(session_id)[:8], "active": self.active_session_count})
        return session

    async def _wire(self, session: BrowserSession) -> None:
        sid = session.session_id

        async def on_blocked(kind: str, decision: GuardDecision) -> None:
            session.blocked_navigation = decision.url
            await self._telemetry.emit(
                sid,
                TelemetryEventType.BROWSER_NAVIGATION_BLOCKED,
                NavigationBlockedPayload(
                    url=safe_url(decision.url) or "blocked", domain=decision.domain,
                    reason_code=decision.code or "NAVIGATION_BLOCKED",
                    message=decision.message or "Navigation blocked by the browser policy.",
                ),
                task_id=session.active_task_id,
            )

        await self.guard.install(session.context, on_blocked)

        async def on_download(filename: str) -> None:
            await self._telemetry.emit(
                sid,
                TelemetryEventType.BROWSER_DOWNLOAD_BLOCKED,
                DownloadBlockedPayload(filename=filename, message="Downloads are blocked in Phase 3."),
                task_id=session.active_task_id,
            )

        attach_download_guard(session.page, on_download)

        max_pages = self._settings.browser_max_pages_per_session

        def on_new_page(page: Page) -> None:
            # Page-created popups/new windows are always closed; only trusted code (new_page) may
            # open extra pages, and never beyond BROWSER_MAX_PAGES_PER_SESSION.
            if page is session.page:
                return
            if session.pending_trusted_pages > 0 and len(session.context.pages) <= max_pages:
                session.pending_trusted_pages -= 1
                session.extra_pages.append(page)
                page.on("close", lambda p: session.extra_pages.remove(p) if p in session.extra_pages else None)
                attach_download_guard(page, on_download)
                return
            opener_url = safe_url(page.url)
            asyncio.ensure_future(page.close())
            asyncio.ensure_future(
                self._telemetry.emit(
                    sid,
                    TelemetryEventType.BROWSER_POPUP_BLOCKED,
                    PopupBlockedPayload(url=opener_url, message="A popup or new tab was blocked."),
                    task_id=session.active_task_id,
                )
            )

        session.context.on("page", on_new_page)
        session.page.on("crash", lambda _p: setattr(session, "status", BrowserSessionStatus.ERROR))

    async def new_page(self, session_id: UUID) -> Page:
        """Open an extra page in this session's context (trusted callers only), enforcing the page limit."""
        session = self._sessions.get(session_id)
        if session is None or not session.is_active:
            raise BrowserSessionNotFoundError()
        if len(session.context.pages) >= self._settings.browser_max_pages_per_session:
            raise BrowserPageLimitError()
        session.pending_trusted_pages += 1
        try:
            page = await session.context.new_page()
        except Exception:
            session.pending_trusted_pages = 0
            raise
        if page not in session.extra_pages:  # closed by on_new_page (limit reached concurrently)
            session.pending_trusted_pages = 0
            raise BrowserPageLimitError()
        return page

    def page_count(self, session_id: UUID) -> int:
        session = self._sessions.get(session_id)
        return len(session.context.pages) if session is not None else 0

    async def close_session(self, session_id: UUID, *, reason: str = "Closed by user") -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.status = BrowserSessionStatus.CLOSED
        if self._store is not None:
            with contextlib.suppress(Exception):
                state: dict[str, Any] = await session.context.storage_state()  # type: ignore[assignment]
                self._store.save(session_id, state)
        with contextlib.suppress(Exception):
            await session.context.close()
        session.latest_frame = None
        if not self._closing:
            await self._telemetry.emit(
                session_id, TelemetryEventType.BROWSER_SESSION_CLOSED, BrowserSessionClosedPayload(reason=reason)
            )
        logger.info("browser.session_closed", extra={"session": str(session_id)[:8]})
        return True

    async def expire_idle(self) -> int:
        cutoff = utc_now() - timedelta(minutes=self._settings.browser_session_idle_timeout_minutes)
        expired = [
            sid for sid, s in self._sessions.items() if s.last_activity_at < cutoff and not s.lock.locked()
        ]
        for sid in expired:
            await self.close_session(sid, reason="Closed after inactivity")
        if self._store is not None:
            self._store.purge_expired()
        return len(expired)

    def snapshot_sessions(self) -> list[BrowserSession]:
        return [s for s in self._sessions.values() if s.is_active]


def _chromium_installed() -> bool:
    """True when Playwright's Chromium binary is present on disk."""
    import os

    from playwright._impl._driver import compute_driver_executable  # noqa: F401

    roots = []
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        roots.append(env)
    home = os.path.expanduser("~")
    roots += [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
        os.path.join(home, ".cache", "ms-playwright"),
        os.path.join(home, "Library", "Caches", "ms-playwright"),
    ]
    for root in roots:
        if root and os.path.isdir(root) and any(
            name.startswith(("chromium-", "chromium_headless_shell-")) for name in os.listdir(root)
        ):
            return True
    return False
