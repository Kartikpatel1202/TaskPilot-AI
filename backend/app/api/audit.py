"""Audit trail (read-only API): own events for everyone, all events + chain verification + export for OWNERs.
There is deliberately no endpoint that edits or deletes audit records."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth.context import current_user
from app.auth.policies import is_admin

router = APIRouter(prefix="/audit", tags=["audit"])


def _row(r: Any) -> dict[str, Any]:
    return {"seq": r.seq, "event_id": str(r.event_id), "event_type": r.event_type, "outcome": r.outcome,
            "user_id": str(r.user_id) if r.user_id else None, "task_id": str(r.task_id) if r.task_id else None,
            "resource_type": r.resource_type, "resource_id": str(r.resource_id) if r.resource_id else None,
            "occurred_at": r.occurred_at.isoformat(), "correlation_id": str(r.correlation_id), "metadata": r.metadata_json,
            "hash": r.hash}


def _scope(request: Request, all_users: bool) -> tuple[Any, JSONResponse | None]:
    user = current_user.get()
    enforced = request.app.state.container.settings.auth_enforced
    if user is None:
        if enforced:
            return None, JSONResponse(status_code=401, content={"code": "AUTHENTICATION_REQUIRED", "message": "Please sign in."})
        return None, None  # development without authentication: whole (local) trail
    if all_users and not is_admin(user.role):
        return None, JSONResponse(status_code=403, content={"code": "FORBIDDEN", "message": "Administrators only."})
    return (None if all_users else user.id), None


@router.get("")
async def audit_page(request: Request, limit: int = Query(default=50, ge=1, le=200), before_seq: int | None = Query(default=None, ge=1),
                     event_type: str | None = Query(default=None, max_length=64), all_users: bool = False) -> JSONResponse:
    scope, denied = _scope(request, all_users)
    if denied is not None:
        return denied
    rows = await request.app.state.container.persistence.audit.page(user_id=scope, after_seq=before_seq, limit=limit, event_type=event_type)
    next_cursor = rows[-1].seq if len(rows) == limit else None
    return JSONResponse(content={"events": [_row(r) for r in rows], "next_before_seq": next_cursor})


@router.get("/verify")
async def audit_verify(request: Request) -> JSONResponse:
    _, denied = _scope(request, True)
    if denied is not None:
        return denied
    intact, checked, broken = await request.app.state.container.persistence.audit.verify()
    return JSONResponse(content={"intact": intact, "checked": checked, "first_broken_seq": broken})


@router.get("/export")
async def audit_export(request: Request, limit: int = Query(default=10_000, ge=1, le=100_000)) -> Any:
    _, denied = _scope(request, True)
    if denied is not None:
        return denied
    repo = request.app.state.container.persistence.audit

    async def lines() -> Any:
        cursor = None
        sent = 0
        while sent < limit:
            rows = await repo.page(user_id=None, after_seq=cursor, limit=min(500, limit - sent))
            if not rows:
                break
            for r in rows:
                yield json.dumps(_row(r)) + "\n"
            sent += len(rows)
            cursor = rows[-1].seq

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=taskpilot-audit.ndjson"})
