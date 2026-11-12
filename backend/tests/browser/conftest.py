"""Shared fixtures for real-Chromium browser tests against the local fixture site."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import BaseModel

from app.browser.controller import BrowserController
from app.browser.dom_inspector import DOMInspector
from app.browser.manager import BrowserManager
from app.browser.navigation_guard import NavigationGuard
from app.browser.screenshot_manager import ScreenshotManager
from app.browser.selector_resolver import SelectorResolver
from app.browser.session import BrowserSession
from app.config import Settings

from ..conftest import FIXTURE_PREFIX, browser_settings


class RecordingTelemetry:
    def __init__(self) -> None:
        self.events: list[tuple[UUID, str, dict[str, Any], UUID | None]] = []

    async def emit(self, session_id: UUID, event_type: Any, payload: BaseModel, task_id: UUID | None = None) -> None:
        self.events.append((session_id, event_type.value, payload.model_dump(mode="json"), task_id))

    def types(self) -> list[str]:
        return [e[1] for e in self.events]


def fixture_url(origin: str, name: str) -> str:
    return f"{origin}{FIXTURE_PREFIX}{name}"


async def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]  # documentation-range-like public address; no real DNS in tests


def make_guard(origin: str, settings: Settings | None = None) -> NavigationGuard:
    return NavigationGuard(
        allowed_domains=(settings.browser_allowed_domain_list if settings else ["example.com"]),
        trusted_origins=[origin],
        resolver=public_resolver,
    )


def make_controller(manager: BrowserManager, settings: Settings) -> BrowserController:
    inspector = DOMInspector()
    return BrowserController(
        manager=manager,
        inspector=inspector,
        resolver=SelectorResolver(
            inspector, min_confidence=settings.browser_selector_min_confidence, max_attempts=settings.browser_selector_max_attempts
        ),
        screenshots=ScreenshotManager(
            quality=settings.browser_screenshot_quality, max_bytes=settings.browser_max_frame_bytes,
            fps=settings.browser_screenshot_fps, width=settings.browser_viewport_width, height=settings.browser_viewport_height,
        ),
        action_timeout_ms=settings.browser_action_timeout_ms,
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
    )


@pytest.fixture
def settings_b(fixture_origin: str) -> Settings:
    return browser_settings(fixture_origin)


@pytest.fixture
def telemetry() -> RecordingTelemetry:
    return RecordingTelemetry()


@pytest_asyncio.fixture
async def manager(settings_b: Settings, fixture_origin: str, telemetry: RecordingTelemetry) -> AsyncIterator[BrowserManager]:
    mgr = BrowserManager(settings_b, guard=make_guard(fixture_origin), telemetry=telemetry)  # type: ignore[arg-type]
    yield mgr
    await mgr.shutdown()


@pytest_asyncio.fixture
async def session(manager: BrowserManager) -> BrowserSession:
    return await manager.get_or_create_session(uuid4())


@pytest_asyncio.fixture
async def controller(manager: BrowserManager, settings_b: Settings) -> BrowserController:
    return make_controller(manager, settings_b)


async def open_fixture(session: BrowserSession, origin: str, name: str) -> None:
    await session.page.goto(fixture_url(origin, name), wait_until="domcontentloaded")
