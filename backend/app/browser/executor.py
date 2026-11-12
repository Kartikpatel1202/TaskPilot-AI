"""Sequential plan executor.

Runs an already-validated TaskPlan step by step through the registered action
handlers. It never plans, never calls an LLM, never runs model-written code.
Every step status comes from an observed browser result; the task is COMPLETED
only when every step SUCCEEDED.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, TYPE_CHECKING

from app.observability.tracing import span
from app.browser.actions import BrowserActionHandler, default_handlers
from app.browser.stream_manager import BrowserStreamManager
from app.core.logging import get_logger
from app.execution.execution_context import ExecutionContext
from app.execution.execution_result import ActionExecutionStatus, ActionResult, ExecutionStatus, ExecutionSummary
from app.schemas.browser import BrowserActionPayload, FrameAvailablePayload, PageUpdatedPayload
from app.schemas.common import utc_now
from app.schemas.execution import (
    ExecutionStartedPayload,
    StepCompletedPayload,
    StepFailedPayload,
    StepStartedPayload,
)
from app.schemas.plan import PlannedAction
from app.schemas.telemetry import TelemetryEventType

if TYPE_CHECKING:
    from app.browser.session import BrowserSession

logger = get_logger("browser.executor")

CANCEL_CODES = {
    "USER_CANCELLED", "APPROVAL_REJECTED", "APPROVAL_EXPIRED", "SENSITIVE_ACTION_BLOCKED", "AUTHENTICATION_REQUIRED",
    # Phase 4 commerce: the user decided, or must act on the website themselves.
    "PURCHASE_REJECTED", "PURCHASE_APPROVAL_EXPIRED", "PURCHASE_APPROVAL_STALE", "COMMERCE_LOCATION_REQUIRED",
    "COMMERCE_SESSION_REQUIRED", "CAPTCHA_REQUIRED", "PURCHASE_POLICY_BLOCKED", "PAYMENT_USER_HANDOFF_REQUIRED",
    # Phase 5 integrations: the user decided, or must sign in / act on the website themselves.
    "CALENDAR_EVENT_REJECTED", "CALENDAR_APPROVAL_EXPIRED", "CALENDAR_APPROVAL_STALE", "GMAIL_LOGIN_REQUIRED", "CALENDAR_LOGIN_REQUIRED",
    "YOUTUBE_LOGIN_REQUIRED", "YOUTUBE_SELECTION_SKIPPED", "FILE_SELECTION_SKIPPED",
    # Phase 6: the user must reconcile an interrupted mutation; rate limits.
    "ACTION_STATE_UNKNOWN",
}
INTEGRATION_TYPES = frozenset({"youtube_search", "youtube_play", "gmail_create_draft", "calendar_create_event", "file_download"})


class PlanExecutor:
    def __init__(
        self,
        *,
        stream: BrowserStreamManager,
        step_timeout_seconds: float,
        handlers: dict[str, BrowserActionHandler] | None = None,
    ) -> None:
        self._stream = stream
        self._handlers = handlers or default_handlers()
        self._step_timeout = step_timeout_seconds
        # Phase 6 (set by the container): per-user browser action rate limit.
        self.rate_limiter: Any = None
        self.actions_per_minute: int = 0

    async def run(self, ctx: ExecutionContext, session: BrowserSession) -> ExecutionSummary:
        plan = ctx.plan
        summary = ExecutionSummary(
            task_id=ctx.task_id, session_id=ctx.session_id, plan_id=plan.plan_id,
            status=ExecutionStatus.EXECUTING, total_steps=len(plan.steps), started_at=utc_now(),
        )
        await ctx.telemetry.emit(
            ctx.session_id, TelemetryEventType.TASK_EXECUTION_STARTED,
            ExecutionStartedPayload(plan_id=plan.plan_id, total_steps=len(plan.steps), engine="chromium", headless=session.headless),
            task_id=ctx.task_id,
        )
        self._stream.keep_alive(ctx.session_id, 3600)
        stop_code: str | None = None
        stop_message: str | None = None
        soft_failures: list[ActionResult] = []
        soft_ids: set = set()  # steps that soft-failed (or were skipped because of one)

        for index, step in enumerate(plan.steps):
            if ctx.cancelled:
                stop_code, stop_message = "USER_CANCELLED", ctx.cancel_reason or "Stopped by you."
                break
            unmet = [d for d in step.depends_on if ctx.results.get(d) is None or ctx.results[d].status != ActionExecutionStatus.SUCCEEDED]
            if unmet and all(d in soft_ids for d in unmet):
                # Phase 5 partial success: a step that needs a failed independent step's result is skipped;
                # other independent steps still run. (Phase 4 commerce has no such dependencies.)
                skipped = ActionResult(
                    step_id=step.step_id, order=step.order, action_type=step.action.type, status=ActionExecutionStatus.SKIPPED,
                    started_at=utc_now(), message="Skipped: it needs the result of a step that did not succeed.",
                )
                ctx.results[step.step_id] = skipped
                summary.results.append(skipped)
                soft_ids.add(step.step_id)
                continue
            if unmet:
                stop_code, stop_message = "DEPENDENCY_FAILED", f"Step {step.order} depends on a step that did not succeed."
                break

            ctx.current_step = step
            ctx.next_step = plan.steps[index + 1] if index + 1 < len(plan.steps) else None
            ctx.step_started_at = utc_now()
            await self._emit_started(ctx, step)
            result = await self._run_step(ctx, step)
            ctx.results[step.step_id] = result
            summary.results.append(result)
            await self._emit_finished(ctx, step, result)
            await self._after_step(ctx, session)

            if result.status != ActionExecutionStatus.SUCCEEDED:
                soft = result.status == ActionExecutionStatus.FAILED or (
                    result.status == ActionExecutionStatus.BLOCKED and step.action.type in INTEGRATION_TYPES)
                if soft and getattr(step.action, "continue_on_failure", False) and not ctx.cancelled:
                    # An independent shopping item failed (e.g. unavailable), or one domain of a multi-domain
                    # workflow did not finish: keep going with independent steps; the run is reported as
                    # partial (never as complete).
                    soft_failures.append(result)
                    soft_ids.add(step.step_id)
                    continue
                stop_code = result.error_code or "STEP_FAILED"
                stop_message = result.message
                break

        # Steps that never ran are reported as SKIPPED — never as completed.
        for step in plan.steps:
            if step.step_id not in ctx.results:
                skipped = ActionResult(
                    step_id=step.step_id, order=step.order, action_type=step.action.type,
                    status=ActionExecutionStatus.SKIPPED, started_at=utc_now(), message="Not run.",
                )
                ctx.results[step.step_id] = skipped
                summary.results.append(skipped)
        summary.results.sort(key=lambda r: r.order)

        if stop_code is None and soft_failures:
            stop_code, stop_message = soft_failures[0].error_code or "STEP_FAILED", soft_failures[0].message
            partial = ctx.integrations.partial_note(ctx.task_id) if ctx.integrations is not None else None
            if partial:
                stop_message = partial
        if stop_code is None and all(r.status == ActionExecutionStatus.SUCCEEDED for r in summary.results):
            summary.status = ExecutionStatus.COMPLETED
            summary.message = self._completion_message(summary)
            note = ctx.commerce.completion_note(ctx.task_id) if ctx.commerce is not None else None
            if note is None and ctx.integrations is not None:
                note = ctx.integrations.completion_note(ctx.task_id)
            if note:  # e.g. an approved COD order really was placed — never claim "no order placed" then
                summary.message = note
        elif stop_code in CANCEL_CODES:
            summary.status = ExecutionStatus.CANCELLED
            summary.error_code, summary.message = stop_code, stop_message
        else:
            summary.status = ExecutionStatus.FAILED
            summary.error_code, summary.message = stop_code or "STEP_FAILED", stop_message
        summary.finished_at = utc_now()
        self._stream.keep_alive(ctx.session_id, 4)
        return summary

    # ---------------------------------------------------------------- steps

    async def _run_step(self, ctx: ExecutionContext, step: PlannedAction) -> ActionResult:
        with span("browser.step", component="executor", action_type=_action_name(step),
                  step_order=step.order):
            if self.rate_limiter is not None and self.actions_per_minute and not await self.rate_limiter.hit(
                    f"ba:{ctx.user_id or ctx.session_id}", self.actions_per_minute, 60):
                return ctx.result(ActionExecutionStatus.BLOCKED,
                                  "Too many browser actions in the last minute. The run was paused before this step; nothing was done.",
                                  error_code="RATE_LIMITED")
            return await self._run_step_journaled(ctx, step)

    async def _run_step_journaled(self, ctx: ExecutionContext, step: PlannedAction) -> ActionResult:
        if ctx.journal is None:
            return await self._run_handler(ctx, step)
        try:
            early = await ctx.journal.begin(ctx, step)
        except Exception:  # noqa: BLE001 - never run a possibly-duplicate mutation without its journal entry
            logger.exception("executor.journal_unavailable")
            return ctx.result(ActionExecutionStatus.FAILED, "The execution journal is unavailable, so the step was not run.",
                              error_code="JOURNAL_UNAVAILABLE")
        if early is not None:
            return early
        result = await self._run_handler(ctx, step)
        await ctx.journal.finish(ctx, step, result)
        return result

    async def _run_handler(self, ctx: ExecutionContext, step: PlannedAction) -> ActionResult:
        handler = self._handlers.get(step.action.type)
        if handler is None:
            return ctx.result(ActionExecutionStatus.FAILED, "Unsupported action.", error_code="ACTION_NOT_SUPPORTED")
        timeout = self._step_timeout
        if step.action.type == "request_approval":
            timeout = ctx.approval_ttl_seconds + 30
        elif step.action.type == "commerce":
            # searches, several cart clicks, a possible product choice and up to two purchase approvals
            selection = getattr(getattr(ctx.commerce, "settings", None), "commerce_selection_timeout_seconds", 300)
            timeout = self._step_timeout * 4 + selection + 2 * (ctx.approval_ttl_seconds + 30)
        elif step.action.type in INTEGRATION_TYPES:
            # page loads + verification, plus at most one user choice or one exact-event approval
            timeout = self._step_timeout * 4 + ctx.approval_ttl_seconds + 60
        work = asyncio.ensure_future(handler.execute(step.action, ctx))
        cancel = asyncio.ensure_future(ctx.cancel_event.wait())
        try:
            done, _ = await asyncio.wait({work, cancel}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                return work.result()
            work.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await work
            if cancel in done:
                return ctx.result(ActionExecutionStatus.FAILED, "Stopped by you during this step.", error_code="USER_CANCELLED")
            return ctx.result(ActionExecutionStatus.FAILED, "The step timed out.", error_code="ACTION_TIMEOUT")
        except Exception:  # handler bug: report safely, never a traceback
            logger.exception("executor.step_crashed", extra={"action": step.action.type})
            return ctx.result(ActionExecutionStatus.FAILED, "The step failed unexpectedly.", error_code="STEP_FAILED")
        finally:
            cancel.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel

    async def _emit_started(self, ctx: ExecutionContext, step: PlannedAction) -> None:
        await ctx.telemetry.emit(
            ctx.session_id, TelemetryEventType.TASK_STEP_STARTED,
            StepStartedPayload(step_id=step.step_id, order=step.order, action_type=step.action.type, description=step.description),
            task_id=ctx.task_id,
        )
        await ctx.telemetry.emit(
            ctx.session_id, TelemetryEventType.BROWSER_ACTION_STARTED,
            BrowserActionPayload(step_id=step.step_id, action_type=step.action.type, message=step.description),
            task_id=ctx.task_id,
        )

    async def _emit_finished(self, ctx: ExecutionContext, step: PlannedAction, result: ActionResult) -> None:
        if result.status == ActionExecutionStatus.SUCCEEDED:
            await ctx.telemetry.emit(
                ctx.session_id, TelemetryEventType.BROWSER_ACTION_COMPLETED,
                BrowserActionPayload(
                    step_id=step.step_id, action_type=step.action.type, message=result.message,
                    strategy=result.strategy, confidence=result.confidence,
                ),
                task_id=ctx.task_id,
            )
            await ctx.telemetry.emit(
                ctx.session_id, TelemetryEventType.TASK_STEP_COMPLETED,
                StepCompletedPayload(
                    step_id=step.step_id, order=step.order, status=result.status, duration_ms=result.duration_ms,
                    message=result.message, verified=result.verified, extracted_data=result.extracted_data,
                ),
                task_id=ctx.task_id,
            )
            return
        await ctx.telemetry.emit(
            ctx.session_id, TelemetryEventType.BROWSER_ACTION_FAILED,
            BrowserActionPayload(
                step_id=step.step_id, action_type=step.action.type, message=result.message,
                strategy=result.strategy, confidence=result.confidence, error_code=result.error_code,
            ),
            task_id=ctx.task_id,
        )
        event = TelemetryEventType.TASK_STEP_BLOCKED if result.status == ActionExecutionStatus.BLOCKED else TelemetryEventType.TASK_STEP_FAILED
        await ctx.telemetry.emit(
            ctx.session_id, event,
            StepFailedPayload(
                step_id=step.step_id, order=step.order, status=result.status,
                error_code=result.error_code or "STEP_FAILED", message=result.message, duration_ms=result.duration_ms,
            ),
            task_id=ctx.task_id,
        )

    async def _after_step(self, ctx: ExecutionContext, session: BrowserSession) -> None:
        await session.refresh_page_info()
        current = (session.current_url, session.current_title)
        if current != ctx.announced_page and session.current_url:
            ctx.announced_page = current
            from urllib.parse import urlsplit

            await ctx.telemetry.emit(
                ctx.session_id, TelemetryEventType.BROWSER_PAGE_UPDATED,
                PageUpdatedPayload(
                    url=session.current_url, title=session.current_title,
                    domain=urlsplit(session.current_url).hostname if session.current_url else None,
                ),
                task_id=ctx.task_id,
            )
        # A screenshot failure never changes a step's result.
        frame = await self._stream.capture_and_publish(ctx.session_id)
        if frame is not None:
            await ctx.telemetry.emit(
                ctx.session_id, TelemetryEventType.BROWSER_FRAME_AVAILABLE,
                FrameAvailablePayload(
                    frame_id=frame.frame_id, sequence=frame.sequence, width=frame.width, height=frame.height,
                    bytes=len(frame.jpeg), captured_at=frame.captured_at,
                ),
                task_id=ctx.task_id,
            )

    @staticmethod
    def _completion_message(summary: ExecutionSummary) -> str:
        unverified = [r.order for r in summary.results if r.action_type == "click" and not r.verified]
        message = f"All {summary.total_steps} steps ran in the browser and were checked."
        if unverified:
            message += f" Step(s) {', '.join(map(str, unverified))}: clicked, but no visible change was observed."
        return message + " No payment or order was placed."


def _action_name(step: PlannedAction) -> str:
    """Low-cardinality span attribute: the action's type name (never its arguments)."""
    action = getattr(step, "action", None)
    kind = getattr(action, "type", None) or getattr(action, "action", None) or type(action).__name__
    return str(getattr(kind, "value", kind))[:40]
