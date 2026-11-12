"""Startup recovery: reconcile persisted state after an API/worker restart. Every decision is
audited. Nothing that could repeat an external mutation is resumed automatically.

| Persisted state            | Decision                                                                  |
| -------------------------- | ------------------------------------------------------------------------- |
| PLANNED (+ READY plan)     | restored: plan visible, Run Plan works (fresh validation at submit)       |
| NEEDS_CLARIFICATION        | restored with its question and history                                    |
| IDLE / PLANNING, no plan   | re-planned once if no clarification was involved, else FAILED             |
| EXECUTING / WAITING_APPROV.| journal reconciled (RUNNING mutations -> UNKNOWN), task FAILED with a note |
| PENDING approvals          | WITHDRAWN (never resumable)                                               |
| browser sessions           | marked CLOSED (the browser process is gone)                               |
| partial downloads (.part)  | deleted; live file metadata re-registered if the bytes still exist        |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.database.repositories.task_repository import to_task
from app.resilience.reconciliation import journal_summary
from app.schemas.approval import ApprovalRequest, ApprovalStatus
from app.schemas.common import utc_now
from app.schemas.files import DownloadedFile, DownloadStatus
from app.schemas.plan import PlanStatus
from app.schemas.task import TaskState

logger = get_logger("recovery")


@dataclass
class RecoveryReport:
    restored: int = 0
    replanned: int = 0
    failed_interrupted: int = 0
    approvals_withdrawn: int = 0
    browser_sessions_closed: int = 0
    partial_files_removed: int = 0
    files_restored: int = 0
    decisions: list[dict[str, Any]] = field(default_factory=list)


async def recover(container: Any) -> RecoveryReport:
    p = container.persistence
    report = RecoveryReport()
    if p is None:
        return report
    await _recover_approvals(container, report)
    for row in await p.tasks.active():
        await _recover_task(container, row, report)
    await _recover_files(container, report)
    await _recover_browser_sessions(container, report)
    logger.info("recovery.completed", extra={k: v for k, v in report.__dict__.items() if k != "decisions"})
    return report


async def _decide(container: Any, report: RecoveryReport, row: Any, decision: str) -> None:
    report.decisions.append({"task_id": str(row.id), "state": row.state, "decision": decision})
    await container.audit.record("recovery.task", outcome=decision, user_id=row.user_id, task_id=row.id, session_id=row.session_id,
                                 metadata={"state": row.state, "recovery": decision})


async def _recover_task(container: Any, row: Any, report: RecoveryReport) -> None:
    p = container.persistence
    plan = await p.plans.latest_plan(row.id)
    plan_row = await p.plans.latest(row.id)
    task = to_task(row)
    if row.state in (TaskState.PLANNED.value, TaskState.PLANNING.value) and plan is not None and plan.status == PlanStatus.READY:
        if row.state == TaskState.PLANNING.value:  # the plan was saved but the PLANNED transition was lost
            task = task.model_copy(update={"state": TaskState.PLANNED, "updated_at": utc_now()})
            await p.tasks.upsert(task)
        container.tasks.restore(task, row.user_id)
        record = container.store.create(task.task_id, task.session_id, plan_row.command or task.command)
        record.user_turn_recorded = True
        record.clarifications = list(plan.clarification_history)
        record.set_plan(plan)
        report.restored += 1
        await _decide(container, report, row, "RESTORED_PLANNED")
        return
    if row.state == TaskState.NEEDS_CLARIFICATION.value and plan is not None:
        container.tasks.restore(task, row.user_id)
        record = container.store.create(task.task_id, task.session_id, plan_row.command or task.command)
        record.user_turn_recorded = True
        record.clarifications = list(plan.clarification_history)
        record.pending_question = plan.clarification_question
        record.set_plan(plan)
        report.restored += 1
        await _decide(container, report, row, "RESTORED_CLARIFICATION")
        return
    if row.state in (TaskState.IDLE.value, TaskState.PLANNING.value) and plan is None and container.planning.enabled:
        container.tasks.restore(task, row.user_id)
        container.store.create(task.task_id, task.session_id, task.command).user_turn_recorded = True
        try:
            from app.core.planner_queue import PlanningJob

            container.planning.queue.submit(PlanningJob(task.task_id, task.session_id, "new"))
            report.replanned += 1
            await _decide(container, report, row, "REPLANNED_AFTER_RESTART")
            return
        except Exception:  # noqa: BLE001 - queue full: fall through to an honest failure
            pass
    # Anything else (running, waiting for approval, or not safely re-plannable) ends FAILED with a note.
    running = row.state in (TaskState.EXECUTING.value, TaskState.WAITING_APPROVAL.value)
    rows: list[Any] = []
    if running:
        await p.journal.mark_in_flight_unknown(row.id)  # RUNNING mutations -> UNKNOWN, PREPARED -> CANCELLED
        rows = await p.journal.for_task(row.id)
    _, unknown, note = journal_summary(rows)
    if row.state in (TaskState.IDLE.value, TaskState.PLANNING.value, TaskState.NEEDS_CLARIFICATION.value):
        note = "The server restarted before this task finished planning. Please send the command again."
    failed = task.model_copy(update={"state": TaskState.FAILED, "updated_at": utc_now(), "error_message": note})
    container.tasks.restore(failed, row.user_id)
    code = "EXECUTION_INTERRUPTED" if row.state in (TaskState.EXECUTING.value, TaskState.WAITING_APPROVAL.value) else "PLANNING_INTERRUPTED"
    await p.tasks.upsert(failed, error_code=code, recovery_note=note, execution_status="UNKNOWN" if unknown else "INTERRUPTED")
    report.failed_interrupted += 1
    await _decide(container, report, row, code)


async def _recover_approvals(container: Any, report: RecoveryReport) -> None:
    p = container.persistence
    for row in await p.approvals.pending():
        approval = ApprovalRequest.model_validate(row.request_json)
        withdrawn = approval.model_copy(update={"status": ApprovalStatus.WITHDRAWN, "resolved_at": utc_now()})
        await p.approvals.save(withdrawn)
        report.approvals_withdrawn += 1
        await container.audit.record("recovery.approval", outcome="WITHDRAWN", user_id=row.user_id, task_id=row.task_id,
                                     session_id=row.session_id, resource_type="approval", resource_id=row.id)


async def _recover_files(container: Any, report: RecoveryReport) -> None:
    store = getattr(container, "files", None)
    p = container.persistence
    if store is None:
        return
    for part in store.root.rglob("*.part"):  # interrupted downloads are never published
        try:
            part.unlink()
            report.partial_files_removed += 1
        except OSError:
            pass
    for row in await p.files.live():
        path = store.path_for(row.session_id, row.id, row.extension)
        if not path.is_file():
            await p.files.mark_deleted(row.id)
            continue
        if row.expires_at is not None and row.expires_at <= utc_now():
            path.unlink(missing_ok=True)
            await p.files.mark_deleted(row.id)
            continue
        meta = DownloadedFile(file_id=row.id, session_id=row.session_id, task_id=row.task_id, original_name=row.original_name,
                              stored_name=f"{row.id}.{row.extension}", extension=row.extension, mime_type=row.mime_type,
                              size_bytes=row.size_bytes, sha256=row.sha256, source_domain=row.source_domain,
                              status=DownloadStatus.COMPLETED, created_at=row.created_at, expires_at=row.expires_at,
                              validation=["restored after restart", f"malware scan: {row.scan_status.replace('_', ' ').lower()}"])
        store.add(meta, path)
        report.files_restored += 1


async def _recover_browser_sessions(container: Any, report: RecoveryReport) -> None:
    from sqlalchemy import update

    from app.database.models import BrowserSessionRecord

    async with container.persistence.db.session() as s:
        result = await s.execute(update(BrowserSessionRecord).where(BrowserSessionRecord.status != "CLOSED").values(status="CLOSED"))
        report.browser_sessions_closed = result.rowcount or 0
