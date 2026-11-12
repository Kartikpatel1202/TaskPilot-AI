"""Planning service: the API-facing entry point for Phase 2 agent planning.

Accepts commands and clarifications, enqueues bounded background planning jobs,
serves plans, and reports agent status. LLM work never runs inside a request.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from app.observability.tracing import span
from app.agent.memory import MemoryManager
from app.agent.orchestrator import AgentOrchestrator, PlanningAborted
from app.agent.plan_store import PlanStore
from app.agent.providers.base import LLMProvider, ProviderError
from app.agent.validation import PlanValidationError
from app.config import Settings
from app.core.logging import get_logger
from app.core.persona import ASSISTANT_NAME, detect_language
from app.core.planner_queue import (
    DuplicateJobError,
    PlannerQueue,
    PlannerQueueClosedError,
    PlannerQueueFullError,
    PlanningJob,
)
from app.schemas.agent import AgentStatusResponse, ClarificationAcceptedResponse, ClarificationRequest
from app.schemas.plan import TaskPlan
from app.schemas.task import CreateTaskRequest, Task, TaskState
from app.services.task_service import TaskService

logger = get_logger("planning")

_FAILURE_MESSAGES = {
    "PLANNING_TIMEOUT": "Planning took too long and was stopped. Please try again.",
    "PLANNING_CANCELLED": "Planning was cancelled because the server is shutting down.",
    "PLANNER_QUEUE_FULL": "Kamlesh Bhai is busy with other plans right now. Please try again shortly.",
    "INTERNAL_PLANNING_ERROR": "Planning failed because of an internal error. Please try again.",
}


class PlannerBusyError(RuntimeError):
    pass


class TaskSessionMismatchError(PermissionError):
    pass


class TaskNotAwaitingClarificationError(RuntimeError):
    def __init__(self, state: TaskState) -> None:
        self.state = state
        super().__init__(f"Task is {state.value}, not waiting for clarification.")


class PlanNotReadyError(RuntimeError):
    def __init__(self, state: TaskState) -> None:
        self.state = state
        super().__init__(f"Planning has not finished (task is {state.value}).")


class PlanNotFoundError(LookupError):
    pass


class PlanningService:
    def __init__(
        self,
        *,
        settings: Settings,
        tasks: TaskService,
        orchestrator: AgentOrchestrator,
        store: PlanStore,
        memory: MemoryManager,
        provider: LLMProvider,
    ) -> None:
        self._settings = settings
        self._tasks = tasks
        self._orchestrator = orchestrator
        self._store = store
        self._memory = memory
        self._provider = provider
        timeout = settings.agent_request_timeout_seconds + 5
        # Classifier + planner, each with retries and backoff, plus slack.
        job_timeout = 2 * timeout * (settings.agent_max_retries + 1) + 10 * (settings.agent_max_retries + 1)
        self.queue = PlannerQueue(
            self._run_job,
            concurrency=settings.planner_concurrency,
            maxsize=settings.planner_queue_size,
            job_timeout=job_timeout,
            on_failure=self._job_failed,
        )

    @property
    def enabled(self) -> bool:
        return self._settings.agent_planning_enabled

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self.enabled:
            await self.queue.start()

    async def stop(self) -> None:
        await self.queue.stop()
        await self._provider.aclose()

    # ---------------------------------------------------------------- commands

    async def accept_command(self, request: CreateTaskRequest) -> Task:
        if not self.enabled:
            return await self._tasks.create_task(request)
        if self.queue.is_full:
            raise PlannerBusyError(_FAILURE_MESSAGES["PLANNER_QUEUE_FULL"])

        task = await self._tasks.create_task(request)
        self._store.create(task.task_id, task.session_id, request.command)
        try:
            self.queue.submit(PlanningJob(task.task_id, task.session_id, "new"))
        except (PlannerQueueFullError, PlannerQueueClosedError, DuplicateJobError) as exc:
            # Never leave an "accepted" task that will not be planned.
            await self._fail_task(task.task_id, "PLANNER_QUEUE_FULL")
            raise PlannerBusyError(_FAILURE_MESSAGES["PLANNER_QUEUE_FULL"]) from exc
        return task

    async def submit_clarification(self, task_id: UUID, request: ClarificationRequest) -> ClarificationAcceptedResponse:
        task = await self._tasks.get_task(task_id)
        if task.session_id != request.session_id:
            raise TaskSessionMismatchError("Task does not belong to this session.")
        if task.state != TaskState.NEEDS_CLARIFICATION:
            raise TaskNotAwaitingClarificationError(task.state)
        record = self._store.get(task_id)
        if record is None:
            raise TaskNotAwaitingClarificationError(task.state)
        if self.queue.is_full:
            raise PlannerBusyError(_FAILURE_MESSAGES["PLANNER_QUEUE_FULL"])

        # The transition is the atomic gate: a concurrent second clarification fails here.
        await self._tasks.transition(task_id, TaskState.PLANNING, reason="Clarification received")
        self._orchestrator.record_clarification(record, request.message)
        try:
            self.queue.submit(PlanningJob(task_id, task.session_id, "clarification"))
        except (PlannerQueueFullError, PlannerQueueClosedError, DuplicateJobError) as exc:
            await self._fail_task(task_id, "PLANNER_QUEUE_FULL")
            raise PlannerBusyError(_FAILURE_MESSAGES["PLANNER_QUEUE_FULL"]) from exc
        return ClarificationAcceptedResponse(
            task_id=task_id,
            accepted=True,
            state=TaskState.PLANNING,
            message="Clarification received. Updating the plan.",
        )

    # ---------------------------------------------------------------- plans

    async def get_plan(self, task_id: UUID, session_id: UUID | None = None) -> TaskPlan:
        task = await self._tasks.get_task(task_id)
        if session_id is not None and task.session_id != session_id:
            raise TaskSessionMismatchError("Task does not belong to this session.")
        if task.state in (TaskState.IDLE, TaskState.PLANNING):
            raise PlanNotReadyError(task.state)
        record = self._store.get(task_id)
        if record is None or record.plan is None:
            raise PlanNotFoundError(str(task_id))
        return record.plan

    # Set by the container: True only if execution is enabled AND Chromium is installed.
    execution_available: Callable[[], bool] | None = None

    @property
    def browser_execution_available(self) -> bool:
        return bool(self.execution_available and self.execution_available())

    async def agent_status(self, probe: bool = False) -> AgentStatusResponse:
        reachable: bool | None = None
        status = "available" if self.enabled else "disabled"
        if probe and self.enabled:
            reachable = await self._provider.health_check()
            status = "available" if reachable else "unavailable"
        return AgentStatusResponse(
            agent_name=self._settings.assistant_name or ASSISTANT_NAME,
            provider=self._provider.name,
            model=self._provider.model,
            status=status,  # type: ignore[arg-type]
            planning_enabled=self.enabled,
            browser_execution_enabled=self.browser_execution_available,
            is_mock=self._provider.name == "mock",
            provider_reachable=reachable,
            planner_kind="offline_rules" if self._provider.name == "mock" else "ai",
            setup_hint=self._settings.planner_setup_hint if self._provider.name == "mock" else None,
        )

    # ---------------------------------------------------------------- workers

    async def _run_job(self, job: PlanningJob) -> None:
        with span("planning.job", component="planner"):
            await self._run_job_inner(job)

    async def _run_job_inner(self, job: PlanningJob) -> None:
        try:
            await self._orchestrator.process_task(job.task_id, job.session_id)
        except (ProviderError, PlanValidationError):
            pass  # already reported and the task moved to FAILED by the orchestrator
        except PlanningAborted as exc:
            logger.info("planning.aborted", extra={"task_id": str(job.task_id), "reason": str(exc)})
        except LookupError:
            logger.warning("planning.record_missing", extra={"task_id": str(job.task_id)})

    async def _job_failed(self, job: PlanningJob, code: str) -> None:
        await self._fail_task(job.task_id, code)

    async def _fail_task(self, task_id: UUID, code: str) -> None:
        if code in ("PLANNING_CANCELLED", "PLANNING_TIMEOUT"):
            # A job cancelled/timed out while finishing bookkeeping after its plan was ready must not fail the task
            # (Phase 6: this state is persisted and must survive restarts).
            try:
                current = await self._tasks.get_task(task_id)
            except LookupError:
                return
            if current.state not in (TaskState.IDLE, TaskState.PLANNING):
                return
        record = self._store.get(task_id)
        message = _FAILURE_MESSAGES.get(code, _FAILURE_MESSAGES["INTERNAL_PLANNING_ERROR"])
        if record is None:
            try:
                await self._tasks.transition(task_id, TaskState.FAILED, reason=message, error_code=code)
            except Exception:  # noqa: BLE001
                logger.exception("planning.fail_without_record")
            return
        language = detect_language(record.clarifications[-1].answer if record.clarifications else record.command)
        await self._orchestrator.fail(record, code, message, language)
