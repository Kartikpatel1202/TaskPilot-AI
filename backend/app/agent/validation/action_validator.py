"""Per-action validation (registry contract + safety rules)."""

from __future__ import annotations

from app.agent.policies.risk_classifier import CREDENTIAL_FIELD
from app.agent.policies.url_policy import UrlPolicyError, validate_url
from app.agent.tools.registry import ToolRegistry
from app.schemas.action import NavigateAction, TypeAction
from app.schemas.commerce import CommerceAction
from app.schemas.integration import INTEGRATION_ACTION_TYPES, FileDownloadAction
from app.schemas.plan import PlannedAction


def validate_action(
    step: PlannedAction, registry: ToolRegistry, trusted_origins: frozenset[str] = frozenset()
) -> list[str]:
    errors: list[str] = []
    action = step.action
    if isinstance(action, CommerceAction):
        # Built only by the deterministic commerce planner; already schema-validated (never from LLM drafts).
        if action.operation in ("search_and_add", "search_products") and action.requirement is None:
            errors.append(f"Step {step.order}: commerce {action.operation} needs a product requirement.")
        return errors
    if action.type in INTEGRATION_ACTION_TYPES:
        # Phase 5: built only by the deterministic integration planner; schema-validated, and the
        # capability is re-checked against the trusted CapabilityRegistry before it runs.
        if isinstance(action, FileDownloadAction):
            try:
                validate_url(action.source_url, trusted_origins=trusted_origins)
            except UrlPolicyError as exc:
                errors.append(f"Step {step.order}: download blocked — {exc}")
        return errors
    name = action.type
    arguments = action.model_dump(mode="json", exclude={"type"})
    if not registry.validate(name, arguments):
        errors.append(f"Step {step.order}: action '{name}' is not a registered tool or has invalid parameters.")
        return errors

    if isinstance(action, NavigateAction):
        try:
            validate_url(action.url, trusted_origins=trusted_origins)
        except UrlPolicyError as exc:
            errors.append(f"Step {step.order}: navigation blocked — {exc}")

    if isinstance(action, TypeAction) and (CREDENTIAL_FIELD.search(action.target_description) or action.sensitive):
        errors.append(
            f"Step {step.order}: typing passwords, OTPs or payment details is not allowed; the user enters them."
        )
    return errors
