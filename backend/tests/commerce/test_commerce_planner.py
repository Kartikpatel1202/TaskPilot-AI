"""Commerce planning: deterministic steps, requirements, mock quantity regressions, config safety."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.policies.approval_policy import checkpoint_violations
from app.agent.providers.mock_scenarios import classify, parse_products
from app.commerce.commerce_planner import CommercePlanner, requirement_from
from app.commerce.registry import fixture_binding
from app.config import Settings
from app.schemas.intent import IntentClassification, ProductEntity
from app.schemas.product import CommercePlatform, ProductUnit

from ..conftest import make_settings

BINDING = fixture_binding(CommercePlatform.BLINKIT, "http://127.0.0.1:8000")


def products(text: str) -> dict[str, tuple[Any, ...]]:
    return {p["name"]: (p["brand"], p["quantity"], p["unit"]) for p in parse_products(text)}


@pytest.mark.parametrize(("text", "name", "expected"), [
    ("Amul milk 1 litre", "milk", ("Amul", 1.0, "litre")),
    ("2 litre Amul milk", "milk", ("Amul", 2.0, "litre")),
    ("500 ml amul milk", "milk", ("Amul", 500.0, "ml")),
    ("12 eggs", "eggs", (None, 12.0, "piece")),
    ("1 dozen eggs", "eggs", (None, 12.0, "piece")),
    ("ek dozen ande", "eggs", (None, 12.0, "piece")),
    ("2 packets bread", "bread", (None, 2.0, "packet")),
    ("do packet bread", "bread", (None, 2.0, "packet")),
    ("दो लीटर दूध", "milk", (None, 2.0, "litre")),
    ("एक दर्जन अंडे", "eggs", (None, 12.0, "piece")),
    ("aadha kilo paneer", "paneer", (None, 0.5, "kg")),
])
def test_quantity_parsing_english_hindi_hinglish(text: str, name: str, expected: tuple[Any, ...]) -> None:
    assert products(text)[name] == expected


@pytest.mark.parametrize("answer", ["1 litre", "2 litre", "500 ml", "ek litre", "दो लीटर"])
def test_clarification_quantity_answer_is_used_not_asked_again(answer: str) -> None:
    """Phase 3 regression: the mock planner asked for the quantity again after '1 litre'."""
    first = classify({"command": "Blinkit se Amul milk order karo aur payment kar do", "clarifications": [], "language": "hinglish", "session_context": {}})
    assert first["requires_clarification"] and "quantity" in first["missing_information"]
    second = classify({"command": "Blinkit se Amul milk order karo aur payment kar do", "clarifications": [answer], "language": "hinglish", "session_context": {}})
    assert not second["requires_clarification"], second
    assert second["entities"]["products"][0]["quantity"] is not None


def test_variants_specs_budget_and_payment_are_extracted() -> None:
    p = parse_products("Blinkit par 2 litre Amul Taaza milk aur 1 Harvest Gold bread")
    milk = next(x for x in p if x["name"] == "milk")
    bread = next(x for x in p if x["name"] == "bread")
    assert milk["variant"] == "taaza" and bread["brand"] == "Harvest Gold" and bread["variant"] is None
    laptop = parse_products("Amazon par ₹60,000 ke under 16GB RAM aur 512GB SSD wala laptop find karo")[0]
    assert laptop["specs"] == ["16GB RAM", "512GB SSD"] and laptop["max_price"] == 60000
    c = classify({"command": "Blinkit par 12 eggs order karo, cash on delivery", "clarifications": [], "language": "en", "session_context": {}})
    assert c["entities"]["payment_preference"] == "COD" and "place_order" in c["entities"]["requested_actions"]
    u = classify({"command": "Blinkit par 12 eggs order karo, UPI se pay karunga", "clarifications": [], "language": "en", "session_context": {}})
    assert u["entities"]["payment_preference"] == "PREPAID"


def test_brand_variant_correction_follow_up() -> None:
    context = {"active_website": "blinkit.com", "active_intent": "ECOMMERCE_SHOPPING",
               "products": [{"name": "milk", "brand": "Amul", "quantity": 1, "unit": "litre", "variant": "gold"}]}
    c = classify({"command": "Amul Gold nahi, Amul Taaza hi lena", "clarifications": [], "language": "hinglish", "session_context": context})
    assert c["is_follow_up"] and c["entities"]["products"][0]["variant"] == "taaza"


def test_requirement_from_entity_preserves_exact_details() -> None:
    r, notes = requirement_from(ProductEntity(name="milk", brand="Amul", quantity=2, unit="litre", variant="taaza"))
    assert (r.brand, r.quantity, r.unit, r.must_match_brand, r.allow_substitute) == ("Amul", 2.0, ProductUnit.LITER, True, False)
    assert r.preferred_variant == {"line": "taaza"} and not notes
    eggs, _ = requirement_from(ProductEntity(name="eggs", quantity=1, unit="dozen"))
    assert (eggs.quantity, eggs.unit) == (12.0, ProductUnit.PIECE)
    bread, notes = requirement_from(ProductEntity(name="bread"))
    assert bread.unit == ProductUnit.PACK and notes  # an assumption is stated, not hidden
    laptop, _ = requirement_from(ProductEntity(name="laptop", category="laptop", specs=["16GB RAM", "512GB SSD"], max_price=60000))
    assert laptop.required_specs == {"RAM": "16GB", "STORAGE": "512GB"} and str(laptop.max_price) == "60000"


def classification(intent: str, actions: list[str], payment: str | None = None, prods: list[dict[str, Any]] | None = None) -> IntentClassification:
    return IntentClassification.model_validate({
        "intent": intent, "confidence": 0.95, "language": "hinglish", "target_website": "blinkit.fixture.test",
        "entities": {"products": prods if prods is not None else [{"name": "eggs", "quantity": 12, "unit": "piece"}],
                     "requested_actions": actions, "payment_preference": payment},
    })


def ops(plan: Any) -> list[str]:
    return [s.action.operation if s.action.type == "commerce" else s.action.type for s in plan.steps]


def build(c: IntentClassification) -> Any:
    return CommercePlanner(20).build(task_id=uuid4(), session_id=uuid4(), classification=c, binding=BINDING, provider="mock", model="m", history=[])


def test_plans_per_intent() -> None:
    assert ops(build(classification("ECOMMERCE_SHOPPING", ["add_to_cart"]))) == ["open_store", "search_and_add", "verify_cart"]
    assert ops(build(classification("ECOMMERCE_SEARCH", ["search"]))) == ["open_store", "search_products"]
    assert ops(build(classification("ECOMMERCE_CART_REVIEW", ["cart_review"], prods=[]))) == ["open_store", "verify_cart"]
    assert ops(build(classification("ECOMMERCE_CHECKOUT_REVIEW", ["checkout_review"]))) == ["open_store", "verify_cart", "checkout_review"]
    order = build(classification("ECOMMERCE_SHOPPING", ["add_to_cart", "place_order"], payment="COD"))
    assert ops(order) == ["open_store", "search_and_add", "verify_cart", "checkout_review", "place_order"]
    last = order.steps[-1]
    assert last.requires_approval and last.risk_level.value == "CRITICAL" and last.action.payment_preference == "COD"
    assert order.requires_human_approval and not checkpoint_violations(order.steps)
    assert "final approval" in order.user_facing_message


def test_item_steps_are_independent_but_checkout_depends_on_verification() -> None:
    plan = build(classification("ECOMMERCE_SHOPPING", ["add_to_cart", "place_order"],
                                prods=[{"name": "milk", "quantity": 1, "unit": "litre"}, {"name": "eggs", "quantity": 12, "unit": "piece"}]))
    open_id = plan.steps[0].step_id
    items = [s for s in plan.steps if s.action.operation == "search_and_add"]
    assert all(s.depends_on == [open_id] and s.action.continue_on_failure for s in items)
    verify, review, place = plan.steps[3], plan.steps[4], plan.steps[5]
    assert review.depends_on == [verify.step_id] and place.depends_on == [review.step_id]
    assert not verify.action.continue_on_failure and not place.action.continue_on_failure


def test_purchase_safety_settings_cannot_be_weakened() -> None:
    for bad in ({"commerce_require_final_purchase_approval": False}, {"commerce_automated_prepaid_payment": True},
                {"commerce_require_cart_verification": False}, {"commerce_acceptable_match_threshold": 0.95},
                {"commerce_supported_platforms": "BLINKIT,FLIPKART"}):
        with pytest.raises(ValidationError):
            make_settings(**bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", commerce_enable_fixtures=True, agent_allow_mock_in_production=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        make_settings(commerce_exact_match_threshold=1.5)
    assert make_settings().commerce_enable_public_smoke_tests is False
