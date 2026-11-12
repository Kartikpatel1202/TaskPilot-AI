"""Whole-plan validation. Model output is never trusted to be correct."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.agent.policies.approval_policy import checkpoint_violations
from app.agent.policies.risk_classifier import risk_at_least, rule_risk
from app.agent.tools.registry import ToolRegistry
from app.schemas.action import StopAction
from app.schemas.intent import NON_ACTIONABLE_INTENTS, IntentType
from app.schemas.plan import PlanStatus, TaskPlan

from .action_validator import validate_action
from .dependency_validator import validate_dependencies


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class PlanValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors[:5]))


class PlanValidator:
    def __init__(self, registry: ToolRegistry, max_steps: int, trusted_origins: frozenset[str] = frozenset()) -> None:
        self._registry = registry
        self._max_steps = max_steps
        # Exact dev/test-only origins (empty outside development/test by settings validation).
        self._trusted_origins = trusted_origins

    def validate(self, plan: TaskPlan, *, task_id: UUID | None = None, session_id: UUID | None = None) -> ValidationReport:
        errors: list[str] = []
        if task_id is not None and plan.task_id != task_id:
            errors.append("Plan belongs to a different task.")
        if session_id is not None and plan.session_id != session_id:
            errors.append("Plan belongs to a different session.")
        if plan.intent not in IntentType:
            errors.append("Unsupported intent.")

        steps = plan.steps
        if plan.status == PlanStatus.READY:
            if not steps and plan.intent != IntentType.GENERAL_CHAT:
                errors.append("A ready plan must contain at least one step.")
            if steps and plan.intent in NON_ACTIONABLE_INTENTS:
                errors.append(f"{plan.intent.value} plans must not contain browser steps.")
        elif steps:
            errors.append(f"A {plan.status.value} plan must not contain steps.")
        if plan.status == PlanStatus.NEEDS_CLARIFICATION and not plan.clarification_question:
            errors.append("A clarification plan needs a clarification question.")

        if len(steps) > self._max_steps:
            errors.append(f"Plan has {len(steps)} steps; the maximum is {self._max_steps}.")

        ids = [s.step_id for s in steps]
        if len(set(ids)) != len(ids):
            errors.append("Step IDs must be unique.")
        orders = [s.order for s in steps]
        if orders != list(range(1, len(steps) + 1)):
            errors.append("Step order must be sequential starting at 1.")

        for index, step in enumerate(steps):
            errors.extend(validate_action(step, self._registry, self._trusted_origins))
            floor = rule_risk(step.action, step.description)
            if not risk_at_least(step.risk_level, floor):
                errors.append(f"Step {step.order}: risk {step.risk_level.value} is below the required {floor.value}.")
            if isinstance(step.action, StopAction) and index != len(steps) - 1:
                errors.append(f"Step {step.order}: 'stop' must be the final step.")

        errors.extend(validate_dependencies(steps))
        errors.extend(checkpoint_violations(steps))
        if any(s.requires_approval for s in steps) != plan.requires_human_approval:
            errors.append("requires_human_approval does not match the steps.")
        return ValidationReport(errors=list(dict.fromkeys(errors)))
