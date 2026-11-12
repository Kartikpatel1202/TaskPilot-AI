"""Planner conversion, validation rules, URL policy, risk classification, approvals and registry."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.agent.llm_runner import StructuredLLMRunner
from app.agent.planner import Planner
from app.agent.policies.approval_policy import apply_risk_and_approvals, checkpoint_violations
from app.agent.policies.risk_classifier import classify_risk
from app.agent.policies.url_policy import UrlPolicyError, validate_url
from app.agent.tools import UnknownToolError, build_default_registry
from app.agent.tools.registry import AgentTool, DuplicateToolError
from app.agent.validation import PlanValidationError, PlanValidator
from app.schemas.action import ClickAction, NavigateAction, RequestApprovalAction, StopAction
from app.schemas.approval import RiskLevel
from app.schemas.intent import IntentClassification, IntentType
from app.schemas.memory import PlanningContext
from app.schemas.plan import PlanDraft, PlannedAction

from .conftest import ScriptedProvider

TASK, SESSION = uuid4(), uuid4()
SHOPPING = IntentClassification(intent=IntentType.ECOMMERCE_SHOPPING, confidence=0.9, target_website="blinkit.com")


def step(order: int, action: dict[str, Any], risk: str = "LOW", deps: list[int] | None = None, approval: bool = False) -> dict[str, Any]:
    return {
        "order": order, "action": action, "description": f"Step {order}", "expected_outcome": "ok",
        "risk_level": risk, "requires_approval": approval, "depends_on_orders": deps if deps is not None else ([order - 1] if order > 1 else []),
    }


NAV = {"type": "navigate", "url": "https://blinkit.com", "purpose": "Open Blinkit"}
ADD = {"type": "click", "target_description": "Add to cart button", "role_hint": "button", "accessible_name": "Add", "text_hint": None}
PAY = {"type": "click", "target_description": "Place order and pay button", "role_hint": "button", "accessible_name": None, "text_hint": None}


def draft(steps: list[dict[str, Any]], status: str = "READY", **extra: Any) -> dict[str, Any]:
    return {"status": status, "summary": "s", "user_facing_message": "Plan ready.", "confidence": 0.9, "assumptions": [],
            "clarification_question": extra.get("question"), "missing_information": [], "steps": steps}


def planner(provider: ScriptedProvider | None = None, max_steps: int = 25, retries: int = 1) -> Planner:
    runner = StructuredLLMRunner(provider or ScriptedProvider(), timeout=5, max_tokens=100, max_retries=retries, retry_base_delay=0)
    return Planner(runner, build_default_registry(), max_steps=max_steps, max_retries=retries)


def to_plan(steps: list[dict[str, Any]], **kw: Any):  # type: ignore[no-untyped-def]
    return planner().to_plan(PlanDraft.model_validate(draft(steps, **kw)), task_id=TASK, session_id=SESSION,
                             classification=SHOPPING, provider="fake", model="m", history=[])


def errors_for(plan: Any, max_steps: int = 25) -> list[str]:
    return PlanValidator(build_default_registry(), max_steps).validate(plan, task_id=TASK, session_id=SESSION).errors


# ---------------------------------------------------------------------- happy path


def test_valid_structured_plan_passes() -> None:
    plan = to_plan([step(1, NAV), step(2, ADD, "MEDIUM"), step(3, {"type": "stop", "reason": "done"})])
    assert errors_for(plan) == []
    assert [s.order for s in plan.steps] == [1, 2, 3]
    assert plan.steps[1].depends_on == [plan.steps[0].step_id]
    assert len({s.step_id for s in plan.steps}) == 3


async def test_generate_retries_invalid_plan_then_succeeds() -> None:
    bad = draft([step(1, {"type": "navigate", "url": "http://localhost:8000", "purpose": "x"})])
    good = draft([step(1, NAV)])
    provider = ScriptedProvider({"PlanDraft": [bad, good]})
    plan = await planner(provider).generate(task_id=TASK, session_id=SESSION, command="c", clarifications=[], classification=SHOPPING,
                                            context=PlanningContext(), history=[])
    assert provider.calls == ["PlanDraft", "PlanDraft"]
    assert plan.steps[0].action.url == "https://blinkit.com"  # type: ignore[union-attr]


async def test_generate_gives_up_after_retry_limit() -> None:
    bad = draft([step(1, {"type": "navigate", "url": "file:///etc/passwd", "purpose": "x"})])
    provider = ScriptedProvider({"PlanDraft": [bad]})
    with pytest.raises(PlanValidationError):
        await planner(provider, retries=1).generate(task_id=TASK, session_id=SESSION, command="c", clarifications=[],
                                                    classification=SHOPPING, context=PlanningContext(), history=[])
    assert len(provider.calls) == 2


# ---------------------------------------------------------------------- schema-level rejection


@pytest.mark.parametrize(
    "bad_step",
    [
        step(1, {"type": "execute_python", "code": "import os"}),  # incorrect action type
        step(1, {"type": "navigate", "purpose": "missing url"}),  # missing mandatory field
        step(1, {"type": "extract", "target_description": "x", "fields": []}),  # empty fields
    ],
)
def test_malformed_actions_fail_schema_validation(bad_step: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PlanDraft.model_validate(draft([bad_step]))


# ---------------------------------------------------------------------- validator rules


def test_invalid_sequence_order_is_rejected() -> None:
    plan = to_plan([step(1, NAV), step(3, ADD, "MEDIUM", deps=[1])])
    assert any("sequential" in e for e in errors_for(plan))


def test_duplicate_step_ids_are_rejected() -> None:
    plan = to_plan([step(1, NAV), step(2, ADD, "MEDIUM")])
    dup = plan.model_copy(update={"steps": [plan.steps[0], plan.steps[1].model_copy(update={"step_id": plan.steps[0].step_id})]})
    assert any("unique" in e for e in errors_for(dup))


def test_unknown_and_forward_dependencies_are_rejected() -> None:
    unknown = to_plan([step(1, NAV), step(2, ADD, "MEDIUM", deps=[7])])
    assert any("unknown step" in e for e in errors_for(unknown))
    forward = to_plan([step(1, NAV, deps=[2]), step(2, ADD, "MEDIUM", deps=[])])
    assert any("later step" in e for e in errors_for(forward))


def test_circular_dependencies_are_rejected() -> None:
    plan = to_plan([step(1, NAV), step(2, ADD, "MEDIUM")])
    a, b = plan.steps
    cyclic = plan.model_copy(update={"steps": [a.model_copy(update={"depends_on": [b.step_id]}), b]})
    assert any("circular" in e for e in errors_for(cyclic))


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi", "ftp://example.com", "http://localhost:3000",
     "http://127.0.0.1", "http://10.0.0.5/admin", "http://192.168.1.1", "http://169.254.169.254/latest", "http://[::1]/",
     "https://user:pass@example.com", "http://2130706433", "http://0x7f.0.0.1", "http://intranet", "https://printer.local"],
)
def test_url_policy_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(UrlPolicyError):
        validate_url(url)
    plan = to_plan([step(1, {"type": "navigate", "url": url, "purpose": "x"})])
    assert any("navigation blocked" in e for e in errors_for(plan))


def test_url_policy_normalises_safe_urls() -> None:
    assert validate_url("HTTPS://WWW.Blinkit.COM./search?q=milk#frag") == "https://www.blinkit.com/search?q=milk"
    assert validate_url("https://xn--bcher-kva.example/") == "https://xn--bcher-kva.example/"


def test_excessive_number_of_actions_is_rejected() -> None:
    plan = to_plan([step(i, NAV) for i in range(1, 8)])
    assert any("maximum" in e for e in errors_for(plan, max_steps=5))


def test_empty_ready_plan_is_rejected_but_chat_is_allowed() -> None:
    assert any("at least one step" in e for e in errors_for(to_plan([])))
    chat = to_plan([]).model_copy(update={"intent": IntentType.GENERAL_CHAT})
    assert errors_for(chat) == []


def test_clarification_plan_must_have_question_and_no_steps() -> None:
    plan = to_plan([], status="NEEDS_CLARIFICATION", question="Which brand?")
    assert errors_for(plan) == [] and plan.clarification_question == "Which brand?"
    no_q = plan.model_copy(update={"clarification_question": None})
    assert any("clarification question" in e for e in errors_for(no_q))


def test_stop_must_be_last() -> None:
    plan = to_plan([step(1, NAV), step(2, {"type": "stop", "reason": "x"}), step(3, NAV)])
    assert any("final step" in e for e in errors_for(plan))


def test_typing_credentials_is_never_planned() -> None:
    plan = to_plan([step(1, NAV), step(2, {"type": "type", "target_description": "Card number field", "text": "4111", "clear_first": True, "sensitive": False})])
    assert any("payment details" in e for e in errors_for(plan))


# ---------------------------------------------------------------------- risk + approvals


def test_risk_incorrectly_classified_by_llm_is_raised() -> None:
    plan = to_plan([step(1, NAV), step(2, PAY, "LOW")])  # model claims LOW
    pay = plan.steps[-1]
    assert pay.risk_level == RiskLevel.CRITICAL and pay.requires_approval
    assert errors_for(plan) == []


def test_risk_is_never_lowered() -> None:
    assert classify_risk(ClickAction(type="click", target_description="Open menu"), RiskLevel.HIGH) == RiskLevel.HIGH
    assert classify_risk(NavigateAction(type="navigate", url="https://a.com", purpose="x"), RiskLevel.LOW) == RiskLevel.LOW


@pytest.mark.parametrize(
    ("target", "expected"),
    [("Add to cart button", "MEDIUM"), ("Send button", "HIGH"), ("Submit form button", "HIGH"),
     ("Place order button", "CRITICAL"), ("Pay now", "CRITICAL"), ("Delete account", "CRITICAL"), ("Search button", "LOW")],
)
def test_deterministic_risk_rules(target: str, expected: str) -> None:
    assert classify_risk(ClickAction(type="click", target_description=target), RiskLevel.LOW).value == expected


def test_missing_approval_checkpoint_is_inserted() -> None:
    plan = to_plan([step(1, NAV), step(2, ADD, "MEDIUM"), step(3, PAY, "CRITICAL", approval=True)])
    kinds = [s.action.type for s in plan.steps]
    assert kinds == ["navigate", "click", "request_approval", "click"]
    gate, pay = plan.steps[2], plan.steps[3]
    assert gate.action.risk_level == RiskLevel.CRITICAL  # type: ignore[union-attr]
    assert gate.step_id in pay.depends_on and plan.requires_human_approval
    assert errors_for(plan) == []


def test_validator_catches_missing_checkpoint_when_policy_is_bypassed() -> None:
    nav = PlannedAction(step_id=uuid4(), order=1, action=NavigateAction(type="navigate", url="https://a.com", purpose="x"),
                        description="d", expected_outcome="o", risk_level=RiskLevel.LOW)
    pay = PlannedAction(step_id=uuid4(), order=2, action=ClickAction(type="click", target_description="Pay now"),
                        description="d", expected_outcome="o", risk_level=RiskLevel.CRITICAL, depends_on=[nav.step_id])
    assert checkpoint_violations([nav, pay])
    weak_gate = PlannedAction(step_id=uuid4(), order=2, action=RequestApprovalAction(type="request_approval", reason="r", risk_level=RiskLevel.MEDIUM),
                              description="d", expected_outcome="o", risk_level=RiskLevel.MEDIUM, requires_approval=True)
    fixed = apply_risk_and_approvals([nav, weak_gate, pay.model_copy(update={"order": 3})])
    assert checkpoint_violations(fixed) == []  # a stronger gate was inserted


def test_add_to_cart_does_not_require_approval() -> None:
    plan = to_plan([step(1, NAV), step(2, ADD, "MEDIUM"), step(3, {"type": "stop", "reason": "cart ready"})])
    assert not plan.requires_human_approval


def test_unsafe_model_message_is_replaced() -> None:
    plan = planner().to_plan(
        PlanDraft.model_validate({**draft([step(1, NAV)]), "user_facing_message": "Done! I have added milk to your cart."}),
        task_id=TASK, session_id=SESSION, classification=SHOPPING, provider="fake", model="m", history=[],
    )
    assert "added milk" not in plan.user_facing_message


# ---------------------------------------------------------------------- registry


def test_registry_only_allows_registered_tools() -> None:
    registry = build_default_registry()
    assert set(registry.names()) == {"navigate", "click", "type", "extract", "request_approval", "stop"}
    assert registry.validate("navigate", {"url": "https://a.com", "purpose": "x"})
    assert not registry.validate("navigate", {"purpose": "x"})
    assert not registry.validate("shell", {"cmd": "ls"})
    with pytest.raises(UnknownToolError):
        registry.get("eval")
    with pytest.raises(DuplicateToolError):
        registry.register(AgentTool(name="click", description="dup", input_schema={}, risk_level=RiskLevel.LOW))


def test_stop_action_model() -> None:
    assert StopAction(type="stop", reason="x").reason == "x"
