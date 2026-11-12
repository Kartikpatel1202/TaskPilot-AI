"""Browser status/session operations for the API. Never exposes Playwright objects or paths."""

from __future__ import annotations

from uuid import UUID

from app.browser.errors import BrowserSessionNotFoundError
from app.browser.manager import BrowserManager
from app.browser.session import CapturedFrame
from app.browser.stream_manager import BrowserStreamManager
from app.config import Settings
from app.execution.execution_manager import ExecutionManager
from app.schemas.browser import BrowserSessionCloseResponse, BrowserSessionInfo, BrowserStatusResponse


class BrowserService:
    def __init__(
        self, *, settings: Settings, manager: BrowserManager, stream: BrowserStreamManager, execution: ExecutionManager
    ) -> None:
        self._settings = settings
        self._manager = manager
        self._stream = stream
        self._execution = execution

    def status(self) -> BrowserStatusResponse:
        installed = self._manager.installation_available()
        enabled = self._settings.agent_browser_execution_enabled
        if not installed:
            state = "unavailable"
        elif self._manager.is_started:
            state = "ready"
        else:
            state = "not_started"
        message = None
        if not enabled:
            message = "Browser execution is disabled by configuration."
        elif not installed:
            message = self._manager.unavailable_reason
        return BrowserStatusResponse(
            available=installed and enabled,
            status=state,  # type: ignore[arg-type]
            engine=self._settings.browser_engine,
            active_sessions=self._manager.active_session_count,
            max_sessions=self._settings.browser_max_sessions,
            headless=self._settings.browser_headless,
            message=message,
        )

    def session_info(self, session_id: UUID) -> BrowserSessionInfo:
        session = self._manager.peek_session(session_id)
        if session is None:
            raise BrowserSessionNotFoundError()
        subs = self._stream.subscriber_count(session_id)
        return BrowserSessionInfo(
            session_id=session_id,
            status=session.status,
            current_url=session.current_url,
            current_title=session.current_title,
            active_task_id=session.active_task_id,
            created_at=session.created_at,
            last_activity_at=session.last_activity_at,
            stream_status="CONNECTED" if subs else "DISCONNECTED",
            stream_subscribers=subs,
            has_screenshot=session.latest_frame is not None,
            auth_required=session.auth_required,
            headless=session.headless,
        )

    async def close_session(self, session_id: UUID) -> BrowserSessionCloseResponse:
        session = self._manager.peek_session(session_id)
        if session is None:
            raise BrowserSessionNotFoundError()
        active = self._execution.active_task_for(session_id)
        if active is not None:
            await self._execution.stop_task(active, session_id, "Browser session closed by you")
        await self._stream.close_session(session_id)
        closed = await self._manager.close_session(session_id, reason="Closed by you")
        return BrowserSessionCloseResponse(session_id=session_id, closed=closed, message="Browser session closed.")

    def latest_frame(self, session_id: UUID) -> CapturedFrame | None:
        session = self._manager.peek_session(session_id)
        if session is None:
            raise BrowserSessionNotFoundError()
        return session.latest_frame
