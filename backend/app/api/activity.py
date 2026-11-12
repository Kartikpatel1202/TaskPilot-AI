"""Activity Logs page API — real persisted history, owner-scoped.

  GET /activity/events          flat timeline: task lifecycle, browser steps (execution journal), audit events
  GET /activity/tasks/{task_id} one task: command, plan summary, every step with its result, related events

Sources are the database tables written by the running system (tasks, plans, action_journal, audit_events,
conversation_turns); nothing here is synthesised. With authentication enforced, a user only sees their own
tasks and events; in development without authentication the single local user sees everything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.context import current_user_id
from app.database.models import ActionJournalRecord, AuditEventRecord, ConversationTurnRecord, PlanRecord, TaskRecord

router = APIRouter(prefix="/activity", tags=["activity"])

EventKind = Literal["task", "step", "approval", "browser", "purchase", "integration", "security", "other"]


class ActivityEvent(BaseModel):
    id: str
    kind: EventKind
    occurred_at: datetime
    title: str
    status: str
    task_id: UUID | None = None
    command: str | None = None
    detail: str | None = None
    error_code: str | None = None
    duration_ms: int | None = None


class ActivityPage(BaseModel):
    events: list[ActivityEvent]
    next_before: datetime | None


class StepView(BaseModel):
    order: int
    action_type: str
    lifecycle: str
    attempt: int
    mutating: bool
    error_code: str | None
    message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None


class TaskActivity(BaseModel):
    task_id: UUID
    session_id: UUID
    command: str
    input_mode: str
    state: str
    error_code: str | None
    error_message: str | None
    execution_status: str | None
    recovery_note: str | None
    created_at: datetime
    updated_at: datetime
    intent: str | None
    plan_status: str | None
    plan_summary: str | None
    planner: str | None
    steps: list[StepView]
    events: list[ActivityEvent]
    conversation: list[dict[str, str]]


_STEP_TITLES = {"navigate": "Opened page", "click": "Clicked", "type": "Typed into field", "extract": "Read page", "wait": "Waited",
                "scroll": "Scrolled", "commerce": "Shopping step", "integration": "Integration step", "stop": "Stopped"}


def _kind_for(event_type: str) -> EventKind:
    head = event_type.split(".", 1)[0]
    return {
        "task": "task", "plan": "task", "execution": "task", "action": "step", "approval": "approval", "browser": "browser",
        "purchase": "purchase", "calendar": "integration", "gmail": "integration", "file": "integration", "auth": "security",
        "recovery": "task", "preferences": "other",
    }.get(head, "other")  # type: ignore[return-value]


def _owner_filter(stmt: Any, column: Any) -> Any:
    uid = current_user_id()
    return stmt.where(column == uid) if uid is not None else stmt


def _db(request: Request) -> Any:
    return request.app.state.container.db


@router.get("/events", response_model=ActivityPage, summary="Timeline of your persisted activity")
async def activity_events(
    request: Request,
    kind: EventKind | Literal["all"] = "all",
    status: str | None = Query(default=None, max_length=32, description="e.g. FAILED, COMPLETED, SUCCEEDED, BLOCKED"),
    task_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=100, description="Text search in task commands"),
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> ActivityPage:
    events: list[ActivityEvent] = []
    status_u = status.upper() if status else None
    async with _db(request).session() as s:
        # Tasks (creation + current outcome) — the backbone of the log.
        if kind in ("all", "task"):
            stmt = _owner_filter(select(TaskRecord), TaskRecord.user_id).order_by(TaskRecord.updated_at.desc()).limit(limit)
            if task_id:
                stmt = stmt.where(TaskRecord.id == task_id)
            if before:
                stmt = stmt.where(TaskRecord.updated_at < before)
            if status_u:
                stmt = stmt.where(TaskRecord.state == status_u)
            if q:
                stmt = stmt.where(TaskRecord.command.ilike(f"%{q}%"))
            for t in await s.scalars(stmt):
                events.append(ActivityEvent(
                    id=f"task:{t.id}", kind="task", occurred_at=t.updated_at, title=_task_title(t.state), status=t.state,
                    task_id=t.id, command=t.command[:300], detail=t.error_message or t.recovery_note, error_code=t.error_code))
        # Browser steps from the execution journal (tasks you own).
        if kind in ("all", "step", "browser"):
            stmt = (select(ActionJournalRecord, TaskRecord.command).join(TaskRecord, TaskRecord.id == ActionJournalRecord.task_id)
                    .order_by(ActionJournalRecord.created_at.desc()).limit(limit))
            stmt = _owner_filter(stmt, TaskRecord.user_id)
            if task_id:
                stmt = stmt.where(ActionJournalRecord.task_id == task_id)
            if before:
                stmt = stmt.where(ActionJournalRecord.created_at < before)
            if status_u:
                stmt = stmt.where(ActionJournalRecord.lifecycle == status_u)
            if q:
                stmt = stmt.where(TaskRecord.command.ilike(f"%{q}%"))
            for j, command in (await s.execute(stmt)).all():
                events.append(ActivityEvent(
                    id=f"step:{j.id}", kind="step", occurred_at=j.completed_at or j.started_at or j.created_at,
                    title=f"Step {j.step_order}: {_STEP_TITLES.get(j.action_type, j.action_type)}", status=j.lifecycle, task_id=j.task_id,
                    command=command[:300], detail=_result_message(j.result_json), error_code=j.error_code, duration_ms=j.duration_ms))
        # Audit trail (approvals, purchases, navigation, integrations, security).
        if kind != "task" and kind != "step":
            stmt = _owner_filter(select(AuditEventRecord), AuditEventRecord.user_id).order_by(AuditEventRecord.seq.desc()).limit(limit)
            if task_id:
                stmt = stmt.where(AuditEventRecord.task_id == task_id)
            if before:
                stmt = stmt.where(AuditEventRecord.occurred_at < before)
            if status_u:
                stmt = stmt.where(AuditEventRecord.outcome == status_u)
            for a in await s.scalars(stmt):
                k = _kind_for(a.event_type)
                if kind not in ("all", k) or k == "task":
                    continue  # task lifecycle already comes from the tasks table
                events.append(ActivityEvent(
                    id=f"audit:{a.seq}", kind=k, occurred_at=a.occurred_at, title=a.event_type.replace(".", " · ").replace("_", " "),
                    status=a.outcome, task_id=a.task_id, detail=_meta_text(a.metadata_json),
                    error_code=(a.metadata_json or {}).get("code") or (a.metadata_json or {}).get("error_code")))
    events.sort(key=lambda e: e.occurred_at, reverse=True)
    page = events[:limit]
    return ActivityPage(events=page, next_before=page[-1].occurred_at if len(events) > limit or len(page) == limit else None)


@router.get("/tasks/{task_id}", response_model=TaskActivity, summary="Everything recorded for one task")
async def task_activity(task_id: UUID, request: Request) -> TaskActivity:
    async with _db(request).session() as s:
        task = await s.get(TaskRecord, task_id)
        uid = current_user_id()
        if task is None or (uid is not None and task.user_id != uid):
            raise HTTPException(status_code=404, detail="Task not found")
        plan = (await s.scalars(select(PlanRecord).where(PlanRecord.task_id == task_id).order_by(PlanRecord.created_at.desc()).limit(1))).first()
        journal = list(await s.scalars(select(ActionJournalRecord).where(ActionJournalRecord.task_id == task_id)
                                       .order_by(ActionJournalRecord.step_order, ActionJournalRecord.attempt)))
        audits = list(await s.scalars(select(AuditEventRecord).where(AuditEventRecord.task_id == task_id).order_by(AuditEventRecord.seq)))
        turns = list(await s.scalars(select(ConversationTurnRecord).where(ConversationTurnRecord.task_id == task_id)
                                     .order_by(ConversationTurnRecord.created_at)))
    plan_json = plan.plan_json if plan else {}
    return TaskActivity(
        task_id=task.id, session_id=task.session_id, command=task.command, input_mode=task.input_mode, state=task.state,
        error_code=task.error_code, error_message=task.error_message, execution_status=task.execution_status,
        recovery_note=task.recovery_note, created_at=task.created_at, updated_at=task.updated_at,
        intent=plan_json.get("intent"), plan_status=plan.status if plan else None, plan_summary=plan_json.get("summary"),
        planner=f"{plan.provider} · {plan.model}" if plan else None,
        steps=[StepView(order=j.step_order, action_type=j.action_type, lifecycle=j.lifecycle, attempt=j.attempt, mutating=j.mutating,
                        error_code=j.error_code, message=_result_message(j.result_json), started_at=j.started_at,
                        completed_at=j.completed_at, duration_ms=j.duration_ms) for j in journal],
        events=[ActivityEvent(id=f"audit:{a.seq}", kind=_kind_for(a.event_type), occurred_at=a.occurred_at,
                              title=a.event_type.replace(".", " · ").replace("_", " "), status=a.outcome, task_id=a.task_id,
                              detail=_meta_text(a.metadata_json)) for a in audits],
        conversation=[{"role": t.role, "content": t.content[:800], "at": t.created_at.isoformat()} for t in turns],
    )


def _task_title(state: str) -> str:
    return {"PLANNED": "Plan ready", "NEEDS_CLARIFICATION": "Waiting for your answer", "EXECUTING": "Running in browser",
            "WAITING_APPROVAL": "Waiting for approval", "COMPLETED": "Task completed", "FAILED": "Task failed",
            "CANCELLED": "Task cancelled", "PLANNING": "Planning", "IDLE": "Task received"}.get(state, state.title())


def _result_message(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    msg = result.get("message") or result.get("summary")
    return str(msg)[:400] if msg else None


def _meta_text(meta: Any) -> str | None:
    if not isinstance(meta, dict) or not meta:
        return None
    return ", ".join(f"{k}: {v}" for k, v in list(meta.items())[:6])[:300]
