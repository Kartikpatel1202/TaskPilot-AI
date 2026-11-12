"""PlanExecutor end-to-end through the real app, real Chromium and the local fixture shop.

Fixture site only — no public website is contacted by these tests.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ..conftest import wait_for_execution
from .conftest import (
    click,
    container,
    execute,
    extract,
    install_plan,
    nav,
    page_eval,
    planned_task,
    results,
    stop,
    telemetry_types,
    type_,
    wait_until,
)


def test_mock_planned_demo_flow_adds_exactly_one_item_and_reads_the_cart(client: TestClient) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    assert execute(client, task_id, sid).status_code == 202
    final = wait_for_execution(client, task_id, timeout=90)
    assert final["state"] == "COMPLETED", final
    rows = results(client, task_id)
    assert [r["order"] for r in rows] == sorted(r["order"] for r in rows)  # sequential
    assert all(r["status"] == "SUCCEEDED" for r in rows)
    cart_read = [r for r in rows if r["action_type"] == "extract"][-1]["extracted_data"]
    assert cart_read["source"] == "observed_dom"
    assert any("Amul Taaza" in str(item) and "₹54" in str(item) for item in cart_read["items"])
    # exactly one add-to-cart: localStorage cart holds a single unit of one product
    cart = page_eval(client, sid, "() => JSON.parse(localStorage.getItem('tp-demo-cart') || '{}')")
    assert sum(cart.values()) == 1, cart
    types = telemetry_types(client, sid)
    for expected in (
        "task.execution_started", "task.step_started", "browser.action_started", "browser.action_completed",
        "browser.navigation_completed", "browser.page_updated", "task.execution_completed",
    ):
        assert expected in types, expected
    assert types.index("task.execution_started") < types.index("task.execution_completed")


def test_selector_failure_fails_the_step_and_skips_the_rest(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [
        nav(fixture_origin, "index.html"),
        click("Wishlist heart icon", "button", "Wishlist"),
        extract("search results", ["name"]),
        stop(),
    ])
    execute(client, task_id, sid)
    final = wait_for_execution(client, task_id, timeout=60)
    assert final["state"] == "FAILED"
    statuses = [r["status"] for r in results(client, task_id)]
    assert statuses == ["SUCCEEDED", "FAILED", "SKIPPED", "SKIPPED"]
    assert results(client, task_id)[1]["error_code"] == "SELECTOR_NOT_FOUND"


def test_ambiguous_target_is_refused_without_clicking(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [
        nav(fixture_origin, "ambiguous.html"),
        click("Add button for Amul Taaza Toned Milk 1 litre", "button", "Add"),
        stop(),
    ])
    execute(client, task_id, sid)
    assert wait_for_execution(client, task_id, timeout=60)["state"] == "FAILED"
    assert results(client, task_id)[1]["error_code"] == "SELECTOR_AMBIGUOUS"
    assert page_eval(client, sid, "() => document.querySelectorAll('[data-clicked]').length") == 0


def test_checkout_is_blocked_before_any_approval_and_nothing_is_purchased(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    steps = install_plan(client, task_id, [
        nav(fixture_origin, "cart.html"),
        click("Place order and pay button", "button", "Place order and pay"),
        stop(),
    ])
    assert steps[1].action.type == "request_approval"  # the planner rules gate it ...
    execute(client, task_id, sid)
    final = wait_for_execution(client, task_id, timeout=60)
    assert final["state"] == "CANCELLED"  # ... and the runtime policy refuses it outright
    rows = results(client, task_id)
    assert rows[1]["status"] == "BLOCKED" and rows[1]["error_code"] == "SENSITIVE_ACTION_BLOCKED"
    assert [r["status"] for r in rows[2:]] == ["SKIPPED", "SKIPPED"]
    assert container(client).approvals._approvals == {} or all(
        str(a.task_id) != task_id for a in container(client).approvals._approvals.values()
    )  # no approval was even requested
    assert page_eval(client, sid, "() => document.getElementById('purchase-log').dataset.purchased") == "no"
    assert "task.step_blocked" in telemetry_types(client, sid)


def test_search_typing_submits_and_extracts_structured_results(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [
        nav(fixture_origin, "index.html"),
        type_("Search box", "laptop"),
        extract("search results", ["name", "price"]),
        stop(),
    ])
    execute(client, task_id, sid)
    assert wait_for_execution(client, task_id, timeout=60)["state"] == "COMPLETED"
    data = results(client, task_id)[2]["extracted_data"]
    assert data["items"][0]["name"].startswith("Acer Aspire 7") and data["items"][0]["price"].startswith("₹")


def test_stop_cancels_a_running_execution(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    # extract on an empty search page waits for rendering (bounded), giving us time to stop
    install_plan(client, task_id, [
        nav(fixture_origin, "index.html"),
        extract("Wishlist heart drawer", ["name"]),
        nav(fixture_origin, "cart.html"),
        stop(),
    ])
    execute(client, task_id, sid)
    wait_until(lambda: client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "EXECUTING")
    response = client.post(f"/api/v1/tasks/{task_id}/stop", json={"session_id": sid, "reason": "Changed my mind"})
    assert response.status_code == 202 and response.json()["status"] in ("STOPPING", "CANCELLED")
    final = wait_for_execution(client, task_id, timeout=60)
    assert final["state"] == "CANCELLED"
    statuses = [r["status"] for r in results(client, task_id)]
    assert "SKIPPED" in statuses and statuses[-1] == "SKIPPED"
    assert "task.execution_cancelled" in telemetry_types(client, sid)


def test_browser_crash_fails_the_execution_cleanly(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [
        nav(fixture_origin, "index.html"),
        extract("Wishlist heart drawer", ["name"]),
        stop(),
    ])
    execute(client, task_id, sid)
    wait_until(lambda: client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "EXECUTING")

    async def kill() -> None:
        session = container(client).browser.peek_session(UUID(sid))
        await session.context.close()  # the page/context dies under the running executor

    client.portal.call(kill)  # type: ignore[union-attr]
    final = wait_for_execution(client, task_id, timeout=60)
    assert final["state"] in ("FAILED", "CANCELLED")
    assert final["state"] != "COMPLETED"
