from __future__ import annotations

from typing import TYPE_CHECKING

from app.browser.errors import BrowserError, SelectorAmbiguousError, SelectorResolutionError
from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.action import ClickAction
from app.schemas.browser import TargetDescription

from .base import error_result

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


class ClickHandler:
    action_type = "click"

    async def execute(self, action: ClickAction, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        target = TargetDescription(
            description=action.target_description, role_hint=action.role_hint,
            accessible_name=action.accessible_name, text_hint=action.text_hint,
        )
        try:
            await ctx.controller.ensure_allowed_page(ctx.session_id)
            try:
                resolved = await ctx.controller.resolve(ctx.session_id, target, "click")
            except SelectorResolutionError as exc:
                recovered = await _recover(ctx, target, "click", exc)
                if recovered is None:
                    raise
                resolved = recovered
            page_state = await ctx.controller.get_page_state(ctx.session_id)
            decision = ctx.policy.check_click(resolved.element, action.target_description, page_state)
            if not decision.allowed:
                # The prohibited control is never clicked.
                return ctx.result(
                    ActionExecutionStatus.BLOCKED, decision.message or "Blocked.", error_code=decision.code,
                    strategy=resolved.strategy, confidence=resolved.confidence,
                )
            # Clicks are not idempotent (e.g. "Add"): never retried after an uncertain outcome.
            try:
                outcome = await ctx.controller.click(ctx.session_id, resolved)
            except SelectorResolutionError as exc:
                # The control vanished before any click was dispatched (re-render): re-resolve once, policy-checked.
                recovered = await _recover(ctx, target, "click", exc)
                if recovered is None:
                    raise
                resolved = recovered
                decision = ctx.policy.check_click(resolved.element, action.target_description, await ctx.controller.get_page_state(ctx.session_id))
                if not decision.allowed:
                    return ctx.result(ActionExecutionStatus.BLOCKED, decision.message or "Blocked.", error_code=decision.code,
                                      strategy=resolved.strategy, confidence=resolved.confidence)
                outcome = await ctx.controller.click(ctx.session_id, resolved)
        except BrowserError as exc:
            return error_result(ctx, exc)

        name = resolved.element.accessible_name or action.target_description
        if outcome.navigated:
            message = f"Clicked “{name}”; the page changed to {outcome.url}."
        elif outcome.dom_changed:
            message = f"Clicked “{name}”; the page updated."
        else:
            message = f"Clicked “{name}”; no visible change was observed."
        return ctx.result(
            ActionExecutionStatus.SUCCEEDED, message, verified=outcome.observed_change,
            strategy=resolved.strategy, confidence=resolved.confidence,
        )


async def _recover(ctx: ExecutionContext, target: TargetDescription, intent: str, exc: SelectorResolutionError) -> object | None:
    """Phase 6 bounded self-correction. Ambiguity is never 'healed' by guessing."""
    if ctx.recovery is None or isinstance(exc, SelectorAmbiguousError):
        return None
    step = ctx.current_step
    risk = step.risk_level if step is not None else None
    from app.schemas.approval import RiskLevel

    return await ctx.recovery.recover(ctx, target, intent, exc, step_risk=risk or RiskLevel.LOW)
