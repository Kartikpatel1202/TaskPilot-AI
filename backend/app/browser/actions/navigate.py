from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from app.browser.bot_check import is_bot_check, wait_until_clear
from app.browser.errors import AuthenticationRequiredError, BrowserActionTimeoutError, BrowserError, SecurityCheckRequiredError
from app.execution.execution_result import ActionExecutionStatus, ActionResult
from app.schemas.action import NavigateAction
from app.schemas.browser import AuthenticationRequiredPayload, BrowserNavigationPayload
from app.schemas.telemetry import TelemetryEventType

from .base import error_result

if TYPE_CHECKING:
    from app.execution.execution_context import ExecutionContext


class NavigateHandler:
    action_type = "navigate"

    async def execute(self, action: NavigateAction, ctx: ExecutionContext) -> ActionResult:  # type: ignore[override]
        step = ctx.current_step
        assert step is not None
        await ctx.telemetry.emit(
            ctx.session_id, TelemetryEventType.BROWSER_NAVIGATION_STARTED,
            BrowserNavigationPayload(url=action.url.split("?")[0], step_id=step.step_id, message=action.purpose),
            task_id=ctx.task_id,
        )
        retries = 0
        while True:
            try:
                outcome = await ctx.controller.navigate(ctx.session_id, action.url)
                break
            except BrowserActionTimeoutError as exc:
                # Navigation is idempotent: one bounded retry after a timeout.
                if retries >= ctx.max_retries:
                    return error_result(ctx, exc, retry_count=retries)
                retries += 1
            except BrowserError as exc:
                return error_result(ctx, exc, retry_count=retries)

        page = await ctx.controller.page_for(ctx.session_id)
        if await is_bot_check(page):
            headed = not ctx.controller.manager.headless
            wait = ctx.controller.manager.human_check_wait_seconds if headed else min(10, ctx.controller.manager.human_check_wait_seconds)
            await ctx.telemetry.emit(
                ctx.session_id, TelemetryEventType.BROWSER_AUTHENTICATION_REQUIRED,
                AuthenticationRequiredPayload(
                    domain=outcome.domain, step_id=step.step_id, headless=not headed,
                    message=(f"{outcome.domain} is showing a security check. Please complete it yourself in the browser window — "
                             f"I'll wait up to {wait} seconds. I never solve these checks.") if headed else
                            f"{outcome.domain} is showing a security check; waiting briefly in case it finishes by itself.",
                ),
                task_id=ctx.task_id,
            )
            if not await wait_until_clear(page, timeout_seconds=wait):
                exc2 = SecurityCheckRequiredError(
                    f"{outcome.domain} is still showing a security check (CAPTCHA / bot check). TaskPilot never bypasses it"
                    + (" — complete it in the browser window, then run the plan again." if headed else
                       " — open the site yourself, or set BROWSER_HEADLESS=false in development to complete it in the window."))
                return ctx.result(ActionExecutionStatus.BLOCKED, exc2.message, error_code=exc2.code, retry_count=retries)
            with contextlib.suppress(Exception):
                await (await ctx.controller.manager.get_session(ctx.session_id)).refresh_page_info()
                outcome.title = await page.title()
        state = await ctx.controller.get_page_state(ctx.session_id)
        await ctx.telemetry.emit(
            ctx.session_id, TelemetryEventType.BROWSER_NAVIGATION_COMPLETED,
            BrowserNavigationPayload(
                url=outcome.url or "", domain=outcome.domain, title=outcome.title, step_id=step.step_id,
                message=f"Loaded {outcome.title or outcome.domain or 'the page'}.",
            ),
            task_id=ctx.task_id,
        )
        if state.auth_required:
            await ctx.telemetry.emit(
                ctx.session_id, TelemetryEventType.BROWSER_AUTHENTICATION_REQUIRED,
                AuthenticationRequiredPayload(
                    domain=outcome.domain, step_id=step.step_id, headless=ctx.controller.manager.headless,
                    message="Please sign in manually in the browser before continuing.",
                ),
                task_id=ctx.task_id,
            )
            exc = AuthenticationRequiredError(
                f"{outcome.domain} needs you to sign in. {state.auth_reason or ''} TaskPilot never enters credentials."
            )
            return ctx.result(ActionExecutionStatus.BLOCKED, exc.message, error_code=exc.code, retry_count=retries)
        return ctx.result(
            ActionExecutionStatus.SUCCEEDED,
            f"Opened {outcome.title or outcome.url} ({outcome.domain}).",
            verified=True, retry_count=retries,
            extracted_data={"url": outcome.url, "title": outcome.title, "http_status": outcome.status},
        )
