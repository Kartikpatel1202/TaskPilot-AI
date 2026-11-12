from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.browser.errors import BrowserError
from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.action import ExtractAction

from .base import error_result

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


MAX_SETTLE_CHECKS = 5


class ExtractHandler:
    action_type = "extract"

    async def execute(self, action: ExtractAction, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        retries = 0
        settle_checks = 0
        while True:
            try:
                await ctx.controller.ensure_allowed_page(ctx.session_id)
                data = await ctx.controller.extract(ctx.session_id, action.target_description, action.fields)
            except BrowserError as exc:
                # Reading is idempotent: bounded retry only.
                if retries >= ctx.max_retries or exc.code == "NAVIGATION_BLOCKED":
                    return error_result(ctx, exc, retry_count=retries)
                retries += 1
                continue
            # Content often renders after the page loads: re-read (bounded) until requested fields appear.
            nothing_found = data["item_count"] == 0 or all(
                all(v is None for v in item.values()) or set(data["missing_fields"]) >= set(action.fields)
                for item in data["items"]
            )
            if nothing_found and settle_checks < MAX_SETTLE_CHECKS:
                settle_checks += 1
                await asyncio.sleep(0.6)
                continue
            break

        count = data["item_count"]
        if count == 0:
            return ctx.result(
                ActionExecutionStatus.FAILED,
                f"Nothing readable was found for “{action.target_description}”.",
                error_code="EXTRACTION_EMPTY", extracted_data=data, retry_count=retries,
            )
        missing = data["missing_fields"]
        note = f" Not shown on the page: {', '.join(missing)}." if missing else ""
        return ctx.result(
            ActionExecutionStatus.SUCCEEDED,
            f"Read {count} item{'s' if count != 1 else ''} from “{action.target_description}”.{note}",
            extracted_data=data, verified=True, retry_count=retries,
        )
