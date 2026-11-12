"""One TaskPilot session's isolated browser state.

Playwright objects live only here and in trusted browser modules; they are never
serialised, returned by API routes, or handed to LLM code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from app.schemas.browser import BrowserSessionStatus
from app.schemas.common import utc_now

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


def safe_url(url: str | None) -> str | None:
    """URL for display/telemetry: query strings and fragments removed (they may carry tokens)."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return parts.scheme + ":" if parts.scheme else None
    return urlunsplit((parts.scheme, parts.netloc.split("@")[-1], parts.path, "", ""))


@dataclass
class CapturedFrame:
    """Latest screenshot only — no history is kept."""

    frame_id: UUID
    sequence: int
    captured_at: datetime
    jpeg: bytes
    width: int
    height: int
    task_id: UUID | None


@dataclass(eq=False)
class BrowserSession:
    session_id: UUID
    context: BrowserContext
    page: Page
    headless: bool
    created_at: datetime = field(default_factory=utc_now)
    last_activity_at: datetime = field(default_factory=utc_now)
    status: BrowserSessionStatus = BrowserSessionStatus.READY
    current_url: str | None = None
    current_title: str | None = None
    is_authenticated: bool | None = None
    auth_required: bool = False
    active_task_id: UUID | None = None
    latest_frame: CapturedFrame | None = None
    frame_sequence: int = 0
    # Serialises every action on this session: one action (and one execution) at a time.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Set while a sensitive field is focused / a login page is shown: no frames are captured.
    privacy_pause: bool = False
    # Trusted code may open extra pages (BrowserManager.new_page) up to the per-session limit.
    pending_trusted_pages: int = 0
    extra_pages: list[Any] = field(default_factory=list)
    blocked_navigation: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status not in (BrowserSessionStatus.CLOSED, BrowserSessionStatus.ERROR)

    def touch(self) -> None:
        self.last_activity_at = utc_now()

    async def refresh_page_info(self) -> None:
        try:
            self.current_url = safe_url(self.page.url)
            self.current_title = (await self.page.title())[:200] or None
        except Exception:  # page closed / navigating — keep previous values
            pass
