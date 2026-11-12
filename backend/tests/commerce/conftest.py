"""Commerce test helpers: real Chromium + the LOCAL Blinkit-like / Amazon-like fixture sites.

Nothing here contacts blinkit.com or amazon.in. Fixture pages are clearly labelled fakes.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.browser.manager import BrowserManager
from app.commerce.base import CommerceContext
from app.commerce.policies.commerce_policy import CommercePolicy
from app.commerce.registry import fixture_binding
from app.config import Settings
from app.main import create_app
from app.schemas.product import CommercePlatform, ProductAvailability, ProductCandidate, ProductRequirement, ProductUnit

from ..browser.conftest import RecordingTelemetry, make_controller, make_guard
from ..conftest import browser_settings, post_command, wait_for_task_state


def commerce_settings(origin: str, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "commerce_enabled": True, "commerce_enable_fixtures": True, "commerce_selection_timeout_seconds": 20,
        "commerce_search_timeout_seconds": 8,
    }
    base.update(overrides)
    return browser_settings(origin, **base)


# ---------------------------------------------------------------------- adapter-level fixtures


@pytest.fixture
def ctelemetry() -> RecordingTelemetry:
    return RecordingTelemetry()


@pytest_asyncio.fixture
async def cmanager(fixture_origin: str, ctelemetry: RecordingTelemetry) -> AsyncIterator[BrowserManager]:
    mgr = BrowserManager(commerce_settings(fixture_origin), guard=make_guard(fixture_origin), telemetry=ctelemetry)  # type: ignore[arg-type]
    yield mgr
    await mgr.shutdown()


async def make_ctx(mgr: BrowserManager, origin: str, platform: CommercePlatform, telemetry: RecordingTelemetry,
                   *, controls: str = "reset=1") -> CommerceContext:
    sid = uuid4()
    await mgr.get_or_create_session(sid)
    controller = make_controller(mgr, commerce_settings(origin))
    binding = fixture_binding(platform, origin)
    await controller.navigate(sid, binding.url(f"index.html?{controls}"))
    return CommerceContext(session_id=sid, task_id=None, controller=controller, policy=CommercePolicy(), telemetry=telemetry,  # type: ignore[arg-type]
                           binding=binding, search_timeout=8, max_results=30, max_attempts=2)


async def page_eval(ctx: CommerceContext, script: str) -> Any:
    return await (await ctx.controller.page_for(ctx.session_id)).evaluate(script)


def req(name: str, *, brand: str | None = None, qty: float = 1, unit: str = "PACK", variant: str | None = None,
        specs: dict[str, str] | None = None, max_price: int | None = None, query: str | None = None) -> ProductRequirement:
    return ProductRequirement(
        product_id=uuid4(), query=query or " ".join(p for p in (brand, variant, name) if p), product_name=name, brand=brand,
        quantity=qty, unit=ProductUnit(unit), preferred_variant={"line": variant} if variant else {}, must_match_brand=bool(brand),
        required_specs=specs or {}, max_price=Decimal(max_price) if max_price else None,
    )


def cand(name: str, size: str | None = None, price: str | None = "50", *, brand: str | None = None, available: bool = True,
         variant: dict[str, str] | None = None) -> ProductCandidate:
    return ProductCandidate(
        candidate_id=uuid4(), platform=CommercePlatform.BLINKIT, product_name=name, brand=brand, pack_size=size,
        displayed_price=f"₹{price}" if price else None, normalized_price=Decimal(price) if price else None,
        availability=ProductAvailability.AVAILABLE if available else ProductAvailability.UNAVAILABLE,
        observed_at=datetime.now(timezone.utc), source_page="test", extraction_confidence=1.0, variant=variant or {},
    )


# ---------------------------------------------------------------------- app-level helpers


@pytest.fixture
def cclient(fixture_origin: str) -> Iterator[TestClient]:
    with TestClient(create_app(commerce_settings(fixture_origin))) as c:
        yield c


def container(client: TestClient) -> Any:
    return client.app.state.container  # type: ignore[attr-defined]


def planned(client: TestClient, command: str, session_id: str) -> tuple[str, dict[str, Any]]:
    task_id = post_command(client, command, session_id)["task_id"]
    task = wait_for_task_state(client, task_id, timeout=10)
    assert task["state"] == "PLANNED", task
    return task_id, client.get(f"/api/v1/tasks/{task_id}/plan").json()


def run(client: TestClient, task_id: str, session_id: str) -> None:
    r = client.post(f"/api/v1/tasks/{task_id}/execute", json={"session_id": session_id, "confirm_execution": True})
    assert r.status_code == 202, r.text


def wait_until(predicate: Any, timeout: float = 60.0, interval: float = 0.1) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("Condition not met in time")


def summary(client: TestClient, task_id: str, session_id: str) -> dict[str, Any]:
    return client.get(f"/api/v1/tasks/{task_id}/commerce/summary", params={"session_id": session_id}).json()


def results(client: TestClient, task_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/tasks/{task_id}/execution").json()["results"]


def pending_purchase_approval(client: TestClient, task_id: str, timeout: float = 60) -> Any:
    approvals = container(client).approvals

    def find() -> Any:
        return next((a for a in list(approvals._approvals.values())
                     if str(a.task_id) == task_id and a.status.value == "PENDING" and a.purchase is not None), None)

    return wait_until(find, timeout)


def pending_selection(client: TestClient, task_id: str, session_id: str, timeout: float = 60) -> dict[str, Any]:
    return wait_until(lambda: (s := summary(client, task_id, session_id)).get("pending_selection") and s, timeout)


def browser_eval(client: TestClient, session_id: str, script: str) -> Any:
    async def go() -> Any:
        session = container(client).browser.peek_session(UUID(session_id))
        return await session.page.evaluate(script)

    return client.portal.call(go)  # type: ignore[union-attr]


def fixture_url(origin: str, site: str, page: str) -> str:
    return f"{origin}/api/v1/dev/fixtures/commerce/{site}/{page}"


def prime(client: TestClient, session_id: str, origin: str, site: str, controls: str) -> None:
    """Set fixture state (reset, location, login, COD, prices) in this session's browser before a run."""

    async def go() -> None:
        browser = container(client).browser
        await browser.get_or_create_session(UUID(session_id))
        session = browser.peek_session(UUID(session_id))
        await session.page.goto(fixture_url(origin, site, f"index.html?{controls}"))

    client.portal.call(go)  # type: ignore[union-attr]
