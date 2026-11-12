"""Kamlesh Bhai's agent brain: connects normalisation, memory, classification,
planning, validation, state and telemetry.

Only trusted code here changes task state. The LLM produces data; nothing it
returns is executed. No browser is touched in Phase 2.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.agent.intent_classifier import IntentClassifier
from app.integrations.domain_router import INTEGRATION_INTENTS, route
from app.integrations.integration_planner import IntegrationPlanner
from app.commerce.base import SiteBinding
from app.commerce.commerce_planner import COMMERCE_INTENTS, CommercePlanner
from app.commerce.registry import CommerceRegistry
from app.agent.memory import MemoryManager
from app.agent.normalizer import normalize_command
from app.agent.plan_store import PlanningRecord, PlanStore
from app.agent.planner import Planner
from app.agent.policies.input_guard import screen_request
from app.agent.providers.base import LLMProvider, ProviderError
from app.agent.response_generator import sanitize_message
from app.agent.validation import PlanValidationError
from app.core.event_manager import EventManager
from app.core.logging import get_logger
from app.core.persona import Language, detect_language, persona_message
from app.core.state_machine import is_terminal
from app.schemas.agent import PlanningStage, stage_progress
from app.schemas.common import utc_now
from app.schemas.intent import IntentClassification, IntentType, WorkflowStepEntity
from app.schemas.plan import ClarificationExchange, PlannedAction, PlanStatus, TaskPlan
from app.schemas.task import TaskState
from app.schemas.telemetry import (
    AgentResponsePayload,
    ClarificationRequiredPayload,
    IntentDetectedPayload,
    PlanningFailedPayload,
    PlanningProgressPayload,
    PlanningStartedPayload,
    PlanReadyPayload,
    TelemetryEventType,
)
from app.services.task_service import TaskService

logger = get_logger("agent.orchestrator")

_STAGE_MESSAGES = {
    PlanningStage.UNDERSTANDING_COMMAND: "Understanding your command…",
    PlanningStage.CLASSIFYING_INTENT: "Identifying the task…",
    PlanningStage.BUILDING_PLAN: "Building an action plan…",
    PlanningStage.VALIDATING_PLAN: "Checking action safety and dependencies…",
    PlanningStage.FINALIZING: "Finalizing the plan…",
}


class PlanningAborted(Exception):
    """The task left the PLANNING state underneath us (e.g. cancelled)."""


class AgentOrchestrator:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        events: EventManager,
        tasks: TaskService,
        memory: MemoryManager,
        classifier: IntentClassifier,
        planner: Planner,
        store: PlanStore,
        max_command_length: int,
        commerce_planner: CommercePlanner | None = None,
        commerce_registry: CommerceRegistry | None = None,
        integration_planner: IntegrationPlanner | None = None,
        workflow_validator: Callable[[list[PlannedAction]], list[str]] | None = None,
    ) -> None:
        self.persistence: Any = None  # Phase 6 Persistence (set by the container)
        self._pending_turns: list[tuple[Any, ...]] = []
        self.preferences: Any = None  # PreferencesService (set by the container)
        self._integration_planner = integration_planner
        self._workflow_validator = workflow_validator
        self._commerce_planner = commerce_planner
        self._commerce_registry = commerce_registry
        self._provider = provider
        self._events = events
        self._tasks = tasks
        self._memory = memory
        self._classifier = classifier
        self._planner = planner
        self._store = store
        self._max_len = max_command_length

    # ---------------------------------------------------------------- public API

    async def process_clarification(self, task_id: UUID, session_id: UUID, message: str) -> TaskPlan:
        """Record a clarification answer and re-plan (direct entry point; the API uses PlanningService)."""
        record = self._require_record(task_id, session_id)
        await self._tasks.transition(task_id, TaskState.PLANNING, reason="Clarification received")
        self.record_clarification(record, message)
        return await self.process_task(task_id, session_id)

    def record_clarification(self, record: PlanningRecord, message: str) -> None:
        answer = normalize_command(message, self._max_len).normalized
        record.clarifications.append(
            ClarificationExchange(question=record.pending_question or "", answer=answer, answered_at=utc_now())
        )
        record.pending_question = None
        self._memory.add_user_turn(record.session_id, record.task_id, answer)
        self._pending_turns.append((record.session_id, record.task_id, "user", answer, None))

    async def process_task(self, task_id: UUID, session_id: UUID) -> TaskPlan:
        record = self._require_record(task_id, session_id)
        task = await self._tasks.get_task(task_id)
        if task.state == TaskState.IDLE:
            await self._tasks.transition(task_id, TaskState.PLANNING, reason="Kamlesh Bhai started planning")
        elif task.state != TaskState.PLANNING:
            raise PlanningAborted(f"Task is {task.state.value}, not PLANNING.")

        latest_text = record.clarifications[-1].answer if record.clarifications else record.command
        language: Language = detect_language(latest_text)
        profile = await self._profile(task_id)
        if profile.get("language") in ("en", "hi", "hinglish"):
            language = profile["language"]  # type: ignore[assignment]
        record.profile = profile
        try:
            return await self._plan(record, language)
        except ProviderError as exc:
            await self.fail(record, exc.code, exc.message, language, retryable=exc.retryable)
            raise
        except PlanValidationError:
            await self.fail(record, "PLAN_VALIDATION_FAILED", "The generated plan did not pass safety validation.", language)
            raise

    # ---------------------------------------------------------------- pipeline

    async def _plan(self, record: PlanningRecord, language: Language) -> TaskPlan:
        task_id, session_id = record.task_id, record.session_id
        is_clarification = bool(record.clarifications)
        await self._emit(
            record,
            TelemetryEventType.AGENT_PLANNING_STARTED,
            PlanningStartedPayload(
                message=persona_message("clarification_received" if is_clarification else "planning_started", language),
                is_clarification=is_clarification,
            ),
        )

        await self._stage(record, PlanningStage.UNDERSTANDING_COMMAND)
        command = normalize_command(record.command, self._max_len)
        clarifications = [c.answer for c in record.clarifications]
        if not record.user_turn_recorded:
            self._memory.add_user_turn(session_id, task_id, command.normalized)
            await self._persist_turn(session_id, task_id, "user", command.normalized, None)
            record.user_turn_recorded = True

        guard = screen_request(" ".join([command.normalized, *clarifications]))
        if not guard.allowed:
            logger.warning("agent.request_blocked", extra={"task_id": str(task_id), "category": guard.category})
            plan = self._planner.rejected_plan(
                task_id=task_id,
                session_id=session_id,
                message=persona_message("rejected", language),
                language=language,
                provider="policy",
                model="input-guard",
                history=record.clarifications,
            )
            return await self._finish(record, plan)

        context = self._memory.build_context(session_id, task_id)
        context.user_profile = getattr(record, "profile", {}) or {}
        if context.user_profile.get("language") in ("en", "hi", "hinglish"):
            command = dataclasses.replace(command, language=context.user_profile["language"])
        await self._stage(record, PlanningStage.CLASSIFYING_INTENT)
        classification = await self._classifier.classify(command, clarifications, context)
        await self._emit(
            record,
            TelemetryEventType.AGENT_INTENT_DETECTED,
            IntentDetectedPayload(
                intent=classification.intent.value,
                confidence=classification.confidence,
                target_website=classification.target_website,
                language=classification.language,
                requires_clarification=classification.requires_clarification,
                is_follow_up=classification.is_follow_up,
            ),
        )

        provider, model = self._provider.name, self._provider.model
        if classification.requires_clarification:
            plan = self._planner.clarification_plan(
                task_id=task_id, session_id=session_id, classification=classification,
                provider=provider, model=model, history=record.clarifications,
            )
        elif classification.intent == IntentType.UNSUPPORTED:
            plan = self._planner.rejected_plan(
                task_id=task_id, session_id=session_id,
                message=persona_message("rejected", classification.language),
                language=classification.language, provider=provider, model=model,
                confidence=classification.confidence, history=record.clarifications,
            )
        elif steps := self._integration_steps(classification):
            # Phase 5: YouTube / Gmail drafts / Calendar / safe downloads (one or several domains) ->
            # deterministic integration plan on domain-validated sites, checked against the capability registry.
            assert self._integration_planner is not None
            await self._stage(record, PlanningStage.BUILDING_PLAN)
            plan = self._integration_planner.build(
                task_id=task_id, session_id=session_id, classification=classification, steps=steps,
                command_text=" ".join([command.normalized, *clarifications]), clarification_text=" ".join(clarifications),
                provider=provider, model=model, history=record.clarifications,
            )
            if plan.status == PlanStatus.READY:
                await self._stage(record, PlanningStage.VALIDATING_PLAN)
                report = self._planner.validator.validate(plan, task_id=task_id, session_id=session_id)
                errors = list(report.errors)
                if self._workflow_validator is not None:
                    errors += self._workflow_validator(plan.steps)
                if errors:
                    raise PlanValidationError(errors)
                self._memory.remember_classification(session_id, task_id, classification)
        elif classification.intent == IntentType.MULTI_DOMAIN_WORKFLOW:
            plan = self._planner.rejected_plan(
                task_id=task_id, session_id=session_id,
                message="Multi-domain workflows (YouTube, Gmail drafts, Calendar, downloads) are not enabled on this server.",
                language=classification.language, provider=provider, model=model, intent=IntentType.MULTI_DOMAIN_WORKFLOW,
                confidence=classification.confidence, history=record.clarifications,
            )
        elif (binding := self._commerce_binding(classification)) is not None and self._commerce_planner is not None:
            # Phase 4: shopping on a supported, domain-validated site -> deterministic commerce plan.
            await self._stage(record, PlanningStage.BUILDING_PLAN)
            plan = self._commerce_planner.build(
                task_id=task_id, session_id=session_id, classification=classification, binding=binding,
                provider=provider, model=model, history=record.clarifications,
            )
            await self._stage(record, PlanningStage.VALIDATING_PLAN)
            report = self._planner.validator.validate(plan, task_id=task_id, session_id=session_id)
            if not report.ok:
                raise PlanValidationError(report.errors)
            self._memory.remember_classification(session_id, task_id, classification)
        else:
            await self._stage(record, PlanningStage.BUILDING_PLAN)
            plan = await self._planner.generate(
                task_id=task_id,
                session_id=session_id,
                command=command.normalized,
                clarifications=clarifications,
                classification=classification,
                context=context,
                history=record.clarifications,
                on_validating=lambda: self._stage(record, PlanningStage.VALIDATING_PLAN),
            )
            if plan.status == PlanStatus.READY:
                self._memory.remember_classification(session_id, task_id, classification)
        return await self._finish(record, plan)

    async def _profile(self, task_id: UUID) -> dict[str, str]:
        """Preferred name and language from Settings (empty when unavailable — never blocks planning)."""
        if self.preferences is None:
            return {}
        try:
            owner = self._tasks.owner_of(task_id) if hasattr(self._tasks, "owner_of") else None
            prefs = await self.preferences.get(owner)
        except Exception:  # noqa: BLE001
            return {}
        profile = {"language": prefs.language}
        if prefs.display_name:
            profile["display_name"] = prefs.display_name
        store = {"blinkit": "blinkit.com", "amazon": "amazon.in"}.get(prefs.preferred_store)
        if store:
            profile["preferred_store"] = store
        return profile

    async def _finish(self, record: PlanningRecord, plan: TaskPlan) -> TaskPlan:
        await self._stage(record, PlanningStage.FINALIZING)
        task = await self._tasks.get_task(record.task_id)
        if task.state != TaskState.PLANNING:
            raise PlanningAborted(f"Task is {task.state.value}; discarding plan.")

        record.set_plan(plan)
        await self._persist_plan(record, plan)
        message = plan.user_facing_message
        if plan.status == PlanStatus.READY:
            # Publish the plan before the task becomes PLANNED, so anyone reacting to PLANNED (or replaying the
            # history right after it) always finds task.plan_ready.
            await self._emit(
                record,
                TelemetryEventType.TASK_PLAN_READY,
                PlanReadyPayload(
                    plan_id=plan.plan_id,
                    status=plan.status.value,
                    intent=plan.intent.value,
                    summary=plan.summary,
                    step_count=len(plan.steps),
                    requires_human_approval=plan.requires_human_approval,
                    provider=plan.provider,
                    model=plan.model,
                    is_mock=plan.is_mock,
                ),
            )
            await self._tasks.transition(record.task_id, TaskState.PLANNED, reason="Plan ready — runs only after you click Run Plan")
            kind = "chat" if plan.intent == IntentType.GENERAL_CHAT else "plan_ready"
        elif plan.status == PlanStatus.NEEDS_CLARIFICATION:
            record.pending_question = plan.clarification_question
            await self._tasks.transition(record.task_id, TaskState.NEEDS_CLARIFICATION, reason="Waiting for your answer")
            await self._emit(
                record,
                TelemetryEventType.TASK_CLARIFICATION_REQUIRED,
                ClarificationRequiredPayload(
                    plan_id=plan.plan_id,
                    question=plan.clarification_question or message,
                    missing_information=plan.missing_information,
                ),
            )
            kind = "clarification"
        else:  # REJECTED
            await self._emit(
                record,
                TelemetryEventType.TASK_PLAN_READY,
                PlanReadyPayload(
                    plan_id=plan.plan_id, status=plan.status.value, intent=plan.intent.value, summary=plan.summary,
                    step_count=0, requires_human_approval=False, provider=plan.provider, model=plan.model, is_mock=plan.is_mock,
                ),
            )
            await self._tasks.transition(record.task_id, TaskState.FAILED, reason=message, error_code="REQUEST_REJECTED")
            kind = "rejected"

        self._memory.add_assistant_turn(record.session_id, record.task_id, message, plan.intent)
        await self._persist_turn(record.session_id, record.task_id, "assistant", message, plan.intent.value)
        await self._emit(
            record,
            TelemetryEventType.AGENT_RESPONSE_GENERATED,
            AgentResponsePayload(message=message, language=plan.language, kind=kind),
        )
        logger.info(
            "agent.plan_finished",
            extra={"task_id": str(record.task_id), "status": plan.status.value, "intent": plan.intent.value, "steps": len(plan.steps)},
        )
        return plan

    async def fail(self, record: PlanningRecord, code: str, message: str, language: Language, *, retryable: bool = False) -> None:
        """Publish a safe failure and move the task to FAILED (idempotent)."""
        task = await self._tasks.get_task(record.task_id)
        if is_terminal(task.state):
            return
        safe = sanitize_message(message, PlanStatus.FAILED, language) if message else persona_message("failed", language)
        await self._emit(record, TelemetryEventType.TASK_PLANNING_FAILED, PlanningFailedPayload(code=code, message=safe, retryable=retryable))
        await self._tasks.transition(record.task_id, TaskState.FAILED, reason=safe, error_code=code)
        reply = persona_message("failed", language)
        self._memory.add_assistant_turn(record.session_id, record.task_id, reply)
        await self._persist_turn(record.session_id, record.task_id, "assistant", reply, None)
        await self._emit(record, TelemetryEventType.AGENT_RESPONSE_GENERATED, AgentResponsePayload(message=reply, language=language, kind="failed"))

    # ---------------------------------------------------------------- helpers

    async def _persist_plan(self, record: PlanningRecord, plan: TaskPlan) -> None:
        if self.persistence is None:
            return
        history = [c.model_dump(mode="json") for c in record.clarifications]
        await self.persistence.best_effort(self.persistence.plans.save(
            plan, user_id=self._tasks.owner_of(record.task_id), command=record.command, clarifications=history), "plan.save")
        while self._pending_turns:
            await self._persist_turn(*self._pending_turns.pop(0))

    async def _persist_turn(self, session_id: UUID, task_id: UUID | None, role: str, content: str, intent: str | None) -> None:
        if self.persistence is None:
            return
        owner = self._tasks.owner_of(task_id) if task_id else None
        await self.persistence.best_effort(self.persistence.conversations.add(
            session_id=session_id, user_id=owner, task_id=task_id, role=role, content=content, intent=intent), "memory.turn")

    def _integration_steps(self, classification: IntentClassification) -> list[WorkflowStepEntity]:
        if self._integration_planner is None or classification.intent not in INTEGRATION_INTENTS:
            return []
        return route(classification)

    def _commerce_binding(self, classification: IntentClassification) -> SiteBinding | None:
        if self._commerce_planner is None or self._commerce_registry is None or classification.intent not in COMMERCE_INTENTS:
            return None
        return self._commerce_registry.binding_for_website(classification.target_website)

    def _require_record(self, task_id: UUID, session_id: UUID) -> PlanningRecord:
        record = self._store.get(task_id)
        if record is None or record.session_id != session_id:
            raise LookupError("No planning record for this task/session.")
        return record

    async def _stage(self, record: PlanningRecord, stage: PlanningStage) -> None:
        await self._emit(
            record,
            TelemetryEventType.AGENT_PLANNING_PROGRESS,
            PlanningProgressPayload(stage=stage.value, progress=stage_progress(stage), message=_STAGE_MESSAGES[stage]),
        )

    async def _emit(self, record: PlanningRecord, event_type: TelemetryEventType, payload: object) -> None:
        await self._events.emit(record.session_id, event_type, payload, task_id=record.task_id)  # type: ignore[arg-type]
