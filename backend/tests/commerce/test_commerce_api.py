"""End-to-end commerce workflows through the real app, real Chromium and the LOCAL fixtures.

Covers the Phase 4 acceptance scenarios on fixtures only — no public website is contacted
and no real order is ever placed (fixture "orders" are fake confirmations).
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from ..conftest import wait_for_execution
from .conftest import (
    browser_eval,
    container,
    pending_purchase_approval,
    pending_selection,
    planned,
    prime,
    results,
    run,
    summary,
    wait_until,
)


def decide(client: TestClient, approval_id: object, decision: str) -> None:
    r = client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": decision})
    assert r.status_code == 200, r.text


def events(client: TestClient, session_id: str) -> list[tuple[str, dict]]:
    from uuid import UUID

    history, _ = container(client).ws_manager.replay(UUID(session_id), None)
    return [(e.type.value, e.data) for e in history]


# ---------------------------------------------------------------------- Scenario 1: multi-product cart


def test_blinkit_multi_product_cart_is_verified_and_nothing_is_ordered(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    task_id, plan = planned(cclient, "Kamlesh Bhai, fixture Blinkit par 2 litre Amul Taaza milk, 1 Harvest Gold bread packet aur 12 eggs cart mein add karo", sid)
    assert plan["intent"] == "ECOMMERCE_SHOPPING" and plan["target_website"] == "blinkit.fixture.test"
    assert [s["action"]["operation"] for s in plan["steps"]] == ["open_store", "search_and_add", "search_and_add", "search_and_add", "verify_cart"]
    assert any("TEST FIXTURE" in a for a in plan["assumptions"])
    run(cclient, task_id, sid)
    assert wait_for_execution(cclient, task_id, timeout=120)["state"] == "COMPLETED"
    s = summary(cclient, task_id, sid)
    assert s["status"] == "CART_READY" and s["verification"]["status"] == "VERIFIED"
    assert {(i["product_name"], i["quantity"]) for i in s["cart"]["items"]} == {
        ("Amul Taaza Toned Fresh Milk", 2.0), ("Harvest Gold White Bread", 1.0), ("Farm Fresh White Eggs", 1.0)}
    assert s["cart"]["total"] == "252.00" and s["order"] is None
    assert "No order placed" in results(cclient, task_id)[-1]["message"]
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") is None
    types = [t for t, _ in events(cclient, sid)]
    for expected in ("commerce.session_detected", "commerce.search_started", "commerce.products_found", "commerce.product_selected",
                     "commerce.cart_update_started", "commerce.cart_item_added", "commerce.cart_verification_completed"):
        assert expected in types, expected
    found = next(d for t, d in events(cclient, sid) if t == "commerce.products_found")
    assert found["candidate_count"] >= 2 and found["exact_match_count"] >= 1
    # cart endpoints return the observed cart; quantities can be changed and are re-verified
    cart = cclient.get(f"/api/v1/browser/sessions/{sid}/commerce/cart").json()
    assert cart["platform"] == "BLINKIT" and cart["item_count"] == 3
    eggs = next(i for i in cart["items"] if "Eggs" in i["product_name"])
    updated = cclient.post(f"/api/v1/browser/sessions/{sid}/commerce/cart/items/{eggs['item_id']}/quantity",
                           json={"session_id": sid, "quantity": 2})
    assert updated.status_code == 200, updated.text
    assert next(i["quantity"] for i in updated.json()["items"] if "Eggs" in i["product_name"]) == 2.0
    assert {i["product_name"] for i in updated.json()["items"]} >= {"Amul Taaza Toned Fresh Milk", "Harvest Gold White Bread"}
    refreshed = cclient.post(f"/api/v1/browser/sessions/{sid}/commerce/cart/refresh", json={"session_id": sid})
    assert refreshed.status_code == 200 and refreshed.json()["item_count"] == 3
    assert cclient.post(f"/api/v1/browser/sessions/{sid}/commerce/cart/refresh", json={"session_id": str(uuid4())}).status_code == 403


# ---------------------------------------------------------------------- Scenario 3: ambiguous product -> user choice


def test_ambiguous_product_waits_for_the_users_choice(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    task_id, _ = planned(cclient, "fixture Blinkit par 1 bread packet add karo", sid)
    run(cclient, task_id, sid)
    s = pending_selection(cclient, task_id, sid)
    pending = s["pending_selection"]
    assert cclient.get(f"/api/v1/tasks/{task_id}").json()["state"] == "WAITING_APPROVAL"
    options = {c["candidate_id"]: c["product_name"] for r in s["requirements"] for c in r["candidates"]}
    assert {options[i] for i in pending["candidate_ids"]} == {"Harvest Gold White Bread", "Britannia 100% Whole Wheat Bread"}
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:cart')") in (None, "{}")  # nothing chosen yet -> nothing added
    britannia = next(i for i in pending["candidate_ids"] if options[i].startswith("Britannia"))
    bad = cclient.post(f"/api/v1/tasks/{task_id}/commerce/selection", json={"session_id": str(uuid4()), "selection_id": pending["selection_id"], "candidate_id": britannia})
    assert bad.status_code == 403
    ok = cclient.post(f"/api/v1/tasks/{task_id}/commerce/selection", json={"session_id": sid, "selection_id": pending["selection_id"], "candidate_id": britannia})
    assert ok.status_code == 202
    assert wait_for_execution(cclient, task_id, timeout=90)["state"] == "COMPLETED"
    items = summary(cclient, task_id, sid)["cart"]["items"]
    assert [(i["product_name"], i["quantity"]) for i in items] == [("Britannia 100% Whole Wheat Bread", 1.0)]
    assert "commerce.product_ambiguous" in [t for t, _ in events(cclient, sid)]


# ---------------------------------------------------------------------- Scenario 4 + 5: existing cart, partial availability


def test_existing_cart_quantity_is_topped_up_and_unrelated_items_kept(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    browser_eval(cclient, sid, "() => localStorage.setItem('fxb:cart', JSON.stringify({'amul-taaza-1l': 1, 'apple-1kg': 1}))")
    task_id, _ = planned(cclient, "fixture Blinkit par 2 litre Amul Taaza milk add karo", sid)
    run(cclient, task_id, sid)
    assert wait_for_execution(cclient, task_id, timeout=90)["state"] == "COMPLETED"
    rows = results(cclient, task_id)
    assert "cart quantity 1 → 2" in rows[1]["message"]  # only the missing litre was added
    cart = json.loads(browser_eval(cclient, sid, "() => localStorage.getItem('fxb:cart')"))
    assert cart == {"amul-taaza-1l": 2, "apple-1kg": 1}
    s = summary(cclient, task_id, sid)
    assert any("left unchanged" in w for w in s["verification"]["warnings"])


def test_partial_availability_is_reported_never_as_success(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    task_id, _ = planned(cclient, "fixture Blinkit par 1 litre Amul Taaza milk aur 200 g Amul paneer add karo", sid)
    run(cclient, task_id, sid)
    final = wait_for_execution(cclient, task_id, timeout=90)
    assert final["state"] == "FAILED"
    rows = results(cclient, task_id)
    assert [r["status"] for r in rows] == ["SUCCEEDED", "SUCCEEDED", "FAILED", "FAILED"]
    assert rows[2]["error_code"] == "COMMERCE_PRODUCT_NOT_FOUND" and "unavailable" in rows[2]["message"]
    s = summary(cclient, task_id, sid)
    assert s["verification"]["status"] == "PARTIAL" and s["status"] == "PARTIAL"
    assert any("paneer" in m.lower() for m in s["verification"]["missing_items"])
    assert {(i["product_name"], i["quantity"]) for i in s["cart"]["items"]} == {("Amul Taaza Toned Fresh Milk", 1.0)}
    assert "commerce.product_unavailable" in [t for t, _ in events(cclient, sid)]
    assert "commerce.cart_verification_failed" in [t for t, _ in events(cclient, sid)]


# ---------------------------------------------------------------------- Scenario 8 + 6: COD with exact approval


COD_COMMAND = "fixture Blinkit par 1 litre Amul Taaza milk aur 12 eggs order karo, cash on delivery"


def test_cod_rejected_places_no_order_and_keeps_the_cart(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    task_id, plan = planned(cclient, COD_COMMAND, sid)
    ops = [s["action"]["operation"] for s in plan["steps"]]
    assert ops[-3:] == ["verify_cart", "checkout_review", "place_order"]
    assert not any(s["action"]["type"] == "request_approval" for s in plan["steps"])  # the exact-order approval replaces a generic gate
    assert plan["steps"][-1]["requires_approval"] and plan["steps"][-1]["action"]["payment_preference"] == "COD"
    run(cclient, task_id, sid)
    approval = pending_purchase_approval(cclient, task_id)
    p = approval.purchase
    assert p.payment_method.value == "COD" and str(p.final_total) == "181.00" and str(p.subtotal) == "152.00" and p.masked_delivery_address == "Home: •••, Gurugram 122•••"
    assert [i.name for i in p.items] == ["Amul Taaza Toned Fresh Milk", "Farm Fresh White Eggs"]
    assert summary(cclient, task_id, sid)["order"]["status"] == "APPROVAL_PENDING"
    decide(cclient, approval.approval_id, "REJECT")
    final = wait_for_execution(cclient, task_id, timeout=60)
    assert final["state"] == "CANCELLED"
    order = cclient.get(f"/api/v1/tasks/{task_id}/commerce/order-status", params={"session_id": sid}).json()
    assert order["status"] == "REJECTED" and order["order_reference"] is None
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") is None
    assert json.loads(browser_eval(cclient, sid, "() => localStorage.getItem('fxb:cart')")) == {"amul-taaza-1l": 1, "eggs-12": 1}


def test_cod_approved_submits_once_and_price_change_requires_fresh_approval(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    task_id, _ = planned(cclient, COD_COMMAND, sid)
    run(cclient, task_id, sid)
    first = pending_purchase_approval(cclient, task_id)
    assert str(first.purchase.final_total) == "181.00"
    # The website's price changes after the user saw the review (Scenario 6).
    browser_eval(cclient, sid, "() => localStorage.setItem('fxb:prices', JSON.stringify({'amul-taaza-1l': 60}))")
    decide(cclient, first.approval_id, "APPROVE")
    second = wait_until(lambda: (a := pending_purchase_approval(cclient, task_id)) and a.approval_id != first.approval_id and a)
    assert str(second.purchase.final_total) == "185.00"  # fresh approval for the new, observed total
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") is None  # nothing submitted on the stale approval
    changes = [d for t, d in events(cclient, sid) if t == "commerce.price_changed"]
    assert changes and changes[-1]["approval_invalidated"] is True and changes[-1]["difference"] == "4.00"
    decide(cclient, second.approval_id, "APPROVE")
    final = wait_for_execution(cclient, task_id, timeout=60)
    assert final["state"] == "COMPLETED"
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") == "1"  # exactly one submission
    order = cclient.get(f"/api/v1/tasks/{task_id}/commerce/order-status", params={"session_id": sid}).json()
    assert order["status"] == "CONFIRMED" and order["order_reference"] == "FXB-100001"
    assert "FXB-100001" in results(cclient, task_id)[-1]["message"]
    execution = cclient.get(f"/api/v1/tasks/{task_id}/execution").json()
    assert "one cash-on-delivery order was placed" in execution["message"] and "No payment or order" not in execution["message"]
    types = [t for t, _ in events(cclient, sid)]
    assert types.count("commerce.purchase_approval_required") == 2 and "commerce.order_confirmed" in types
    # the same approval can never be used again
    assert container(cclient).commerce.purchase.was_submitted(__import__("uuid").UUID(task_id))
    # no full address or credentials in telemetry
    blob = json.dumps([d for _, d in events(cclient, sid)], ensure_ascii=False)
    assert "Fixture Lane" not in blob and "Flat 12" not in blob


# ---------------------------------------------------------------------- Scenario 7: prepaid handoff; COD unavailable; login wall


def test_prepaid_payment_is_handed_to_the_user(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1")
    task_id, _ = planned(cclient, "fixture Blinkit par 12 eggs order karo, UPI se payment karunga", sid)
    run(cclient, task_id, sid)
    assert wait_for_execution(cclient, task_id, timeout=90)["state"] == "COMPLETED"
    order = cclient.get(f"/api/v1/tasks/{task_id}/commerce/order-status", params={"session_id": sid}).json()
    assert order["status"] == "PAYMENT_HANDOFF"
    assert "No payment was made by TaskPilot" in results(cclient, task_id)[-1]["message"]
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:paid_attempt')") is None
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") is None
    assert not [a for a in container(cclient).approvals._approvals.values() if a.purchase is not None]
    handoff = next(d for t, d in events(cclient, sid) if t == "commerce.payment_handoff")
    assert handoff["status"] == "USER_ACTION_REQUIRED"


def test_cod_unavailable_falls_back_to_a_manual_decision(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1&cod=0")
    task_id, _ = planned(cclient, "fixture Blinkit par 12 eggs order karo, cash on delivery", sid)
    run(cclient, task_id, sid)
    assert wait_for_execution(cclient, task_id, timeout=90)["state"] == "COMPLETED"
    order = cclient.get(f"/api/v1/tasks/{task_id}/commerce/order-status", params={"session_id": sid}).json()
    assert order["status"] == "PAYMENT_HANDOFF" and "not available" in order["message"]
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxb:submits')") is None


def test_checkout_login_wall_stops_safely(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1&login=0")
    task_id, _ = planned(cclient, "fixture Blinkit par 12 eggs order karo, cash on delivery", sid)
    run(cclient, task_id, sid)
    final = wait_for_execution(cclient, task_id, timeout=90)
    assert final["state"] == "CANCELLED"
    review = results(cclient, task_id)[-2]
    assert review["status"] == "BLOCKED" and review["error_code"] == "COMMERCE_SESSION_REQUIRED"


def test_location_required_stops_before_shopping(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "blinkit", "reset=1&location=0")
    task_id, _ = planned(cclient, "fixture Blinkit par 12 eggs add karo", sid)
    run(cclient, task_id, sid)
    assert wait_for_execution(cclient, task_id, timeout=60)["state"] == "CANCELLED"
    assert results(cclient, task_id)[0]["error_code"] == "COMMERCE_LOCATION_REQUIRED"
    assert "commerce.location_required" in [t for t, _ in events(cclient, sid)]


# ---------------------------------------------------------------------- Scenario 2: Amazon search; Scenario 9: isolation


def test_amazon_budget_laptop_search_shows_only_matching_listings(cclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    prime(cclient, sid, fixture_origin, "amazon", "reset=1")
    task_id, plan = planned(cclient, "fixture Amazon par 60000 ke under 16GB RAM aur 512GB SSD wala laptop find karo", sid)
    req = plan["steps"][1]["action"]["requirement"]
    assert plan["intent"] == "ECOMMERCE_SEARCH" and req["max_price"] == "60000"
    assert req["required_specs"] == {"RAM": "16GB", "STORAGE": "512GB"}
    run(cclient, task_id, sid)
    assert wait_for_execution(cclient, task_id, timeout=90)["state"] == "COMPLETED"
    step = results(cclient, task_id)[1]
    names = [i["name"] for i in step["extracted_data"]["items"]]
    assert sorted(n.split()[0] for n in names) == ["ASUS", "Acer"]
    assert all(i["price"] for i in step["extracted_data"]["items"])
    assert "Nothing was added to the cart" in step["message"]
    assert browser_eval(cclient, sid, "() => localStorage.getItem('fxa:cart')") in (None, "{}")


def test_sessions_are_isolated(cclient: TestClient, fixture_origin: str) -> None:
    a, b = str(uuid4()), str(uuid4())
    prime(cclient, a, fixture_origin, "blinkit", "reset=1")
    prime(cclient, b, fixture_origin, "amazon", "reset=1")
    ta, _ = planned(cclient, "fixture Blinkit par 12 eggs add karo", a)
    tb, _ = planned(cclient, "fixture Amazon par 1 Logitech mouse add karo", b)
    run(cclient, ta, a)
    run(cclient, tb, b)
    wait_for_execution(cclient, ta, timeout=120)
    wait_for_execution(cclient, tb, timeout=120)
    cart_a = cclient.get(f"/api/v1/browser/sessions/{a}/commerce/cart").json()
    assert cart_a["platform"] == "BLINKIT" and [i["product_name"] for i in cart_a["items"]] == ["Farm Fresh White Eggs"]
    assert cclient.get(f"/api/v1/tasks/{ta}/commerce/summary", params={"session_id": b}).status_code == 403
    assert all(e[1].get("platform") in (None, "BLINKIT") for e in events(cclient, a) if e[0].startswith("commerce."))
    assert all(e[1].get("platform") in (None, "AMAZON_IN") for e in events(cclient, b) if e[0].startswith("commerce."))


# ---------------------------------------------------------------------- REST validation


def test_rest_errors_never_invent_data(cclient: TestClient) -> None:
    sid = str(uuid4())
    assert cclient.get(f"/api/v1/browser/sessions/{sid}/commerce/cart").json()["code"] == "BROWSER_SESSION_NOT_FOUND"
    assert cclient.get(f"/api/v1/tasks/{uuid4()}/commerce/summary").status_code == 404
    assert cclient.get(f"/api/v1/tasks/{uuid4()}/commerce/checkout").status_code == 404
    r = cclient.post(f"/api/v1/tasks/{uuid4()}/commerce/checkout/review", json={"session_id": sid})
    assert r.status_code == 404 and r.json()["code"] == "BROWSER_SESSION_NOT_FOUND"
    sel = cclient.post(f"/api/v1/tasks/{uuid4()}/commerce/selection", json={"session_id": sid, "selection_id": str(uuid4()), "candidate_id": None})
    assert sel.status_code == 404
