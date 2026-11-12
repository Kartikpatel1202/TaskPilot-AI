from __future__ import annotations

from typing import TYPE_CHECKING

from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.action import StopAction

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


class StopHandler:
    """A planned `stop` ends the plan on purpose; the browser stays open for inspection."""

    action_type = "stop"

    async def execute(self, action: StopAction, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        return ctx.result(ActionExecutionStatus.SUCCEEDED, f"Plan ended as planned: {action.reason}", verified=True)
