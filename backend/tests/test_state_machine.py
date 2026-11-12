from __future__ import annotations

import uuid

import pytest

from app.core.event_manager import EventManager
from app.core.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    InvalidTransitionError,
    can_transition,
    validate_transition,
)
from app.schemas.task import CreateTaskRequest, InputMode, TaskState
from app.schemas.telemetry import TelemetryEvent
from app.services.task_service import TaskService

S = TaskState

VALID = [
    (S.IDLE, S.PLANNING),
    (S.PLANNING, S.PLANNED),
    (S.PLANNING, S.NEEDS_CLARIFICATION),
    (S.NEEDS_CLARIFICATION, S.PLANNING),
    (S.PLANNED, S.EXECUTING),
    # Kept only for the clearly labelled Phase 1 demo simulation.
    (S.PLANNING, S.EXECUTING),
    (S.EXECUTING, S.WAITING_APPROVAL),
    (S.WAITING_APPROVAL, S.EXECUTING),
    (S.EXECUTING, S.COMPLETED),
    # Phase 3: user stop, rejected/expired approval or a hard-blocked action.
    (S.EXECUTING, S.CANCELLED),
    (S.WAITING_APPROVAL, S.CANCELLED),
    # Any active state may fail.
    (S.IDLE, S.FAILED),
    (S.PLANNING, S.FAILED),
    (S.NEEDS_CLARIFICATION, S.FAILED),
    (S.PLANNED, S.FAILED),
    (S.EXECUTING, S.FAILED),
    (S.WAITING_APPROVAL, S.FAILED),
]


@pytest.mark.parametrize(("current", "target"), VALID)
def test_valid_transitions_succeed(current: TaskState, target: TaskState) -> None:
    assert validate_transition(current, target) is target


def test_every_other_transition_is_rejected() -> None:
    valid = set(VALID)
    for current in TaskState:
        for target in TaskState:
            if (current, target) in valid:
                continue
            assert not can_transition(current, target)
            with pytest.raises(InvalidTransitionError):
                validate_transition(current, target)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES, key=lambda s: s.value))
def test_terminal_states_cannot_transition(terminal: TaskState) -> None:
    assert ALLOWED_TRANSITIONS[terminal] == frozenset()
    for target in TaskState:
        with pytest.raises(InvalidTransitionError, match="terminal"):
            validate_transition(terminal, target)


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    async def publish(self, session_id: uuid.UUID, event: TelemetryEvent) -> None:
        self.events.append(event)


async def test_service_transition_emits_telemetry_and_rejects_invalid() -> None:
    publisher = RecordingPublisher()
    service = TaskService(EventManager(publisher, max_sessions=10), max_tasks=10)
    task = await service.create_task(
        CreateTaskRequest(command="test", session_id=uuid.uuid4(), input_mode=InputMode.TEXT)
    )
    assert task.state is S.IDLE

    with pytest.raises(InvalidTransitionError):
        await service.transition(task.task_id, S.COMPLETED)
    before = len(publisher.events)

    await service.transition(task.task_id, S.PLANNING)
    await service.transition(task.task_id, S.EXECUTING)
    await service.transition(task.task_id, S.FAILED, reason="boom", error_code="X")
    types = [e.type.value for e in publisher.events[before:]]
    assert types == ["task.state_changed", "task.state_changed", "task.state_changed", "task.failed"]
    assert publisher.events[-1].data == {"error_code": "X", "error_message": "boom", "is_demo": False}

    # sequence numbers are strictly increasing per session
    seqs = [e.sequence for e in publisher.events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert (await service.get_task(task.task_id)).error_message == "boom"
