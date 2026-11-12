"""Idempotency + execution journal (Scenarios 6 and 8). A "duplicate delivery" re-runs the SAME plan
(same idempotency keys) through the real executor after the journal was put back into the state a crash
right after the website action would leave (step RUNNING — success never recorded)."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.database.models import ActionLifecycle
from app.database.repositories.execution_repository import idempotency_key
from app.execution.execution_queue import ExecutionJob
from app.resilience.idempotency import is_mutating
from app.schemas.action import ClickAction, NavigateAction
from app.schemas.task import TaskState

from ..commerce.conftest import (  # noqa: F401
    cclient,
    browser_eval,
    container,
    pending_purchase_approval,
    planned,
    prime,
    run,
)
from ..commerce.test_commerce_api import decide
from ..conftest import wait_for_execution


def test_mutation_classification() -> None:
    assert is_mutating(ClickAction(type="click", target_description="Add"))
    assert not is_mutating(NavigateAction(type="navigate", url="https://example.com", purpose="open"))


async def test_journal_key_is_unique_per_step_version(tmp_path) -> None:  # noqa: ANN001
    from app.database.dependencies import Persistence
    from app.database.models import TaskRecord
    from app.database.session import Database
    from app.schemas.common import utc_now

    db = Database("sqlite+aiosqlite://")
    await db.create_all()
    p = Persistence(db)
    task, plan, step = uuid4(), uuid4(), uuid4()
    async with db.session() as s:
        s.add(TaskRecord(id=task, session_id=uuid4(), command="x", input_mode="TEXT", state="EXECUTING", created_at=utc_now(), updated_at=utc_now()))
    key = idempotency_key(task, plan, step)
    _, created = await p.journal.prepare(key=key, task_id=task, plan_id=plan, step_id=step, order=1, action_type="click", mutating=True, worker_id="w")
    _, again = await p.journal.prepare(key=key, task_id=task, plan_id=plan, step_id=step, order=1, action_type="click", mutating=True, worker_id="w")
    assert created and not again
    await db.dispose()


def _redeliver(client: TestClient, task_id: str, session_id: str, rewind: str) -> None:
    """Put the journal row of `rewind` steps back to RUNNING and deliver the same execution job again."""
    c = container(client)
    record = c.planning._store.get(UUID(task_id))
    plan = record.plan

    async def go() -> None:
        for step in plan.steps:
            kind = step.action.type if step.action.type != "commerce" else f"commerce:{step.action.operation}"
            if kind == rewind:
                await c.persistence.journal.mark(idempotency_key(UUID(task_id), plan.plan_id, step.step_id), ActionLifecycle.RUNNING)
        task = await c.tasks.get_task(UUID(task_id))
        c.tasks.restore(task.model_copy(update={"state": TaskState.PLANNED}), c.tasks.owner_of(UUID(task_id)))
        c.execution._records.pop(UUID(task_id), None)
        await c.execution.prepare_job(ExecutionJob(UUID(task_id), UUID(session_id)))
        await c.execution.run_job(ExecutionJob(UUID(task_id), UUID(session_id)))

    client.portal.call(go)  # type: ignore[union-attr]


def test_scenario6_duplicate_delivery_never_places_a_second_cod_order(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    task_id, _ = planned(cclient, "fixture Blinkit par 12 eggs order karo, cash on delivery", sid)
    run(cclient, task_id, sid)
    decide(cclient, pending_purchase_approval(cclient, task_id).approval_id, "APPROVE")
    assert wait_for_execution(cclient, task_id, timeout=90)["state"] == "COMPLETED"
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") == "1"
    cart_before = browser_eval(cclient, sid, "() => localStorage.getItem('fxb:cart')")
    # crash right after the website accepted the order (success never recorded) -> the job is delivered again
    _redeliver(cclient, task_id, sid, rewind="commerce:place_order")
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") == "1"  # still exactly one order
    summary = cclient.get(f"/api/v1/tasks/{task_id}/execution").json()
    last = summary["results"][-1]
    assert last["error_code"] == "ACTION_STATE_UNKNOWN" and summary["status"] in ("FAILED", "CANCELLED")
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:cart')") == cart_before  # add steps were not repeated
    added = [r for r in summary["results"] if "not repeated" in r["message"]]
    assert added, "already-succeeded cart steps are reported, not re-executed"


def test_scenario8_interrupted_gmail_save_is_reconciled_without_duplicates(fixture_origin: str, tmp_path) -> None:  # noqa: ANN001
    from app.main import create_app

    from ..integrations.conftest import integration_settings
    from ..integrations.conftest import planned as iplanned
    from ..integrations.conftest import prime as iprime

    with TestClient(create_app(integration_settings(fixture_origin, tmp_path / "dl"))) as client:
        sid = str(uuid4())
        iprime(client, sid, fixture_origin, "gmail", "index.html?reset=1")
        task_id, _ = iplanned(client, "Draft an email to hr@example.com about leave on fixture gmail", sid)
        run(client, task_id, sid)
        assert wait_for_execution(client, task_id, timeout=90)["state"] == "COMPLETED"
        drafts = "() => JSON.parse(localStorage.getItem('fx_gmail_drafts') || '[]').length"
        assert browser_eval(client, sid, drafts) == 1
        _redeliver(client, task_id, sid, rewind="gmail_create_draft")
        result = client.get(f"/api/v1/tasks/{task_id}/execution").json()["results"][-1]
        assert result["status"] == "SUCCEEDED" and "not duplicated" in result["message"]
        assert browser_eval(client, sid, drafts) == 1  # no second draft
        assert browser_eval(client, sid, "() => Number(localStorage.getItem('fx_gmail_sent_clicks') || '0')") == 0  # never sent
        assert json.dumps(result).count("NOT been sent") == 1
