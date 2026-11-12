"""Runtime approval checkpoint.

Before asking a human, the NEXT planned action is checked against the hard
runtime policy: a manual-only action is blocked outright (an approval can never
unlock it). Otherwise a real approval request is raised, the task waits in
WAITING_APPROVAL, and execution resumes only on an explicit APPROVE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.action import ClickAction, RequestApprovalAction
from app.schemas.approval import ApprovalStatus
from app.schemas.execution import ExecutionPausedPayload, ExecutionResumedPayload
from app.schemas.task import TaskState
from app.schemas.telemetry import TelemetryEventType

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


class ApprovalHandler:
    action_type = "request_approval"

    async def execute(self, action: RequestApprovalAction, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        step = ctx.current_step
        nxt = ctx.next_step
        assert step is not None
        if nxt is None:
            return ctx.result(ActionExecutionStatus.SUCCEEDED, "No action follows this checkpoint.", verified=True)

        target = nxt.action.target_description if isinstance(nxt.action, ClickAction) else None
        decision = ctx.policy.check_planned(nxt.action.type, nxt.description, target)
        if not decision.allowed:
            return ctx.result(ActionExecutionStatus.BLOCKED, decision.message or "Blocked.", error_code=decision.code)

        session = await ctx.controller.manager.get_session(ctx.session_id)
        domain = urlsplit(session.page.url).hostname if session and session.page.url.startswith("http") else None
        details = "; ".join(f"{k}: {v}" for k, v in action.details.items()) or None
        approval = await ctx.approvals.create(
            task_id=ctx.task_id,
            session_id=ctx.session_id,
            action_summary=nxt.description,
            domain=domain or "unknown",
            reason=action.reason,
            risk_level=action.risk_level,
            estimated_impact=details,
            ttl_seconds=ctx.approval_ttl_seconds,
        )
        await ctx.tasks.transition(ctx.task_id, TaskState.WAITING_APPROVAL, reason="Waiting for your approval")
        await ctx.telemetry.emit(
            ctx.session_id, TelemetryEventType.TASK_EXECUTION_PAUSED,
            ExecutionPausedPayload(step_id=step.step_id, reason=action.reason, approval_id=approval.approval_id),
            task_id=ctx.task_id,
        )
        status = await ctx.approvals.wait(approval.approval_id, ctx.cancel_event, timeout=ctx.approval_ttl_seconds + 10)

        if status == ApprovalStatus.APPROVED:
            await ctx.tasks.transition(ctx.task_id, TaskState.EXECUTING, reason="Approved by you")
            await ctx.telemetry.emit(
                ctx.session_id, TelemetryEventType.TASK_EXECUTION_RESUMED,
                ExecutionResumedPayload(step_id=step.step_id, message="Approved — re-checking the next action."),
                task_id=ctx.task_id,
            )
            return ctx.result(ActionExecutionStatus.SUCCEEDED, "You approved the next action.", verified=True)
        if status == ApprovalStatus.REJECTED:
            return ctx.result(ActionExecutionStatus.FAILED, "You rejected the next action.", error_code="APPROVAL_REJECTED")
        if status == ApprovalStatus.EXPIRED:
            return ctx.result(
                ActionExecutionStatus.FAILED, "The approval request expired before a decision.", error_code="APPROVAL_EXPIRED"
            )
        return ctx.result(ActionExecutionStatus.FAILED, "Execution was stopped while waiting.", error_code="USER_CANCELLED")
