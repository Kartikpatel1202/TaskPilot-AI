"""LLM-based intent classification with deterministic post-validation."""

from __future__ import annotations

from typing import Any

from app.agent.llm_runner import StructuredLLMRunner
from app.agent.normalizer import NormalizedCommand
from app.agent.prompts import CLASSIFIER_INSTRUCTIONS, build_system_prompt
from app.agent.websites import WEBSITES, normalize_website
from app.core.persona import persona_message
from app.schemas.intent import NON_ACTIONABLE_INTENTS, IntentClassification, IntentType
from app.schemas.memory import PlanningContext


class IntentClassifier:
    def __init__(self, runner: StructuredLLMRunner) -> None:
        self._runner = runner
        self._system_prompt = build_system_prompt(CLASSIFIER_INSTRUCTIONS)

    def build_payload(
        self, command: NormalizedCommand, clarifications: list[str], context: PlanningContext
    ) -> dict[str, Any]:
        return {
            "task": "classify_intent",
            "command": command.normalized,
            "clarifications": clarifications,
            "language": command.language,
            "supported_intents": [i.value for i in IntentType],
            "known_websites": {w.name: w.domain for w in WEBSITES},
            "session_context": context.session_context.model_dump(mode="json"),
            "user_profile": context.user_profile,
            "conversation_summary": context.summary,
            "recent_conversation": [t.model_dump(mode="json") for t in context.recent_turns],
        }

    async def classify(
        self, command: NormalizedCommand, clarifications: list[str], context: PlanningContext
    ) -> IntentClassification:
        result = await self._runner.run(self._system_prompt, self.build_payload(command, clarifications, context), IntentClassification)
        return post_process(IntentClassification.model_validate(result.parsed_output), command)


def post_process(classification: IntentClassification, command: NormalizedCommand) -> IntentClassification:
    """Safe, deterministic normalisation of model output. Never invents data."""
    update: dict[str, Any] = {"target_website": normalize_website(classification.target_website)}
    if classification.intent in NON_ACTIONABLE_INTENTS:
        update.update(requires_clarification=False, clarification_question=None, missing_information=[])
    elif classification.missing_information and not classification.requires_clarification:
        update["requires_clarification"] = True
    if (update.get("requires_clarification", classification.requires_clarification)) and not classification.clarification_question:
        update["clarification_question"] = persona_message("clarification", classification.language)
    return classification.model_copy(update=update)
