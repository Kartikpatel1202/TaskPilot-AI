from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.schemas.agent import ClarificationAcceptedResponse, ClarificationRequest
from app.schemas.common import APIError
from app.schemas.plan import TaskPlan
from app.schemas.task import CreateTaskRequest, Task, TaskAcceptedResponse, TaskListResponse
from app.services.planning_service import PlanningService
from app.services.task_service import TaskService

from .deps import get_planning_service, get_task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskAcceptedResponse,
    responses={422: {"model": APIError}, 503: {"model": APIError}},
    summary="Accept a natural-language command and queue it for planning (no browser execution)",
)
async def create_task(
    body: CreateTaskRequest,
    planning: PlanningService = Depends(get_planning_service),
    tasks: TaskService = Depends(get_task_service),
) -> TaskAcceptedResponse:
    task = await planning.accept_command(body)
    return TaskAcceptedResponse(
        task_id=task.task_id,
        session_id=task.session_id,
        state=task.state,
        accepted=True,
        message=tasks.accepted_message,
        created_at=task.created_at,
    )


@router.get("/{task_id}", response_model=Task, responses={404: {"model": APIError}})
async def get_task(task_id: UUID, service: TaskService = Depends(get_task_service)) -> Task:
    return await service.get_task(task_id)


@router.get("", response_model=TaskListResponse, summary="List recent tasks for a session")
async def list_tasks(
    session_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    service: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    return TaskListResponse(tasks=service.list_tasks(session_id, limit))


@router.get(
    "/{task_id}/plan",
    response_model=TaskPlan,
    responses={403: {"model": APIError}, 404: {"model": APIError}, 409: {"model": APIError}},
    summary="Get the validated action plan for a task",
)
async def get_plan(
    task_id: UUID,
    session_id: UUID | None = Query(default=None, description="Optional ownership check"),
    planning: PlanningService = Depends(get_planning_service),
) -> TaskPlan:
    return await planning.get_plan(task_id, session_id)


@router.post(
    "/{task_id}/clarification",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ClarificationAcceptedResponse,
    responses={403: {"model": APIError}, 404: {"model": APIError}, 409: {"model": APIError}, 503: {"model": APIError}},
    summary="Answer Kamlesh Bhai's clarification question and re-plan the same task",
)
async def submit_clarification(
    task_id: UUID,
    body: ClarificationRequest,
    planning: PlanningService = Depends(get_planning_service),
) -> ClarificationAcceptedResponse:
    return await planning.submit_clarification(task_id, body)


# ---------------------------------------------------------------------- Phase 6: persistent, paginated task history

history_router = APIRouter(prefix="/task-history", tags=["tasks"])


@history_router.get("", summary="Your task history (newest first, cursor-paginated, survives restarts)")
async def task_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=80),
    session_id: UUID | None = Query(default=None),
    state: str | None = Query(default=None, max_length=32),
) -> dict[str, object]:
    from datetime import datetime

    from app.auth.context import current_user

    container = request.app.state.container
    user = current_user.get()
    before = None
    if cursor:
        try:
            created, _, tid = cursor.partition("|")
            before = (datetime.fromisoformat(created), UUID(tid))
        except ValueError:
            before = None
    sessions = [session_id] if (user is None and session_id) else None
    rows = await container.persistence.tasks.history(user_id=user.id if user else None, session_ids=sessions, limit=limit,
                                                     before=before, state=state)
    items = [{"task_id": str(r.id), "session_id": str(r.session_id), "command": r.command[:300], "state": r.state,
              "error_code": r.error_code, "error_message": r.error_message, "execution_status": r.execution_status,
              "recovery_note": r.recovery_note, "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat()}
             for r in rows]
    next_cursor = f"{rows[-1].created_at.isoformat()}|{rows[-1].id}" if len(rows) == limit else None
    return {"tasks": items, "next_cursor": next_cursor}
