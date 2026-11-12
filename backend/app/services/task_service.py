"""Task lifecycle service (in-memory, Phase 1).

Creating a task validates and records it, then publishes `task.accepted`.
It does NOT plan, call an LLM or launch a browser — the `planner` and
`browser` hooks stay `None` until later phases provide implementations.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any
from uuid import UUID, uuid4

from app.auth.context import current_user_id

from app.core.event_manager import EventManager
from app.core.logging import get_logger
from app.core.persona import detect_language, persona_message, task_acknowledgement
from app.core.state_machine import INITIAL_STATE, validate_transition
from app.schemas.common import utc_now
from app.schemas.task import CreateTaskRequest, InputMode, Task, TaskState
from app.schemas.telemetry import (
    LogLevel,
    TaskAcceptedPayload,
    TaskCompletedPayload,
    TaskFailedPayload,
    TaskStateChangedPayload,
    TelemetryEventType,
)
from app.services.interfaces import BrowserController, TaskPlanner

logger = get_logger("tasks")

ACCEPTED_MESSAGE = "Task accepted. Agent planning will be available in a later phase."
PLANNING_ACCEPTED_MESSAGE = "Task accepted. Kamlesh Bhai is preparing an action plan."


class TaskNotFoundError(LookupError):
    pass


class TaskService:
    def __init__(
        self,
        events: EventManager,
        max_tasks: int,
        planner: TaskPlanner | None = None,
        browser: BrowserController | None = None,
        planning_enabled: bool = False,
    ) -> None:
        self._events = events
        self._max_tasks = max_tasks
        self._tasks: OrderedDict[UUID, Task] = OrderedDict()
        self._lock = asyncio.Lock()
        # Extension points — intentionally unused in Phase 1.
        self.planner = planner
        self.browser = browser
        self.planning_enabled = planning_enabled
        self.persistence: Any = None  # Phase 6 Persistence (set by the container)
        self._owners: dict[UUID, UUID] = {}

    @property
    def accepted_message(self) -> str:
        return PLANNING_ACCEPTED_MESSAGE if self.planning_enabled else ACCEPTED_MESSAGE

    async def create_task(self, request: CreateTaskRequest, *, is_demo: bool = False) -> Task:
        now = utc_now()
        task = Task(
            task_id=uuid4(),
            session_id=request.session_id,
            command=request.command,
            input_mode=request.input_mode,
            state=INITIAL_STATE,
            created_at=now,
            updated_at=now,
            is_demo=is_demo,
        )
        owner = current_user_id()
        if self.persistence is not None:
            # The database is authoritative: if it is unavailable the task is refused (503), never half-created.
            await self.persistence.tasks.upsert(task, user_id=owner)
        async with self._lock:
            self._tasks[task.task_id] = task
            if owner is not None:
                self._owners[task.task_id] = owner
            while len(self._tasks) > self._max_tasks:
                evicted, _ = self._tasks.popitem(last=False)
                self._owners.pop(evicted, None)

        logger.info(
            "task.created",
            extra={"task_id": str(task.task_id), "input_mode": task.input_mode.value, "demo": is_demo},
        )
        await self._events.emit(
            task.session_id,
            TelemetryEventType.TASK_ACCEPTED,
            TaskAcceptedPayload(
                task_id=task.task_id,
                state=task.state,
                command=task.command,
                input_mode=task.input_mode,
                created_at=task.created_at,
                is_demo=is_demo,
            ),
            task_id=task.task_id,
        )
        if not is_demo:
            if self.planning_enabled:
                language = detect_language(task.command)
                reply = persona_message("acknowledgement", language)
            else:
                reply, language = task_acknowledgement(task.command)
            await self._events.log(
                task.session_id,
                LogLevel.INFO,
                reply,
                task_id=task.task_id,
                source="assistant",
                language=language,
            )
        return task

    async def get_task(self, task_id: UUID) -> Task:
        task = self._tasks.get(task_id)
        if task is None and self.persistence is not None:
            from app.database.repositories.task_repository import to_task

            row = await self.persistence.tasks.get(task_id)
            if row is not None:  # e.g. created before a restart; read-only view from the database
                task = to_task(row)
                if row.user_id is not None:
                    self._owners[task_id] = row.user_id
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    def owner_of(self, task_id: UUID) -> UUID | None:
        return self._owners.get(task_id)

    def restore(self, task: Task, owner: UUID | None) -> None:
        """Phase 6 recovery: re-register a task loaded from the database."""
        self._tasks[task.task_id] = task
        if owner is not None:
            self._owners[task.task_id] = owner

    def list_tasks(self, session_id: UUID, limit: int = 50) -> list[Task]:
        tasks = [t for t in self._tasks.values() if t.session_id == session_id]
        return list(reversed(tasks))[:limit]

    async def transition(
        self,
        task_id: UUID,
        target: TaskState,
        *,
        reason: str | None = None,
        error_code: str | None = None,
    ) -> Task:
        """Apply a validated state transition and publish telemetry for it."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(str(task_id))
            previous = task.state
            validate_transition(previous, target)
            updated = task.model_copy(
                update={
                    "state": target,
                    "updated_at": utc_now(),
                    "error_message": reason
                    if target in (TaskState.FAILED, TaskState.CANCELLED)
                    else task.error_message,
                }
            )
            self._tasks[task_id] = updated

        if self.persistence is not None:
            await self.persistence.best_effort(self.persistence.tasks.upsert(updated, error_code=error_code), "task.transition")
        await self._events.emit(
            updated.session_id,
            TelemetryEventType.TASK_STATE_CHANGED,
            TaskStateChangedPayload(
                previous_state=previous, new_state=target, reason=reason, is_demo=updated.is_demo
            ),
            task_id=task_id,
        )
        if target == TaskState.COMPLETED:
            await self._events.emit(
                updated.session_id,
                TelemetryEventType.TASK_COMPLETED,
                TaskCompletedPayload(summary=reason or "Task completed.", is_demo=updated.is_demo),
                task_id=task_id,
            )
        elif target == TaskState.FAILED:
            await self._events.emit(
                updated.session_id,
                TelemetryEventType.TASK_FAILED,
                TaskFailedPayload(
                    error_code=error_code or "TASK_FAILED",
                    error_message=reason or "Task failed.",
                    is_demo=updated.is_demo,
                ),
                task_id=task_id,
            )
        return updated


def demo_task_request(session_id: UUID, command: str) -> CreateTaskRequest:
    return CreateTaskRequest(command=command, session_id=session_id, input_mode=InputMode.TEXT)
