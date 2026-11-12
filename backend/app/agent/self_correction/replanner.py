"""Optional LLM suggestion for a replacement target — data only, strictly validated.

The model receives sanitized evidence and may only answer with ONE of the candidate names it was
given (or none). It cannot produce code, URLs, new action types or approvals; the answer is checked
against the live candidate list, the original role, the risk policy and the runtime click policy.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.self_correction.evidence_builder import FailureEvidence
from app.core.logging import get_logger

logger = get_logger("self_correction.replanner")

RECOVERY_INSTRUCTIONS = """
Task: a browser step failed because its target control was not found. From the candidate controls
listed in the payload (role + accessible name, observed on the page), pick the ONE that is the same
control under a new label, or answer none. Never pick a control that would do something different
(e.g. pay, order, send, delete, sign in). Never invent a name that is not in the candidate list.
""".strip()


class RecoverySuggestion(BaseModel):
    choice: str | None = Field(default=None, max_length=80, description="Exact candidate name, or null for none")
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=200)


class Replanner:
    def __init__(self, runner: Any | None) -> None:
        self._runner = runner

    async def suggest(self, evidence: FailureEvidence) -> str | None:
        if self._runner is None or getattr(self._runner.provider, "name", "") == "mock":
            return None  # the offline mock never guesses replacements
        from app.agent.prompts import build_system_prompt

        try:
            result = await self._runner.run(build_system_prompt(RECOVERY_INSTRUCTIONS), evidence.as_payload(), RecoverySuggestion)
        except Exception:  # noqa: BLE001 - no suggestion is a safe outcome
            logger.info("self_correction.no_suggestion")
            return None
        try:  # providers return the validated structured output as a dict
            raw = result.parsed_output
            suggestion = raw if isinstance(raw, RecoverySuggestion) else RecoverySuggestion.model_validate(raw)
        except Exception:  # noqa: BLE001
            return None
        if not suggestion.choice or suggestion.confidence < 0.7:
            return None
        names = {c.name for c in evidence.candidates}
        return suggestion.choice if suggestion.choice in names else None  # only names that were actually on the page
