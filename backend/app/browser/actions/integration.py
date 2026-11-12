"""Phase 5 integration plan steps -> IntegrationManager (trusted, deterministic integration code)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.execution.execution_result import ActionExecutionStatus, ActionResult

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


class IntegrationHandler:
    def __init__(self, action_type: str) -> None:
        self.action_type = action_type

    async def execute(self, action: Any, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        if ctx.integrations is None:
            return ctx.result(ActionExecutionStatus.BLOCKED, "Multi-domain integrations are not enabled on this server.",
                              error_code="CAPABILITY_DISABLED")
        return await ctx.integrations.run_step(ctx, action)
