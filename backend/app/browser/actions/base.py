"""Common interface for browser action handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.browser.errors import BrowserError
from app.execution.execution_result import ActionExecutionStatus, ActionResult

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext
    from app.schemas.action import SupportedAction


class BrowserActionHandler(Protocol):
    action_type: str

    async def execute(self, action: SupportedAction, ctx: ExecutionContext) -> ActionResult: ...


def error_result(ctx: ExecutionContext, exc: BrowserError, *, retry_count: int = 0) -> ActionResult:
    """Translate a domain error into a safe step result (no traceback, no secrets)."""
    status = ActionExecutionStatus.BLOCKED if exc.code in ("SENSITIVE_ACTION_BLOCKED", "NAVIGATION_BLOCKED") else (
        ActionExecutionStatus.FAILED
    )
    return ctx.result(status, exc.message, error_code=exc.code, retry_count=retry_count)
