"""MockLLMProvider — deterministic, offline, no API key.

Every plan it produces is labelled mock (`provider="mock"`, `is_mock=True`, and an
explicit assumption line). It is never used as a silent fallback for a real provider.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from pydantic import BaseModel

from app.agent.prompts import extract_task_payload
from app.schemas.intent import IntentClassification
from app.schemas.plan import PlanDraft

from . import mock_scenarios
from .base import InvalidModelOutputError, LLMResult, LLMUsage, ProviderBadRequestError, validate_output

MOCK_MODEL = "taskpilot-mock-v1"


class MockLLMProvider:
    name = "mock"

    def __init__(self, *, latency_ms: int = 0) -> None:
        self.model = MOCK_MODEL
        self._latency = latency_ms / 1000
        self.calls: list[str] = []  # schema names, for tests/diagnostics

    async def generate_structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        max_tokens: int,
        timeout: float,
    ) -> LLMResult:
        started = time.perf_counter()
        self.calls.append(response_schema.__name__)
        payload = extract_task_payload(user_prompt)
        if payload is None:
            raise InvalidModelOutputError(detail="Mock provider could not find the task payload.")
        if self._latency:
            await asyncio.sleep(self._latency)

        output: dict[str, Any]
        if response_schema is IntentClassification:
            output = mock_scenarios.classify(payload)
        elif response_schema is PlanDraft:
            output = mock_scenarios.plan(payload)
        else:
            raise ProviderBadRequestError(detail=f"Unsupported schema {response_schema.__name__}")

        size = len(json.dumps(output))
        return LLMResult(
            parsed_output=validate_output(output, response_schema),
            provider=self.name,
            model=self.model,
            usage=LLMUsage(input_tokens=len(user_prompt) // 4, output_tokens=size // 4, total_tokens=(len(user_prompt) + size) // 4),
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_id=None,
        )

    async def health_check(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None
