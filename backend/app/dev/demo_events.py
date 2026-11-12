"""DEVELOPMENT-ONLY simulation.

Generates clearly labelled demo telemetry so the dashboard can be exercised
before the planner (Phase 2) and browser controller (Phase 3) exist.

* Never touches a real website or browser.
* Every event carries `is_demo: true` and uses the normal event contracts.
* Clients cannot choose event types or inject arbitrary payloads — they can
  only ask for one of two fixed scenarios.
* The HTTP endpoints return 404 unless demo endpoints are enabled AND the app
  runs in development/test.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.event_manager import EventManager
from app.core.logging import get_logger
from app.schemas.approval import (
    ApprovalRequest,
    ApprovalStatus,
    DemoAcceptedResponse,
    DemoRequest,
    RiskLevel,
)
from app.schemas.task import Task, TaskState
from app.schemas.telemetry import (
    BrowserPreviewMode,
    BrowserPreviewPayload,
    LogLevel,
    TelemetryEventType,
)
from app.services.approval_service import ApprovalService
from app.services.task_service import TaskService, demo_task_request

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("demo")

DEMO_BANNER = "DEMO SIMULATION — no real browser or website is being used."


class DemoSimulator:
    def __init__(
        self,
        *,
        settings: Settings,
        events: EventManager,
        tasks: TaskService,
        approvals: ApprovalService,
    ) -> None:
        self._settings = settings
        self._events = events
        self._tasks = tasks
        self._approvals = approvals
        self._running: set[asyncio.Task[None]] = set()

    async def _pause(self) -> None:
        delay = self._settings.demo_event_delay_ms / 1000
        if delay:
            await asyncio.sleep(delay)

    async def _log(self, task: Task, level: LogLevel, message: str, **metadata: object) -> None:
        await self._events.log(
            task.session_id,
            level,
            message,
            task_id=task.task_id,
            source="demo",
            metadata={"demo": True, **metadata},
            is_demo=True,
        )

    async def _preview(self, task: Task, mode: BrowserPreviewMode, message: str) -> None:
        await self._events.emit(
            task.session_id,
            TelemetryEventType.BROWSER_PREVIEW,
            BrowserPreviewPayload(mode=mode, message=message, is_demo=True),
            task_id=task.task_id,
        )

    # ------------------------------------------------------------------ telemetry scenario

    async def start_telemetry(self, request: DemoRequest) -> Task:
        task = await self._tasks.create_task(
            demo_task_request(request.session_id, "[DEMO] Simulated walkthrough — search for Python tutorials"),
            is_demo=True,
        )
        job = asyncio.create_task(self._run_telemetry(task), name=f"demo-telemetry-{task.task_id}")
        self._running.add(job)
        job.add_done_callback(self._running.discard)
        return task

    async def _run_telemetry(self, task: Task) -> None:
        try:
            await self._log(task, LogLevel.INFO, DEMO_BANNER)
            await self._pause()
            await self._tasks.transition(task.task_id, TaskState.PLANNING, reason="Demo: simulated planning")
            await self._log(
                task,
                LogLevel.DEBUG,
                "Demo planner produced 3 illustrative steps.",
                steps=["open site", "search", "review results"],
            )
            await self._pause()
            await self._tasks.transition(task.task_id, TaskState.EXECUTING, reason="Demo: simulated execution")
            await self._preview(
                task,
                BrowserPreviewMode.PLACEHOLDER,
                "Demo placeholder — no real browser session is running.",
            )
            await self._pause()
            await self._log(task, LogLevel.INFO, "Demo step 1/3 (simulated): open site.", step=1)
            await self._pause()
            await self._log(
                task, LogLevel.WARNING, "Demo step 2/3 (simulated): illustrative slow-response warning.", step=2
            )
            await self._pause()
            await self._log(task, LogLevel.INFO, "Demo step 3/3 (simulated): review results.", step=3)
            await self._pause()
            await self._log(task, LogLevel.SUCCESS, "Demo simulation finished. No real actions were performed.")
            await self._tasks.transition(
                task.task_id,
                TaskState.COMPLETED,
                reason="Demo simulation completed — no real actions performed.",
            )
            await self._preview(task, BrowserPreviewMode.DISCONNECTED, "Browser not connected.")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("demo.telemetry_failed", extra={"task_id": str(task.task_id)})

    # ------------------------------------------------------------------ approval scenario

    async def create_approval(self, request: DemoRequest) -> ApprovalRequest:
        task = await self._tasks.create_task(
            demo_task_request(request.session_id, "[DEMO] Simulated grocery checkout requiring approval"),
            is_demo=True,
        )
        await self._log(task, LogLevel.INFO, DEMO_BANNER)
        for state in (TaskState.PLANNING, TaskState.EXECUTING, TaskState.WAITING_APPROVAL):
            await self._tasks.transition(task.task_id, state, reason="Demo: simulated transition")
        return await self._approvals.create(
            task_id=task.task_id,
            session_id=task.session_id,
            action_summary="Place grocery order (simulated)",
            domain="example-grocer.test",
            reason="Placing an order may result in a purchase, so explicit human approval is required.",
            risk_level=RiskLevel.HIGH,
            estimated_impact="Illustrative only: ₹850 across 4 items. No order will be placed.",
            ttl_seconds=self._settings.demo_approval_ttl_seconds,
            is_demo=True,
        )

    async def on_approval_resolved(self, approval: ApprovalRequest) -> None:
        """Continue the simulated task after a demo decision. Executes nothing real."""
        if not approval.is_demo:
            return
        try:
            task = await self._tasks.get_task(approval.task_id)
        except LookupError:
            return
        if task.state != TaskState.WAITING_APPROVAL:
            return
        await self._tasks.transition(task.task_id, TaskState.EXECUTING, reason="Demo: approval resolved")
        if approval.status == ApprovalStatus.APPROVED:
            await self._log(task, LogLevel.SUCCESS, "Demo approval recorded. No real action was executed.")
            await self._tasks.transition(
                task.task_id, TaskState.COMPLETED, reason="Demo approval flow completed — nothing was purchased."
            )
        else:
            if approval.status == ApprovalStatus.EXPIRED:
                code, reason = "APPROVAL_EXPIRED", "Demo approval expired before a decision was made."
            else:
                code, reason = "APPROVAL_REJECTED", "Demo approval rejected by the user."
            await self._log(task, LogLevel.WARNING, f"{reason} Task stopped; nothing was executed.")
            await self._tasks.transition(task.task_id, TaskState.FAILED, reason=reason, error_code=code)

    async def shutdown(self) -> None:
        for job in list(self._running):
            job.cancel()
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)


# ---------------------------------------------------------------------- HTTP routes


def require_demo_enabled(request: Request) -> DemoSimulator:
    container = request.app.state.container
    if not container.settings.demo_endpoints_active:
        # Indistinguishable from a route that does not exist.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return container.demo


router = APIRouter(prefix="/dev/demo", tags=["development (demo only)"])


@router.post(
    "/telemetry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DemoAcceptedResponse,
    summary="Start a simulated, clearly labelled telemetry stream (development only)",
)
async def demo_telemetry(
    body: DemoRequest, simulator: DemoSimulator = Depends(require_demo_enabled)
) -> DemoAcceptedResponse:
    task = await simulator.start_telemetry(body)
    return DemoAcceptedResponse(
        accepted=True, message="Demo telemetry started. No real actions will be performed.", task_id=task.task_id
    )


@router.post(
    "/approval",
    status_code=status.HTTP_201_CREATED,
    response_model=ApprovalRequest,
    summary="Create a sample approval request (development only)",
)
async def demo_approval(
    body: DemoRequest, simulator: DemoSimulator = Depends(require_demo_enabled)
) -> ApprovalRequest:
    return await simulator.create_approval(body)
