"""Structured planning engine.

LLM `PlanDraft` -> trusted conversion (server-assigned step IDs, order-based
dependencies resolved to IDs) -> deterministic risk + approval policy ->
`PlanValidator`. Invalid plans are retried with validation feedback up to
AGENT_MAX_RETRIES and are never returned to the caller.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from app.agent.llm_runner import StructuredLLMRunner
from app.agent.policies.approval_policy import apply_risk_and_approvals
from app.agent.prompts import PLANNER_INSTRUCTIONS, build_system_prompt
from app.agent.response_generator import sanitize_message, sanitize_short
from app.agent.tools.registry import ToolRegistry
from app.agent.validation import PlanValidationError, PlanValidator
from app.core.logging import get_logger, redact_text
from app.core.persona import Language
from app.schemas.action import DraftRequestApprovalAction, TypeAction
from app.schemas.common import utc_now
from app.schemas.intent import IntentClassification, IntentType
from app.schemas.memory import PlanningContext
from app.schemas.plan import ClarificationExchange, PlanDraft, PlannedAction, PlanStatus, TaskPlan

logger = get_logger("agent.planner")


class Planner:
    def __init__(
        self,
        runner: StructuredLLMRunner,
        registry: ToolRegistry,
        *,
        max_steps: int,
        max_retries: int,
        trusted_origins: frozenset[str] = frozenset(),
    ) -> None:
        self._runner = runner
        self._registry = registry
        self._validator = PlanValidator(registry, max_steps, trusted_origins)
        self._max_steps = max_steps
        self._max_retries = max_retries
        self._system_prompt = build_system_prompt(PLANNER_INSTRUCTIONS)

    @property
    def validator(self) -> PlanValidator:
        return self._validator

    # ---------------------------------------------------------------- LLM planning

    async def generate(
        self,
        *,
        task_id: UUID,
        session_id: UUID,
        command: str,
        clarifications: list[str],
        classification: IntentClassification,
        context: PlanningContext,
        history: list[ClarificationExchange],
        on_validating: Callable[[], Awaitable[None]] | None = None,
    ) -> TaskPlan:
        feedback: list[str] = []
        notified = False
        for attempt in range(self._max_retries + 1):
            payload: dict[str, Any] = {
                "task": "build_plan",
                "command": command,
                "clarifications": clarifications,
                "language": classification.language,
                "intent": classification.model_dump(mode="json"),
                "session_context": context.session_context.model_dump(mode="json"),
                "user_profile": context.user_profile,
                "conversation_summary": context.summary,
                "allowed_actions": self._registry.describe_for_prompt(),
                "max_steps": self._max_steps,
                "previous_validation_errors": feedback,
            }
            result = await self._runner.run(self._system_prompt, payload, PlanDraft)
            if on_validating and not notified:
                notified = True
                await on_validating()
            draft = PlanDraft.model_validate(result.parsed_output)
            plan = self.to_plan(
                draft,
                task_id=task_id,
                session_id=session_id,
                classification=classification,
                provider=result.provider,
                model=result.model,
                history=history,
            )
            report = self._validator.validate(plan, task_id=task_id, session_id=session_id)
            if report.ok:
                return plan
            feedback = report.errors[:10]
            logger.warning("planner.invalid_plan", extra={"attempt": attempt + 1, "errors": feedback})
        raise PlanValidationError(feedback)

    # ---------------------------------------------------------------- conversion

    def to_plan(
        self,
        draft: PlanDraft,
        *,
        task_id: UUID,
        session_id: UUID,
        classification: IntentClassification,
        provider: str,
        model: str,
        history: list[ClarificationExchange],
    ) -> TaskPlan:
        status = PlanStatus(draft.status)
        language: Language = classification.language
        steps: list[PlannedAction] = []
        if status == PlanStatus.READY:
            order_ids: dict[int, UUID] = {}
            for step in draft.steps:
                order_ids.setdefault(step.order, uuid4())
            for step in draft.steps:
                action = step.action.to_action() if isinstance(step.action, DraftRequestApprovalAction) else step.action
                if isinstance(action, TypeAction):
                    action = action.model_copy(update={"text": redact_text(action.text)})
                step_id = order_ids[step.order] if not any(s.step_id == order_ids[step.order] for s in steps) else uuid4()
                steps.append(
                    PlannedAction(
                        step_id=step_id,
                        order=step.order,
                        action=action,
                        description=sanitize_short(step.description),
                        expected_outcome=sanitize_short(step.expected_outcome),
                        risk_level=step.risk_level,
                        requires_approval=step.requires_approval,
                        # Unknown order references become unknown IDs, which the validator rejects.
                        depends_on=[order_ids.get(o, uuid4()) for o in step.depends_on_orders],
                    )
                )
            # Only well-ordered plans get the policy pass; malformed ones fail validation as-is.
            if [s.order for s in steps] == list(range(1, len(steps) + 1)):
                steps = apply_risk_and_approvals(steps)

        return TaskPlan(
            plan_id=uuid4(),
            task_id=task_id,
            session_id=session_id,
            status=status,
            intent=classification.intent,
            summary=sanitize_short(draft.summary),
            user_facing_message=sanitize_message(draft.user_facing_message, status, language),
            language=language,
            target_website=classification.target_website,
            confidence=min(draft.confidence, 1.0),
            assumptions=[sanitize_short(a) for a in draft.assumptions][:10],
            clarification_question=sanitize_short(draft.clarification_question, 400)
            if status == PlanStatus.NEEDS_CLARIFICATION and draft.clarification_question
            else None,
            missing_information=draft.missing_information if status == PlanStatus.NEEDS_CLARIFICATION else [],
            clarification_history=list(history),
            steps=steps,
            requires_human_approval=any(s.requires_approval for s in steps),
            provider=provider,
            model=model,
            is_mock=provider == "mock",
            created_at=utc_now(),
        )

    # ---------------------------------------------------------------- non-LLM plans

    def clarification_plan(
        self,
        *,
        task_id: UUID,
        session_id: UUID,
        classification: IntentClassification,
        provider: str,
        model: str,
        history: list[ClarificationExchange],
    ) -> TaskPlan:
        question = sanitize_message(classification.clarification_question, PlanStatus.NEEDS_CLARIFICATION, classification.language)
        return TaskPlan(
            plan_id=uuid4(),
            task_id=task_id,
            session_id=session_id,
            status=PlanStatus.NEEDS_CLARIFICATION,
            intent=classification.intent,
            summary="More information is needed before planning.",
            user_facing_message=question,
            language=classification.language,
            target_website=classification.target_website,
            confidence=classification.confidence,
            clarification_question=question,
            missing_information=classification.missing_information,
            clarification_history=list(history),
            provider=provider,
            model=model,
            is_mock=provider == "mock",
            created_at=utc_now(),
        )

    def rejected_plan(
        self,
        *,
        task_id: UUID,
        session_id: UUID,
        message: str,
        language: Language,
        provider: str,
        model: str,
        intent: IntentType = IntentType.UNSUPPORTED,
        confidence: float = 1.0,
        history: list[ClarificationExchange] | None = None,
    ) -> TaskPlan:
        return TaskPlan(
            plan_id=uuid4(),
            task_id=task_id,
            session_id=session_id,
            status=PlanStatus.REJECTED,
            intent=intent,
            summary="Request is outside supported or safe capabilities.",
            user_facing_message=message,
            language=language,
            confidence=confidence,
            clarification_history=list(history or []),
            provider=provider,
            model=model,
            is_mock=provider == "mock",
            created_at=utc_now(),
        )
