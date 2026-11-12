"""Execution manager: validates Run Plan requests, queues jobs, runs them, finalises state.

Execution only ever starts from an explicit, validated `POST /tasks/{id}/execute`.
Planning never launches a browser.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.agent.plan_store import PlanStore
from app.agent.validation import PlanValidator
from app.browser.controller import BrowserController
from app.browser.errors import BrowserError
from app.browser.executor import PlanExecutor
from app.browser.manager import BrowserManager
from app.browser.stream_manager import BrowserStreamManager
from app.config import Settings
from app.schemas.approval import RiskLevel
from app.core.execution_events import ExecutionEvents
from app.core.logging import get_logger
from app.core.persona import persona_message
from app.core.state_machine import is_terminal
from app.execution.approval_coordinator import ApprovalCoordinator
from app.execution.execution_context import ExecutionContext
from app.execution.execution_queue import (
    ExecutionAlreadyActiveError,
    ExecutionJob,
    ExecutionQueue,
    ExecutionQueueClosedError,
    ExecutionQueueFullError,
)
from app.execution.execution_result import ExecutionStatus, ExecutionSummary
from app.policies.browser_action_policy import BrowserActionPolicy
from app.schemas.browser import BrowserSessionStatus
from app.schemas.common import utc_now
from app.schemas.execution import ExecutionFinishedPayload, StopTaskResponse
from app.schemas.intent import IntentType
from app.schemas.plan import PlanStatus
from app.schemas.task import TaskState
from app.schemas.telemetry import AgentResponsePayload, TelemetryEventType
from app.services.task_service import TaskService

logger = get_logger("execution.manager")


class ExecutionError(Exception):
    code = "EXECUTION_ERROR"
    status_code = 409

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ExecutionUnavailableError(ExecutionError):
    code = "BROWSER_UNAVAILABLE"
    status_code = 503


class ExecutionSessionMismatchError(ExecutionError):
    code = "TASK_SESSION_MISMATCH"
    status_code = 403


class ExecutionPlanNotFoundError(ExecutionError):
    code = "PLAN_NOT_FOUND"
    status_code = 404


class ExecutionPlanNotReadyError(ExecutionError):
    code = "PLAN_NOT_READY"


class ExecutionAutoRunRefusedError(ExecutionError):
    code = "AUTO_RUN_NOT_ALLOWED"


class ExecutionAlreadyStartedError(ExecutionError):
    code = "EXECUTION_ALREADY_STARTED"


class ExecutionSessionBusyError(ExecutionError):
    code = "BROWSER_SESSION_BUSY"


class ExecutionQueueBusyError(ExecutionError):
    code = "EXECUTION_QUEUE_FULL"
    status_code = 503


class ExecutionNotActiveError(ExecutionError):
    code = "EXECUTION_NOT_ACTIVE"


@dataclass
class ExecutionRecord:
    task_id: UUID
    session_id: UUID
    status: ExecutionStatus = ExecutionStatus.QUEUED
    queued_at: datetime = field(default_factory=utc_now)
    ctx: ExecutionContext | None = None
    summary: ExecutionSummary | None = None


_FINAL_STATE = {
    ExecutionStatus.COMPLETED: TaskState.COMPLETED,
    ExecutionStatus.FAILED: TaskState.FAILED,
    ExecutionStatus.CANCELLED: TaskState.CANCELLED,
}
_FINAL_EVENT = {
    ExecutionStatus.COMPLETED: TelemetryEventType.TASK_EXECUTION_COMPLETED,
    ExecutionStatus.FAILED: TelemetryEventType.TASK_EXECUTION_FAILED,
    ExecutionStatus.CANCELLED: TelemetryEventType.TASK_EXECUTION_CANCELLED,
}


class ExecutionManager:
    def __init__(
        self,
        *,
        settings: Settings,
        tasks: TaskService,
        store: PlanStore,
        validator: PlanValidator,
        browser: BrowserManager,
        controller: BrowserController,
        stream: BrowserStreamManager,
        telemetry: ExecutionEvents,
        approvals: ApprovalCoordinator,
    ) -> None:
        self._settings = settings
        self._tasks = tasks
        self._store = store
        self._validator = validator
        self._browser = browser
        self._controller = controller
        self._stream = stream
        self._telemetry = telemetry
        self._approvals = approvals
        self._policy = BrowserActionPolicy()
        self.commerce: object | None = None  # Phase 4 CommerceManager, set by the container
        self.integrations: object | None = None  # Phase 5 IntegrationManager, set by the container
        self.journal: object | None = None  # Phase 6 ExecutionJournal, set by the container
        self.recovery: object | None = None  # Phase 6 RecoveryEngine, set by the container
        self.session_locks: object | None = None  # Phase 6 distributed per-session lock (Redis), optional
        step_timeout = (settings.browser_navigation_timeout_ms + 2 * settings.browser_action_timeout_ms) / 1000 + 10
        self._executor = PlanExecutor(stream=stream, step_timeout_seconds=step_timeout)
        self._records: OrderedDict[UUID, ExecutionRecord] = OrderedDict()
        self.preferences: Any = None  # PreferencesService (voice auto-run setting)
        self.queue = ExecutionQueue(
            self._run,
            concurrency=settings.execution_concurrency,
            maxsize=settings.execution_queue_size,
            on_abandoned=self._abandoned,
        )

    # ---------------------------------------------------------------- lifecycle

    @property
    def executor(self) -> PlanExecutor:
        return self._executor

    async def start(self) -> None:
        await self.queue.start()

    async def stop(self) -> None:
        for record in self._records.values():
            if record.ctx is not None and not record.ctx.cancelled:
                record.ctx.cancel_reason = "The server is shutting down."
                record.ctx.cancel_event.set()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._drain_running(), timeout=10)
        await self.queue.stop()

    async def _drain_running(self) -> None:
        while any(self.queue.is_running(r.task_id) for r in self._records.values()):
            await asyncio.sleep(0.1)

    @property
    def available(self) -> bool:
        return self._settings.agent_browser_execution_enabled and self._browser.installation_available()

    # ---------------------------------------------------------------- requests

    async def submit(self, task_id: UUID, session_id: UUID, *, trigger: str = "run_plan_click") -> ExecutionRecord:
        if not self._settings.agent_browser_execution_enabled:
            raise ExecutionUnavailableError("Browser execution is disabled (AGENT_BROWSER_EXECUTION_ENABLED=false).")
        if not self._browser.installation_available():
            raise ExecutionUnavailableError(self._browser.unavailable_reason or "The browser is unavailable.")
        task = await self._tasks.get_task(task_id)
        if task.session_id != session_id:
            raise ExecutionSessionMismatchError("This task belongs to a different session.")
        if self.queue.is_active(task_id) or (task.state != TaskState.PLANNED and task_id in self._records):
            raise ExecutionAlreadyStartedError("This plan has already been run.")
        record_plan = self._store.get(task_id)
        plan = record_plan.plan if record_plan else None
        if plan is None:
            raise ExecutionPlanNotFoundError("No plan exists for this task.")
        if task.state != TaskState.PLANNED:
            raise ExecutionPlanNotReadyError(f"Only PLANNED tasks can run (this task is {task.state.value}).")
        if plan.status != PlanStatus.READY or not plan.steps or plan.intent == IntentType.GENERAL_CHAT:
            raise ExecutionPlanNotReadyError("This plan has no browser steps to run.")
        if trigger == "voice_auto":
            await self._check_auto_run(task_id, plan)
        report = self._validator.validate(plan, task_id=task_id, session_id=session_id)  # runtime re-validation
        if not report.ok:
            raise ExecutionPlanNotReadyError("The plan no longer passes validation: " + "; ".join(report.errors[:3]))
        if self.queue.session_busy(session_id):
            raise ExecutionSessionBusyError("Another plan is already running in this session's browser.")
        if self.queue.is_full:
            raise ExecutionQueueBusyError("The execution queue is full. Please try again shortly.")
        record = ExecutionRecord(task_id=task_id, session_id=session_id)
        try:
            if hasattr(self.queue, "enqueue"):  # Phase 6 Redis-backed durable dispatch
                await self.queue.enqueue(ExecutionJob(task_id, session_id))  # type: ignore[attr-defined]
            else:
                self.queue.submit(ExecutionJob(task_id, session_id))
        except ExecutionQueueFullError as exc:
            raise ExecutionQueueBusyError("The execution queue is full. Please try again shortly.") from exc
        except ExecutionAlreadyActiveError as exc:
            raise ExecutionSessionBusyError(str(exc)) from exc
        except ExecutionQueueClosedError as exc:
            raise ExecutionUnavailableError(str(exc)) from exc
        # With the Redis queue a worker may already have registered (and finished) this job; keep its record.
        record = self._records.setdefault(task_id, record)
        while len(self._records) > 500:
            self._records.popitem(last=False)
        logger.info("execution.queued", extra={"task_id": str(task_id)})
        return record

    async def _check_auto_run(self, task_id: UUID, plan: Any) -> None:
        """Voice auto-run starts only low-risk plans (open, search, add to cart) and only when the user enabled it.
        Anything that orders, pays, sends, submits, creates, downloads or deletes waits for an explicit Run Plan
        click — and runtime approvals still apply to every sensitive step in any case."""
        prefs = None
        if self.preferences is not None:
            owner = self._tasks.owner_of(task_id) if hasattr(self._tasks, "owner_of") else None
            prefs = await self.preferences.get(owner)
        if prefs is not None and not prefs.voice_auto_execute:
            raise ExecutionAutoRunRefusedError("Voice auto-run is turned off in Settings. Press Run Plan to start.")
        sensitive = [s for s in plan.steps if s.requires_approval or s.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)]
        if sensitive or plan.requires_human_approval:
            raise ExecutionAutoRunRefusedError(
                "This plan includes a sensitive step (for example placing an order, sending or creating something), "
                "so it does not start automatically. Review it and press Run Plan — I will still ask before that step.")

    async def stop_task(self, task_id: UUID, session_id: UUID, reason: str) -> StopTaskResponse:
        task = await self._tasks.get_task(task_id)
        if task.session_id != session_id:
            raise ExecutionSessionMismatchError("This task belongs to a different session.")
        record = self._records.get(task_id)
        if record is None or record.status not in (ExecutionStatus.QUEUED, ExecutionStatus.EXECUTING, ExecutionStatus.WAITING_APPROVAL):
            raise ExecutionNotActiveError("This task has no active execution.")
        if record.ctx is None and self.queue.withdraw_queued(task_id):
            return StopTaskResponse(task_id=task_id, status="CANCELLED", message="Removed from the queue before it started.")
        if record.ctx is not None:
            record.ctx.cancel_reason = reason
            record.ctx.cancel_event.set()
        return StopTaskResponse(task_id=task_id, status="STOPPING", message="Stopping after the current browser action.")

    def summary(self, task_id: UUID) -> ExecutionSummary | None:
        record = self._records.get(task_id)
        return record.summary if record else None

    def active_task_for(self, session_id: UUID) -> UUID | None:
        for record in reversed(self._records.values()):
            if record.session_id == session_id and record.status in (ExecutionStatus.EXECUTING, ExecutionStatus.WAITING_APPROVAL):
                return record.task_id
        return None

    # ---------------------------------------------------------------- worker

    async def _run(self, job: ExecutionJob) -> None:
        record = self._records[job.task_id]
        store_record = self._store.get(job.task_id)
        assert store_record is not None and store_record.plan is not None
        plan = store_record.plan
        record.status = ExecutionStatus.EXECUTING
        try:
            session = await self._browser.get_or_create_session(job.session_id)
        except BrowserError as exc:
            summary = ExecutionSummary(
                task_id=job.task_id, session_id=job.session_id, plan_id=plan.plan_id, status=ExecutionStatus.FAILED,
                total_steps=len(plan.steps), message=exc.message, error_code=exc.code, started_at=utc_now(), finished_at=utc_now(),
            )
            await self._finalize(record, summary, plan.language)
            return

        ctx = ExecutionContext(
            task_id=job.task_id, session_id=job.session_id, plan=plan, controller=self._controller, policy=self._policy,
            telemetry=self._telemetry, approvals=self._approvals, tasks=self._tasks,
            approval_ttl_seconds=self._settings.execution_approval_ttl_seconds,
            max_retries=self._settings.browser_action_max_retries,
            commerce=self.commerce,
            integrations=self.integrations,
            journal=self.journal,
            recovery=self.recovery,
            user_id=self._tasks.owner_of(job.task_id),
        )
        record.ctx = ctx
        summary: ExecutionSummary | None = None
        locks = self.session_locks
        if locks is not None:  # Phase 6: also exclusive across processes (Redis lock with ownership token)
            from app.queue.locks import LockNotAcquiredError

            try:
                async with locks.hold(job.session_id):  # type: ignore[attr-defined]
                    await self._run_locked(job, record, plan, session, ctx)
            except LockNotAcquiredError as exc:
                summary = ExecutionSummary(
                    task_id=job.task_id, session_id=job.session_id, plan_id=plan.plan_id, status=ExecutionStatus.FAILED,
                    total_steps=len(plan.steps), message=str(exc), error_code="BROWSER_SESSION_BUSY", started_at=utc_now(),
                    finished_at=utc_now())
                await self._finalize(record, summary, plan.language)
            return
        await self._run_locked(job, record, plan, session, ctx)

    async def _run_locked(self, job: ExecutionJob, record: ExecutionRecord, plan: Any, session: Any, ctx: ExecutionContext) -> None:
        summary: ExecutionSummary | None = None
        async with session.lock:  # one execution (and one action) at a time per browser session
            session.active_task_id = job.task_id
            session.status = BrowserSessionStatus.BUSY
            try:
                await self._tasks.transition(job.task_id, TaskState.EXECUTING, reason="Run Plan clicked — executing in Chromium")
                summary = await self._executor.run(ctx, session)
            except asyncio.CancelledError:
                summary = ExecutionSummary(
                    task_id=job.task_id, session_id=job.session_id, plan_id=plan.plan_id, status=ExecutionStatus.CANCELLED,
                    total_steps=len(plan.steps), results=list(ctx.results.values()),
                    message="Stopped because the server is shutting down.", error_code="SERVER_SHUTDOWN", finished_at=utc_now(),
                )
                await asyncio.shield(self._finalize(record, summary, plan.language))
                raise
            except Exception:
                logger.exception("execution.run_crashed", extra={"task_id": str(job.task_id)})
                summary = ExecutionSummary(
                    task_id=job.task_id, session_id=job.session_id, plan_id=plan.plan_id, status=ExecutionStatus.FAILED,
                    total_steps=len(plan.steps), results=list(ctx.results.values()),
                    message="Execution failed unexpectedly.", error_code="EXECUTION_WORKER_ERROR", finished_at=utc_now(),
                )
            finally:
                session.active_task_id = None
                if session.is_active:
                    session.status = BrowserSessionStatus.READY
        assert summary is not None
        await self._finalize(record, summary, plan.language)

    async def _finalize(self, record: ExecutionRecord, summary: ExecutionSummary, language: str) -> None:
        record.summary = summary
        record.status = summary.status
        if self.journal is not None and self._tasks.persistence is not None:
            p = self._tasks.persistence
            with contextlib.suppress(Exception):
                task_now = await self._tasks.get_task(record.task_id)
                await p.best_effort(p.tasks.upsert(task_now, error_code=summary.error_code, execution_status=summary.status.value),
                                    "task.execution_status")
        if self.integrations is not None:
            with contextlib.suppress(Exception):
                await self.integrations.finalize(record.task_id, summary.status.value)  # type: ignore[attr-defined]
        task = await self._tasks.get_task(record.task_id)
        if not is_terminal(task.state):
            target = _FINAL_STATE[summary.status]
            reason = summary.message or summary.status.value.title()
            with contextlib.suppress(Exception):
                await self._tasks.transition(record.task_id, target, reason=reason, error_code=summary.error_code)
        from app.execution.execution_result import ActionExecutionStatus as S

        await self._telemetry.emit(
            record.session_id, _FINAL_EVENT[summary.status],
            ExecutionFinishedPayload(
                status=summary.status, total_steps=summary.total_steps,
                succeeded_steps=summary.count(S.SUCCEEDED), failed_steps=summary.count(S.FAILED),
                blocked_steps=summary.count(S.BLOCKED), skipped_steps=summary.count(S.SKIPPED),
                message=summary.message or "", error_code=summary.error_code,
            ),
            task_id=record.task_id,
        )
        kind = {"COMPLETED": "execution_completed", "CANCELLED": "execution_cancelled"}.get(summary.status.value, "execution_failed")
        if kind == "execution_completed" and self.commerce is not None:
            kind = self.commerce.persona_kind(record.task_id) or kind  # type: ignore[attr-defined]
        if self.integrations is not None:
            kind = self.integrations.persona_kind(record.task_id, summary.status.value) or kind  # type: ignore[attr-defined]
        lang = language if language in ("en", "hi", "hinglish") else "en"
        await self._telemetry.emit(
            record.session_id, TelemetryEventType.AGENT_RESPONSE_GENERATED,
            AgentResponsePayload(message=persona_message(kind, lang), language=lang, kind="execution"),  # type: ignore[arg-type]
            task_id=record.task_id,
        )
        logger.info("execution.finished", extra={"task_id": str(record.task_id), "status": summary.status.value})

    # ---------------------------------------------------------------- Phase 6 Redis dispatch hooks

    async def run_job(self, job: ExecutionJob) -> None:
        await self._run(job)

    async def prepare_job(self, job: ExecutionJob) -> bool:
        """A durable job may outlive the process that queued it: run it only if the task is still PLANNED."""
        try:
            task = await self._tasks.get_task(job.task_id)
        except LookupError:
            return False
        store_record = self._store.get(job.task_id)
        if task.state != TaskState.PLANNED or store_record is None or store_record.plan is None:
            return False
        self._records.setdefault(job.task_id, ExecutionRecord(task_id=job.task_id, session_id=job.session_id))
        return True

    async def abandon_job(self, job: ExecutionJob, code: str) -> None:
        await self._abandoned(job, code)

    async def _abandoned(self, job: ExecutionJob, code: str) -> None:
        """A queued job that never ran: the task stays PLANNED (nothing happened in the browser)."""
        record = self._records.get(job.task_id)
        if record is None or record.ctx is not None:
            return
        record.status = ExecutionStatus.CANCELLED
        record.summary = ExecutionSummary(
            task_id=job.task_id, session_id=job.session_id, plan_id=(self._store.get(job.task_id).plan.plan_id),  # type: ignore[union-attr]
            status=ExecutionStatus.CANCELLED, total_steps=0, message="Removed from the queue before it started.",
            error_code=code, finished_at=utc_now(),
        )
        self._records.pop(job.task_id, None)
        await self._telemetry.emit(
            job.session_id, TelemetryEventType.TASK_EXECUTION_CANCELLED,
            ExecutionFinishedPayload(
                status=ExecutionStatus.CANCELLED, total_steps=0, succeeded_steps=0, failed_steps=0, blocked_steps=0,
                skipped_steps=0, message="Removed from the queue before it started; nothing ran.", error_code=code,
            ),
            task_id=job.task_id,
        )
