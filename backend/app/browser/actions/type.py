from __future__ import annotations

from typing import TYPE_CHECKING

from app.browser.errors import BrowserError, SelectorResolutionError
from app.browser.selector_resolver import tokens
from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.action import ClickAction, TypeAction
from app.schemas.browser import DOMElementInfo, TargetDescription

from .base import error_result

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


def is_search_field(el: DOMElementInfo, description: str) -> bool:
    if el.role == "searchbox" or (el.input_type or "") == "search":
        return True
    return "search" in tokens(el.accessible_name, el.placeholder, el.aria_label, el.label, description)


def next_is_explicit_submit(ctx: ExecutionContext) -> bool:
    nxt = ctx.next_step
    if nxt is None or not isinstance(nxt.action, ClickAction):
        return False
    words = tokens(nxt.action.target_description, nxt.action.accessible_name, nxt.action.text_hint)
    return bool(words & {"search", "submit", "go", "find"})


class TypeHandler:
    action_type = "type"

    async def execute(self, action: TypeAction, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        target = TargetDescription(description=action.target_description, role_hint="textbox")
        try:
            await ctx.controller.ensure_allowed_page(ctx.session_id)
            try:
                resolved = await ctx.controller.resolve(ctx.session_id, target, "type")
            except SelectorResolutionError as exc:
                from .click import _recover

                recovered = await _recover(ctx, target, "type", exc)
                if recovered is None:
                    raise
                resolved = recovered
            if action.sensitive:
                decision = ctx.policy.check_type(resolved.element.model_copy(update={"is_sensitive": True}), action.text)
            else:
                decision = ctx.policy.check_type(resolved.element, action.text)
            if not decision.allowed:
                return ctx.result(
                    ActionExecutionStatus.BLOCKED, decision.message or "Blocked.", error_code=decision.code,
                    strategy=resolved.strategy, confidence=resolved.confidence,
                )
            # Search boxes are submitted with Enter unless the plan has its own search-button click next.
            submit = is_search_field(resolved.element, action.target_description) and not next_is_explicit_submit(ctx)
            value_ok, outcome = await ctx.controller.type_text(
                ctx.session_id, resolved, action.text, clear_first=action.clear_first, submit=submit
            )
        except BrowserError as exc:
            return error_result(ctx, exc)

        field = resolved.element.accessible_name or action.target_description
        # The typed value itself is never logged or sent in telemetry.
        if not value_ok:
            return ctx.result(
                ActionExecutionStatus.FAILED, f"Typed into “{field}”, but the field did not keep the text.",
                error_code="TYPE_NOT_VERIFIED", strategy=resolved.strategy, confidence=resolved.confidence,
            )
        message = f"Typed {len(action.text)} characters into “{field}”."
        if outcome is not None:
            message += " Submitted the search; results " + ("loaded." if outcome.observed_change else "did not visibly change.")
        return ctx.result(
            ActionExecutionStatus.SUCCEEDED, message, verified=True,
            strategy=resolved.strategy, confidence=resolved.confidence,
        )
