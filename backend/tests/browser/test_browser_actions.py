"""Action handlers against real Chromium + the local fixture site (no public sites)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.browser.actions import default_handlers
from app.browser.controller import BrowserController
from app.execution.execution_context import ExecutionContext
from app.execution.execution_result import ActionExecutionStatus as S
from app.policies.browser_action_policy import BrowserActionPolicy
from app.schemas.action import (
    ClickAction,
    ExtractAction,
    NavigateAction,
    RequestApprovalAction,
    StopAction,
    TypeAction,
)
from app.schemas.approval import RiskLevel
from app.schemas.plan import PlannedAction, PlanStatus, TaskPlan
from app.schemas.intent import IntentType
from app.schemas.common import utc_now

from .conftest import RecordingTelemetry, fixture_url

HANDLERS = default_handlers()


class NoApprovals:
    """Any attempt to create an approval fails the test."""

    created = 0

    async def create(self, **_: Any) -> Any:
        NoApprovals.created += 1
        raise AssertionError("an approval must not be requested here")


def planned(action: Any) -> PlannedAction:
    return PlannedAction(
        step_id=uuid4(), order=1, action=action, description=getattr(action, "target_description", None) or "step",
        expected_outcome="ok", risk_level=RiskLevel.LOW,
    )


@pytest.fixture
async def ctx(controller: BrowserController, telemetry: RecordingTelemetry) -> ExecutionContext:
    sid = uuid4()
    await controller.manager.get_or_create_session(sid)
    plan = TaskPlan(
        plan_id=uuid4(), task_id=uuid4(), session_id=sid, status=PlanStatus.READY, intent=IntentType.ECOMMERCE_SEARCH,
        summary="t", user_facing_message="t", confidence=1, provider="test", model="test", created_at=utc_now(),
    )
    return ExecutionContext(
        task_id=plan.task_id, session_id=sid, plan=plan, controller=controller, policy=BrowserActionPolicy(),
        telemetry=telemetry, approvals=NoApprovals(), tasks=None,  # type: ignore[arg-type]
        approval_ttl_seconds=10, max_retries=1,
    )


async def run(ctx: ExecutionContext, action: Any, next_action: Any | None = None) -> Any:
    ctx.current_step = planned(action)
    ctx.next_step = planned(next_action) if next_action is not None else None
    ctx.step_started_at = utc_now()
    return await HANDLERS[action.type].execute(action, ctx)


def go(origin: str, name: str) -> NavigateAction:
    return NavigateAction(type="navigate", url=fixture_url(origin, name), purpose="open")


async def page(ctx: ExecutionContext) -> Any:
    return (await ctx.controller.manager.get_session(ctx.session_id)).page


async def test_navigate_success_reports_safe_url(ctx: ExecutionContext, fixture_origin: str, telemetry: RecordingTelemetry) -> None:
    result = await run(ctx, go(fixture_origin, "index.html?token=abc"))
    assert result.status == S.SUCCEEDED and result.verified
    assert "token" not in str(telemetry.events)
    assert "browser.navigation_completed" in telemetry.types()


async def test_navigate_to_disallowed_domain_is_blocked(ctx: ExecutionContext) -> None:
    result = await run(ctx, NavigateAction(type="navigate", url="https://evil.example.net/", purpose="x"))
    assert result.status == S.BLOCKED and result.error_code == "NAVIGATION_BLOCKED"


async def test_login_page_stops_with_authentication_required(ctx: ExecutionContext, fixture_origin: str, telemetry: RecordingTelemetry) -> None:
    result = await run(ctx, go(fixture_origin, "login.html"))
    assert result.status == S.BLOCKED and result.error_code == "AUTHENTICATION_REQUIRED"
    assert "browser.authentication_required" in telemetry.types()


async def test_click_success_is_verified_by_observed_change(ctx: ExecutionContext, fixture_origin: str) -> None:
    await run(ctx, go(fixture_origin, "approval.html"))
    result = await run(ctx, ClickAction(type="click", target_description="Save to wishlist button", role_hint="button", accessible_name="Save to wishlist"))
    assert result.status == S.SUCCEEDED and result.verified and result.confidence and result.confidence >= 0.82
    assert await (await page(ctx)).text_content("#saved") == "Saved to wishlist"


async def test_click_timeout_is_reported_not_retried(ctx: ExecutionContext) -> None:
    p = await page(ctx)
    # visible but permanently covered by an overlay: Playwright's actionability check times out
    await p.set_content(
        "<button style='position:absolute;top:10px;left:10px'>Apply coupon</button>"
        "<div style='position:fixed;inset:0;background:rgba(0,0,0,.01)'></div>"
    )
    ctx.controller._action_timeout = 800
    result = await run(ctx, ClickAction(type="click", target_description="Apply coupon button", role_hint="button", accessible_name="Apply coupon"))
    assert result.status == S.FAILED and result.error_code == "ACTION_TIMEOUT" and result.retry_count == 0


async def test_payment_click_is_blocked_and_never_performed(ctx: ExecutionContext, fixture_origin: str) -> None:
    await run(ctx, go(fixture_origin, "cart.html"))
    result = await run(ctx, ClickAction(type="click", target_description="Pay button", role_hint="button", accessible_name="Place order and pay"))
    assert result.status == S.BLOCKED and result.error_code == "SENSITIVE_ACTION_BLOCKED"
    assert await (await page(ctx)).get_attribute("#purchase-log", "data-purchased") == "no"


async def test_type_into_search_box(ctx: ExecutionContext, fixture_origin: str) -> None:
    await run(ctx, go(fixture_origin, "index.html"))
    result = await run(ctx, TypeAction(type="type", target_description="Search box", text="bread"))
    assert result.status == S.SUCCEEDED and result.verified
    assert "search.html" in (await page(ctx)).url  # search fields submit with Enter


@pytest.mark.parametrize("field", ["Password field", "One-time code (OTP) field"])
async def test_typing_into_password_or_otp_fields_is_blocked(ctx: ExecutionContext, fixture_origin: str, field: str) -> None:
    p = await page(ctx)
    await p.goto(fixture_url(fixture_origin, "login.html"))
    result = await run(ctx, TypeAction(type="type", target_description=field, text="hello123"))
    assert result.status == S.BLOCKED and result.error_code == "SENSITIVE_ACTION_BLOCKED"
    assert await p.input_value("#pw") == "" and await p.input_value("#otp") == ""


async def test_credential_like_text_is_never_typed(ctx: ExecutionContext, fixture_origin: str) -> None:
    await run(ctx, go(fixture_origin, "index.html"))
    result = await run(ctx, TypeAction(type="type", target_description="Search box", text="my otp is 482913"))
    assert result.status == S.BLOCKED
    assert await (await page(ctx)).input_value("input[type=search]") == ""


async def test_extract_returns_structured_observed_data_and_redacts(ctx: ExecutionContext, fixture_origin: str) -> None:
    p = await page(ctx)
    await p.goto(fixture_url(fixture_origin, "search.html?q=milk"))
    result = await run(ctx, ExtractAction(type="extract", target_description="search results", fields=["name", "price", "quantity", "availability"]))
    assert result.status == S.SUCCEEDED
    data = result.extracted_data
    assert data["source"] == "observed_dom" and data["item_count"] >= 3
    first = data["items"][0]
    assert first["name"] == "Amul Taaza Toned Milk" and first["price"] == "₹54" and first["quantity"] == "1 L"
    await p.set_content("<ul aria-label='Offers'><li><h3>Card</h3><p>Use card 4111 1111 1111 1111</p></li></ul>")
    redacted = await run(ctx, ExtractAction(type="extract", target_description="offers", fields=["text"]))
    assert "4111 1111 1111 1111" not in str(redacted.extracted_data)


async def test_extract_reports_nothing_found_honestly(ctx: ExecutionContext) -> None:
    await (await page(ctx)).set_content("<p>empty</p>")
    result = await run(ctx, ExtractAction(type="extract", target_description="order history table", fields=["name"]))
    assert result.status == S.FAILED and result.error_code == "EXTRACTION_EMPTY"


async def test_approval_precheck_blocks_manual_only_action_without_asking(ctx: ExecutionContext) -> None:
    gate = RequestApprovalAction(type="request_approval", reason="checkout", risk_level=RiskLevel.CRITICAL)
    nxt = ClickAction(type="click", target_description="Proceed to checkout button", accessible_name="Proceed to checkout")
    before = NoApprovals.created
    result = await run(ctx, gate, nxt)
    assert result.status == S.BLOCKED and result.error_code == "SENSITIVE_ACTION_BLOCKED"
    assert NoApprovals.created == before


async def test_stop_action_succeeds(ctx: ExecutionContext) -> None:
    result = await run(ctx, StopAction(type="stop", reason="done"))
    assert result.status == S.SUCCEEDED
