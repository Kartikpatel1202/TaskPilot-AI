from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.schemas.common import APIError
from app.schemas.execution import (
    ExecutionAcceptedResponse,
    ExecutionSummary,
    ExecuteTaskRequest,
    StopTaskRequest,
    StopTaskResponse,
)
from app.services.execution_service import ExecutionService

from .deps import get_execution_service

router = APIRouter(prefix="/tasks", tags=["execution"])

_ERRORS = {403: {"model": APIError}, 404: {"model": APIError}, 409: {"model": APIError}, 503: {"model": APIError}}


@router.post(
    "/{task_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ExecutionAcceptedResponse,
    responses=_ERRORS,
    summary="Run a READY plan in a real Chromium browser (explicit user action only)",
)
async def execute_task(
    task_id: UUID, body: ExecuteTaskRequest, service: ExecutionService = Depends(get_execution_service)
) -> ExecutionAcceptedResponse:
    return await service.execute(task_id, body)


@router.post(
    "/{task_id}/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=StopTaskResponse,
    responses=_ERRORS,
    summary="Stop an active execution; remaining steps never run",
)
async def stop_task(
    task_id: UUID, body: StopTaskRequest, service: ExecutionService = Depends(get_execution_service)
) -> StopTaskResponse:
    return await service.stop(task_id, body)


@router.get(
    "/{task_id}/execution",
    response_model=ExecutionSummary,
    responses={404: {"model": APIError}},
    summary="Verified step results of the task's latest execution",
)
async def get_execution(
    task_id: UUID,
    session_id: UUID | None = Query(default=None),
    service: ExecutionService = Depends(get_execution_service),
) -> ExecutionSummary:
    from app.execution.execution_manager import ExecutionNotActiveError, ExecutionSessionMismatchError

    summary = service.summary(task_id)
    if summary is None:
        raise ExecutionNotActiveError("No finished execution exists for this task yet.")
    if session_id is not None and summary.session_id != session_id:
        raise ExecutionSessionMismatchError("This task belongs to a different session.")
    return summary
