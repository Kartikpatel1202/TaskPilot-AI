"""Workflow engine units: dependency order and cycles, typed handoff, plan validation and
the integration planner (deterministic; injected clock; never invents facts)."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.integrations.capability_registry import CapabilityRegistry
from app.integrations.integration_planner import IntegrationPlanner
from app.integrations.registry import IntegrationRegistry
from app.schemas.approval import RiskLevel
from app.schemas.integration import DomainType, GmailCreateDraftAction, YouTubeSearchAction
from app.schemas.intent import IntentClassification
from app.schemas.plan import PlannedAction
from app.schemas.workflow import WorkflowOutput
from app.workflow.dependency_resolver import WorkflowCycleError, dependents, resolve_order
from app.workflow.result_handoff import MissingOutputError, consumes, produces, resolve
from app.workflow.workflow_validator import validate_workflow

from ..conftest import make_settings

IST = ZoneInfo("Asia/Kolkata")


def test_resolve_order_and_cycles() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert resolve_order([(a, []), (b, [a]), (c, [b])]) == [a, b, c]
    with pytest.raises(WorkflowCycleError):
        resolve_order([(a, [c]), (b, [a]), (c, [b])])
    with pytest.raises(WorkflowCycleError):
        resolve_order([(a, [uuid.uuid4()])])
    assert dependents([(a, []), (b, [a]), (c, [b])], a) == {b, c}


def test_typed_handoff_resolves_only_produced_outputs() -> None:
    sid = uuid.uuid4()
    out = {"youtube.video_reference": WorkflowOutput(type="youtube.video_reference", step_id=sid,
                                                       data={"title": "T", "video_url": "https://www.youtube.com/watch?v=abcdefg", "channel": "C"})}
    assert resolve("See {{youtube.title}} {{ youtube.video_url }}", out) == "See T https://www.youtube.com/watch?v=abcdefg"
    with pytest.raises(MissingOutputError):
        resolve("{{file.name}}", out)
    search = YouTubeSearchAction(type="youtube_search", query="q", select=True)
    draft = GmailCreateDraftAction(type="gmail_create_draft", recipient_emails=["a@example.com"], subject="s", body="b",
                                   insert_outputs=["youtube.video_reference"])
    assert produces(search) == ["youtube.video_reference"] and consumes(draft) == ["youtube.video_reference"]


def _step(order: int, action: object, deps: list[uuid.UUID] | None = None) -> PlannedAction:
    return PlannedAction(step_id=uuid.uuid4(), order=order, action=action, description="d", expected_outcome="o",  # type: ignore[arg-type]
                         risk_level=RiskLevel.LOW, depends_on=deps or [])


def test_validator_requires_a_producing_dependency() -> None:
    settings = make_settings(integrations_enabled=True)
    reg = CapabilityRegistry(settings)
    search = _step(1, YouTubeSearchAction(type="youtube_search", query="q", select=True))
    draft = GmailCreateDraftAction(type="gmail_create_draft", recipient_emails=["a@example.com"], subject="s", body="{{youtube.video_url}}",
                                   insert_outputs=["youtube.video_reference"])
    assert validate_workflow([search, _step(2, draft, [search.step_id])], reg, settings) == []
    errors = validate_workflow([search, _step(2, draft)], reg, settings)
    assert errors and "needs youtube.video_reference" in errors[0]
    disabled = make_settings(integrations_enabled=True, youtube_enabled=False)
    assert any("not enabled" in e for e in validate_workflow([search], CapabilityRegistry(disabled), disabled))


def _planner(**settings_overrides: object) -> IntegrationPlanner:
    settings = make_settings(integrations_enabled=True, **settings_overrides)
    reg = IntegrationRegistry(CapabilityRegistry.enabled_domains(settings) - {DomainType.BLINKIT, DomainType.AMAZON_IN})
    return IntegrationPlanner(settings, reg, clock=lambda: datetime(2026, 11, 9, 10, tzinfo=IST))


def _classify(payload: dict[str, object]) -> IntentClassification:
    from app.agent.providers.mock_scenarios import classify

    return IntentClassification.model_validate(classify(payload))


def _plan(command: str, **kw: object):  # noqa: ANN201
    from app.integrations.domain_router import route

    c = _classify({"command": command, "language": "en"})
    return _planner(**kw).build(task_id=uuid.uuid4(), session_id=uuid.uuid4(), classification=c, steps=route(c), command_text=command,
                                provider="mock", model="mock", history=[])


def test_planner_builds_calendar_event_from_injected_now() -> None:
    plan = _plan("Schedule a meeting with Rahul tomorrow at 3pm for 30 minutes")
    action = plan.steps[0].action
    assert plan.status.value == "READY" and action.type == "calendar_create_event"
    assert action.start_at == datetime(2026, 11, 10, 15, tzinfo=IST) and action.title == "Meeting with Rahul"
    assert plan.steps[0].requires_approval is True and plan.requires_human_approval is True
    # no generic request_approval step is inserted: the event's own exact approval is stricter
    assert [s.action.type for s in plan.steps] == ["calendar_create_event"]


def test_planner_asks_instead_of_inventing() -> None:
    assert _plan("Schedule a meeting with Rahul tomorrow at 3pm").missing_information == ["duration"]
    assert _plan("Schedule a meeting with Rahul tomorrow at 3pm", calendar_default_duration_minutes=30).status.value == "READY"
    no_link = _plan("Download the quarterly report")
    assert no_link.status.value in ("NEEDS_CLARIFICATION",)


def test_planner_marks_multi_domain_steps_as_independent() -> None:
    plan = _plan("Find a Python tutorial on YouTube and email the link to friend@example.com")
    assert [s.action.type for s in plan.steps] == ["youtube_search", "gmail_create_draft"]
    assert all(s.action.continue_on_failure for s in plan.steps)
    assert plan.steps[1].depends_on == [plan.steps[0].step_id]
    assert plan.steps[1].action.send_requested is False
