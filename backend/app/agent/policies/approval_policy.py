"""Approval checkpoint policy.

Every HIGH or CRITICAL action must be immediately preceded by a `request_approval`
step of at least the same risk, must depend on it, and must be flagged
`requires_approval`. If the model forgot a checkpoint, one is inserted here.

These are *planned* checkpoints. Phase 2 never raises a real approval request;
Phase 3 raises it at runtime, right before the sensitive action, when its real
consequences can be shown.
"""

from __future__ import annotations

from uuid import uuid4

from app.schemas.action import RequestApprovalAction
from app.schemas.approval import RiskLevel
from app.schemas.commerce import CommerceAction
from app.schemas.plan import PlannedAction

from .risk_classifier import classify_risk, risk_at_least


def needs_approval(risk: RiskLevel) -> bool:
    return risk_at_least(risk, RiskLevel.HIGH)


def is_self_gated(action: object) -> bool:
    """Phase 4: `place_order` raises its own exact-order purchase approval at runtime (bound to the
    observed checkout summary), which is stricter than a generic planned checkpoint. Phase 5:
    `calendar_create_event` likewise raises an exact-event approval."""
    if isinstance(action, CommerceAction) and action.operation == "place_order":
        return True
    # Phase 5: creating a calendar event raises its own exact-event approval bound to the event hash.
    return getattr(action, "type", None) == "calendar_create_event"


def apply_risk_and_approvals(steps: list[PlannedAction]) -> list[PlannedAction]:
    """Raise risk levels by rule, then guarantee an approval gate before every risky step."""
    result: list[PlannedAction] = []
    for step in steps:
        risk = classify_risk(step.action, step.risk_level, step.description)
        is_gate = isinstance(step.action, RequestApprovalAction)
        step = step.model_copy(update={"risk_level": risk, "requires_approval": step.requires_approval or is_gate})

        if is_self_gated(step.action):
            step = step.model_copy(update={"requires_approval": True})
        elif needs_approval(risk) and not is_gate:
            previous = result[-1] if result else None
            gate_ok = (
                previous is not None
                and isinstance(previous.action, RequestApprovalAction)
                and risk_at_least(previous.action.risk_level, risk)
            )
            if not gate_ok:
                previous = PlannedAction(
                    step_id=uuid4(),
                    order=1,  # renumbered below
                    action=RequestApprovalAction(
                        type="request_approval",
                        reason=f"Approval required before: {step.description}",
                        risk_level=risk,
                        details={"Action": step.description[:300]},
                    ),
                    description="Ask for your explicit approval before continuing.",
                    expected_outcome="Execution pauses until you approve or reject.",
                    risk_level=risk,
                    requires_approval=True,
                    depends_on=list(step.depends_on),
                )
                result.append(previous)
            assert previous is not None
            depends = list(dict.fromkeys([*step.depends_on, previous.step_id]))
            step = step.model_copy(update={"requires_approval": True, "depends_on": depends})
        result.append(step)

    return [s.model_copy(update={"order": i}) for i, s in enumerate(result, start=1)]


def checkpoint_violations(steps: list[PlannedAction]) -> list[str]:
    """Independent check used by the plan validator (does not mutate)."""
    errors: list[str] = []
    for index, step in enumerate(steps):
        if isinstance(step.action, RequestApprovalAction) or not needs_approval(step.risk_level):
            continue
        if is_self_gated(step.action):
            if not step.requires_approval:
                errors.append(f"Step {step.order} must be marked requires_approval.")
            continue
        gate = steps[index - 1] if index > 0 else None
        if gate is None or not isinstance(gate.action, RequestApprovalAction):
            errors.append(f"Step {step.order} ({step.risk_level.value}) has no approval checkpoint before it.")
            continue
        if not risk_at_least(gate.action.risk_level, step.risk_level):
            errors.append(f"Step {step.order}: approval checkpoint risk is lower than the action risk.")
        if gate.step_id not in step.depends_on:
            errors.append(f"Step {step.order} does not depend on its approval checkpoint.")
        if not step.requires_approval:
            errors.append(f"Step {step.order} must be marked requires_approval.")
    return errors
