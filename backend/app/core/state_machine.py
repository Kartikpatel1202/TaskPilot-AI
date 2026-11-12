"""Explicit task state machine.

    IDLE -> PLANNING -> {PLANNED, NEEDS_CLARIFICATION}
    NEEDS_CLARIFICATION -> PLANNING          (user answered a clarification)
    PLANNED -> EXECUTING                     (Phase 3+; never used by the planner)
    EXECUTING -> {WAITING_APPROVAL, COMPLETED, CANCELLED}
    WAITING_APPROVAL -> {EXECUTING, CANCELLED}   (approved / rejected or expired)
    any active state -> FAILED

PLANNING -> EXECUTING is kept only so the clearly labelled Phase 1 demo
simulation keeps working. COMPLETED, FAILED and CANCELLED are terminal.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from app.schemas.task import TaskState

ALLOWED_TRANSITIONS: Mapping[TaskState, frozenset[TaskState]] = MappingProxyType(
    {
        TaskState.IDLE: frozenset({TaskState.PLANNING, TaskState.FAILED}),
        TaskState.PLANNING: frozenset(
            {TaskState.PLANNED, TaskState.NEEDS_CLARIFICATION, TaskState.EXECUTING, TaskState.FAILED}
        ),
        TaskState.NEEDS_CLARIFICATION: frozenset({TaskState.PLANNING, TaskState.FAILED}),
        TaskState.PLANNED: frozenset({TaskState.EXECUTING, TaskState.FAILED}),
        TaskState.EXECUTING: frozenset(
            {TaskState.WAITING_APPROVAL, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
        ),
        TaskState.WAITING_APPROVAL: frozenset({TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED}),
        TaskState.COMPLETED: frozenset(),
        TaskState.FAILED: frozenset(),
        TaskState.CANCELLED: frozenset(),
    }
)

TERMINAL_STATES: frozenset[TaskState] = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})
INITIAL_STATE = TaskState.IDLE


class InvalidTransitionError(ValueError):
    def __init__(self, current: TaskState, target: TaskState) -> None:
        self.current = current
        self.target = target
        reason = "terminal state" if current in TERMINAL_STATES else "transition not allowed"
        super().__init__(f"Invalid task transition {current.value} -> {target.value} ({reason}).")


def is_terminal(state: TaskState) -> bool:
    return state in TERMINAL_STATES


def can_transition(current: TaskState, target: TaskState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def validate_transition(current: TaskState, target: TaskState) -> TaskState:
    """Return `target` if the transition is legal, otherwise raise InvalidTransitionError."""
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
    return target
