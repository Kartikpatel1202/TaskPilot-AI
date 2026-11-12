"""Workflow plan validation (Phase 5): limits, capabilities, typed inputs and dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.integrations.capability_registry import ACTION_CAPABILITY, CapabilityError, CapabilityRegistry
from app.schemas.plan import PlannedAction
from app.workflow.dependency_resolver import WorkflowCycleError, resolve_order
from app.workflow.result_handoff import consumes, placeholders_in, produces

if TYPE_CHECKING:
    from app.config import Settings


def validate_workflow(steps: list[PlannedAction], registry: CapabilityRegistry, settings: Settings) -> list[str]:
    errors: list[str] = []
    integration = [s for s in steps if s.action.type in ACTION_CAPABILITY]
    if not integration:
        return errors
    if len(steps) > settings.workflow_max_steps:
        errors.append(f"The workflow has {len(steps)} steps; the limit is {settings.workflow_max_steps}.")
    domains = set()
    for step in integration:
        try:
            domains.add(registry.require(step.action.type).domain)
        except CapabilityError as exc:
            errors.append(f"Step {step.order}: {exc.message}")
    if len(domains) > settings.workflow_max_domains:
        errors.append(f"The workflow uses {len(domains)} domains; the limit is {settings.workflow_max_domains}.")
    try:
        resolve_order([(s.step_id, list(s.depends_on)) for s in steps])
    except WorkflowCycleError as exc:
        errors.append(str(exc))
        return errors
    by_id = {s.step_id: s for s in steps}
    for step in integration:
        needed = set(consumes(step.action))
        for text in (getattr(step.action, "subject", ""), getattr(step.action, "body", "")):
            needed |= placeholders_in(text or "")
        for kind in needed:
            producers = [d for d in step.depends_on if kind in produces(by_id[d].action)]
            if not producers:
                errors.append(f"Step {step.order} needs {kind} but does not depend on a step that produces it.")
    return errors
