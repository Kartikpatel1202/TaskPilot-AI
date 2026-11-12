"""Real Playwright viewport screenshots (JPEG), bounded in size and frequency.

Only the latest frame per session is kept. Nothing is captured while a password,
OTP or payment field is visible (privacy pause) — the preview simply holds the
previous frame and says so.
"""

from __future__ import annotations

import time
from uuid import UUID, uuid4

from app.browser.errors import ScreenshotError
from app.browser.session import BrowserSession, CapturedFrame
from app.core.logging import get_logger
from app.schemas.common import utc_now

logger = get_logger("browser.screenshots")

_SENSITIVE_VISIBLE_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const RX = /(\botp\b|one[-_ ]?time|cvv|cvc|card[-_ ]?number|cc-number|cc-csc)/i;
  return [...document.querySelectorAll('input')].some((i) => vis(i) && (
    i.type === 'password' || /one-time-code|cc-/.test(i.getAttribute('autocomplete') || '') ||
    RX.test([i.name, i.id, i.getAttribute('placeholder'), i.getAttribute('aria-label')].join(' '))));
}
"""


class ScreenshotManager:
    def __init__(self, *, quality: int, max_bytes: int, fps: float, width: int, height: int) -> None:
        self.quality = quality
        self.max_bytes = max_bytes
        self.min_interval = 1.0 / fps
        self.width = width
        self.height = height
        self._last_capture: dict[UUID, float] = {}

    def due(self, session_id: UUID) -> bool:
        return time.monotonic() - self._last_capture.get(session_id, 0.0) >= self.min_interval

    async def sensitive_content_visible(self, session: BrowserSession) -> bool:
        try:
            return bool(await session.page.evaluate(_SENSITIVE_VISIBLE_JS))
        except Exception:
            return False

    async def capture(self, session: BrowserSession, task_id: UUID | None = None) -> CapturedFrame | None:
        """Capture the active page. Returns None during a privacy pause; raises ScreenshotError on failure."""
        if await self.sensitive_content_visible(session):
            session.privacy_pause = True
            return None
        session.privacy_pause = False
        self._last_capture[session.session_id] = time.monotonic()
        data: bytes | None = None
        for quality in (self.quality, max(20, self.quality // 2)):
            try:
                data = await session.page.screenshot(
                    type="jpeg", quality=quality, full_page=False, timeout=5_000, caret="hide", scale="css"
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("screenshot.failed", extra={"session": str(session.session_id)[:8], "error": type(exc).__name__})
                raise ScreenshotError() from exc
            if len(data) <= self.max_bytes:
                break
            data = None
        if data is None:
            raise ScreenshotError("The screenshot exceeded the maximum frame size.")
        viewport = session.page.viewport_size or {"width": self.width, "height": self.height}
        session.frame_sequence += 1
        frame = CapturedFrame(
            frame_id=uuid4(),
            sequence=session.frame_sequence,
            captured_at=utc_now(),
            jpeg=data,
            width=int(viewport["width"]),
            height=int(viewport["height"]),
            task_id=task_id or session.active_task_id,
        )
        session.latest_frame = frame  # replaces the previous frame; no history
        return frame

    def forget(self, session_id: UUID) -> None:
        self._last_capture.pop(session_id, None)
