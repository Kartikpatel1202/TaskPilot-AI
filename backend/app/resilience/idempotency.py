"""Execution journal + idempotency guard around every plan step.

Lifecycle per (task, plan, step, version):  PREPARED -> RUNNING -> SUCCEEDED | FAILED | BLOCKED | CANCELLED | UNKNOWN

- A second delivery of an already SUCCEEDED step is not executed again (its success is reported).
- A step found RUNNING/UNKNOWN (an earlier attempt crashed mid-action) is NOT repeated if it can
  mutate external state (cart, order, draft, event, clicks): it fails with ACTION_STATE_UNKNOWN and
  asks for reconciliation. Read-only steps may run again.
- A mutating step that times out or is interrupted mid-flight is recorded UNKNOWN, never FAILED,
  because the website may have applied it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.database.models import ActionLifecycle
from app.database.repositories.execution_repository import idempotency_key
from app.execution.execution_result import ActionExecutionStatus, ActionResult

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext
    from app.schemas.plan import PlannedAction

MUTATING_COMMERCE = {"search_and_add", "place_order"}
# Mutations whose outcome the handler can establish from the website BEFORE acting again:
#   gmail draft -> looks for the draft in Drafts; calendar event -> identical-event check (+ fresh approval);
#   commerce add -> cart reconciliation adds only the missing quantity. COD order submission is NOT here.
RECONCILABLE = {"gmail_create_draft", "calendar_create_event", "commerce:search_and_add"}
UNCERTAIN_CODES = {"ACTION_TIMEOUT", "USER_CANCELLED", "STEP_FAILED", "CALENDAR_EVENT_STATUS_UNKNOWN", "GMAIL_DRAFT_SAVE_UNKNOWN"}
_STATUS = {
    ActionExecutionStatus.SUCCEEDED: ActionLifecycle.SUCCEEDED,
    ActionExecutionStatus.FAILED: ActionLifecycle.FAILED,
    ActionExecutionStatus.BLOCKED: ActionLifecycle.BLOCKED,
    ActionExecutionStatus.SKIPPED: ActionLifecycle.CANCELLED,
}


def is_mutating(action: Any) -> bool:
    kind = getattr(action, "type", "")
    if kind == "commerce":
        return getattr(action, "operation", "") in MUTATING_COMMERCE
    return kind in ("click", "gmail_create_draft", "calendar_create_event")


class ExecutionJournal:
    def __init__(self, persistence: Any, worker_id: str) -> None:
        self._p = persistence
        self.worker_id = worker_id

    def key(self, ctx: ExecutionContext, step: PlannedAction) -> str:
        return idempotency_key(ctx.task_id, ctx.plan.plan_id, step.step_id, 1)

    async def begin(self, ctx: ExecutionContext, step: PlannedAction) -> ActionResult | None:
        """None = go ahead. An ActionResult = do NOT run the action (already done / uncertain)."""
        key = self.key(ctx, step)
        mutating = is_mutating(step.action)
        row, created = await self._p.journal.prepare(key=key, task_id=ctx.task_id, plan_id=ctx.plan.plan_id, step_id=step.step_id,
                                                     order=step.order, action_type=step.action.type, mutating=mutating,
                                                     worker_id=self.worker_id)
        if created:
            await self._p.journal.mark(key, ActionLifecycle.RUNNING)
            return None
        state = row.lifecycle
        if state == ActionLifecycle.SUCCEEDED.value:
            return ctx.result(ActionExecutionStatus.SUCCEEDED, "Already completed by an earlier attempt — not repeated.", verified=True)
        kind = step.action.type if step.action.type != "commerce" else f"commerce:{getattr(step.action, 'operation', '')}"
        if mutating and state in (ActionLifecycle.RUNNING.value, ActionLifecycle.UNKNOWN.value) and kind in RECONCILABLE:
            ctx.reconciling = True  # the handler must inspect the website before doing anything again
            await self._p.journal.mark(key, ActionLifecycle.RUNNING, bump_attempt=True)
            return None
        if mutating and state in (ActionLifecycle.RUNNING.value, ActionLifecycle.UNKNOWN.value):
            await self._p.journal.mark(key, ActionLifecycle.UNKNOWN, error_code="ACTION_STATE_UNKNOWN")
            return ctx.result(ActionExecutionStatus.FAILED,
                              "An earlier attempt of this step was interrupted and may already have changed the website. "
                              "It was not repeated — please check the site before running it again.", error_code="ACTION_STATE_UNKNOWN")
        await self._p.journal.mark(key, ActionLifecycle.RUNNING, bump_attempt=True)
        return None

    async def finish(self, ctx: ExecutionContext, step: PlannedAction, result: ActionResult) -> None:
        ctx.reconciling = False
        lifecycle = _STATUS.get(result.status, ActionLifecycle.FAILED)
        if result.error_code == "USER_CANCELLED":
            lifecycle = ActionLifecycle.CANCELLED
        if is_mutating(step.action) and result.status == ActionExecutionStatus.FAILED and result.error_code in UNCERTAIN_CODES:
            lifecycle = ActionLifecycle.UNKNOWN
        summary = {"status": result.status.value, "verified": result.verified, "message": result.message[:300]}
        await self._p.best_effort(self._p.journal.mark(self.key(ctx, step), lifecycle, error_code=result.error_code, result=summary),
                                  "journal.finish")
