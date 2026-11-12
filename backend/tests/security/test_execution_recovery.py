"""Restart recovery (Scenario 1 + crash states). A "restart" is a second app instance on the same
SQLite file. Crash states are created by writing exactly the rows an interrupted process leaves behind
(task EXECUTING, journal step RUNNING, approval PENDING) — the recovery logic itself is the real one."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.database.models import ActionJournalRecord, ApprovalRecord, TaskRecord
from app.main import create_app
from app.schemas.common import utc_now

from ..conftest import make_settings, post_command, wait_for_task_state


def _settings(db: Path, **kw: object):  # noqa: ANN202
    return make_settings(database_url=f"sqlite+aiosqlite:///{db.as_posix()}", **kw)


def test_scenario1_planned_task_and_plan_survive_an_api_restart(tmp_path: Path) -> None:
    db = tmp_path / "tp.db"
    sid = str(uuid4())
    with TestClient(create_app(_settings(db))) as first:
        task_id = post_command(first, "Search for wireless earbuds on amazon", sid)["task_id"]
        assert wait_for_task_state(first, task_id)["state"] == "PLANNED"
        plan_before = first.get(f"/api/v1/tasks/{task_id}/plan").json()
    with TestClient(create_app(_settings(db))) as second:  # API restarted
        report = second.app.state.container.recovery_report  # type: ignore[attr-defined]
        assert report.restored >= 1
        task = second.get(f"/api/v1/tasks/{task_id}").json()
        assert task["state"] == "PLANNED" and task["command"] == "Search for wireless earbuds on amazon"
        plan_after = second.get(f"/api/v1/tasks/{task_id}/plan").json()
        assert plan_after["plan_id"] == plan_before["plan_id"] and plan_after["steps"] == plan_before["steps"]
        history = second.get("/api/v1/task-history", params={"session_id": sid}).json()["tasks"]
        assert [t["task_id"] for t in history] == [task_id]


def _seed_crash(client: TestClient, *, state: str, journal: list[tuple[int, str, str, bool]], approval: bool,
                command: str = "fixture Blinkit par 12 eggs order karo, cash on delivery") -> tuple[str, str]:
    task_id, sid, plan_id = uuid4(), uuid4(), uuid4()

    async def seed() -> None:
        db = client.app.state.container.persistence.db  # type: ignore[attr-defined]
        now = utc_now()
        async with db.session() as s:
            s.add(TaskRecord(id=task_id, session_id=sid, command=command,
                             input_mode="TEXT", state=state, created_at=now, updated_at=now))
        async with db.session() as s:
            for order, action, lifecycle, mutating in journal:
                step = uuid4()
                s.add(ActionJournalRecord(idempotency_key=f"{task_id}:{plan_id}:{step}:v1", task_id=task_id, plan_id=plan_id, step_id=step,
                                          step_order=order, action_type=action, mutating=mutating, lifecycle=lifecycle, created_at=now,
                                          started_at=now))
            if approval:
                req = {"approval_id": str(uuid4()), "task_id": str(task_id), "session_id": str(sid), "action_summary": "Place order",
                       "domain": "x", "reason": "r", "risk_level": "CRITICAL", "status": "PENDING", "expires_at": now.isoformat(),
                       "is_demo": False, "created_at": now.isoformat()}
                s.add(ApprovalRecord(id=UUID(req["approval_id"]), task_id=task_id, session_id=sid, action_type="purchase", status="PENDING",
                                     risk_level="CRITICAL", request_json=req, created_at=now, expires_at=now))

    client.portal.call(seed)  # type: ignore[union-attr]
    return str(task_id), str(sid)


def test_interrupted_execution_is_reconciled_never_resumed(tmp_path: Path) -> None:
    db = tmp_path / "tp.db"
    with TestClient(create_app(_settings(db))) as first:
        task_id, _ = _seed_crash(first, state="WAITING_APPROVAL", approval=True, journal=[
            (1, "commerce", "SUCCEEDED", False), (2, "commerce", "SUCCEEDED", True), (3, "commerce", "RUNNING", True)])
    with TestClient(create_app(_settings(db))) as second:
        task = second.get(f"/api/v1/tasks/{task_id}").json()
        assert task["state"] == "FAILED"
        row = second.portal.call(second.app.state.container.persistence.tasks.get, UUID(task_id))  # type: ignore[union-attr]
        assert row.error_code == "EXECUTION_INTERRUPTED" and row.execution_status == "UNKNOWN"
        assert "step(s) 1, 2" in row.recovery_note and "Step(s) 3 may or may not have changed the website" in row.recovery_note
        journal = second.portal.call(second.app.state.container.persistence.journal.for_task, UUID(task_id))  # type: ignore[union-attr]
        assert [j.lifecycle for j in journal] == ["SUCCEEDED", "SUCCEEDED", "UNKNOWN"]
        approvals = second.portal.call(second.app.state.container.persistence.approvals.pending)  # type: ignore[union-attr]
        assert approvals == []  # the pending purchase approval was WITHDRAWN, never resumable
        audit = second.portal.call(lambda: second.app.state.container.persistence.audit.page(user_id=None, after_seq=None, limit=20))  # type: ignore[union-attr]
        assert {"recovery.task", "recovery.approval"} <= {a.event_type for a in audit}


def test_interrupted_planning_is_replanned_once(tmp_path: Path) -> None:
    db = tmp_path / "tp.db"
    with TestClient(create_app(_settings(db))) as first:
        task_id, _ = _seed_crash(first, state="PLANNING", approval=False, journal=[], command="Search for wireless earbuds on amazon")
    with TestClient(create_app(_settings(db))) as second:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and second.get(f"/api/v1/tasks/{task_id}").json()["state"] == "PLANNING":
            time.sleep(0.05)
        assert second.get(f"/api/v1/tasks/{task_id}").json()["state"] in ("PLANNED", "NEEDS_CLARIFICATION")
        assert second.app.state.container.recovery_report.replanned == 1  # type: ignore[attr-defined]


def test_unmigrated_database_refuses_to_start(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(RuntimeError, match="not migrated"):
        with TestClient(create_app(_settings(tmp_path / "empty.db", database_auto_create=False))):
            pass
