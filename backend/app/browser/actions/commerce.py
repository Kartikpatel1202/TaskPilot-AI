"""`commerce` plan steps -> CommerceManager (trusted, deterministic commerce code)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.commerce import CommerceAction

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


class CommerceHandler:
    action_type = "commerce"

    async def execute(self, action: CommerceAction, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        if ctx.commerce is None:
            return ctx.result(ActionExecutionStatus.BLOCKED, "Commerce automation is not enabled on this server.",
                              error_code="COMMERCE_PLATFORM_UNSUPPORTED")
        return await ctx.commerce.run_step(ctx, action)
