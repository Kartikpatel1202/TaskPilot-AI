"""API-facing facade over the ExecutionManager (keeps route handlers thin)."""

from __future__ import annotations

from uuid import UUID

from app.execution.execution_manager import ExecutionManager
from app.execution.execution_result import ExecutionSummary
from app.schemas.execution import ExecutionAcceptedResponse, ExecuteTaskRequest, StopTaskRequest, StopTaskResponse


class ExecutionService:
    def __init__(self, manager: ExecutionManager) -> None:
        self._manager = manager

    async def execute(self, task_id: UUID, request: ExecuteTaskRequest) -> ExecutionAcceptedResponse:
        await self._manager.submit(task_id, request.session_id, trigger=request.trigger)
        return ExecutionAcceptedResponse(
            task_id=task_id, session_id=request.session_id, message="Browser execution has been queued."
        )

    async def stop(self, task_id: UUID, request: StopTaskRequest) -> StopTaskResponse:
        return await self._manager.stop_task(task_id, request.session_id, request.reason)

    def summary(self, task_id: UUID) -> ExecutionSummary | None:
        return self._manager.summary(task_id)
