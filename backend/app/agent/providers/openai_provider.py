"""OpenAI provider (official `openai` SDK, JSON-schema structured outputs)."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger

from .base import (
    InvalidModelOutputError,
    LLMResult,
    LLMUsage,
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderConfigError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    strict_json_schema,
    validate_output,
)

logger = get_logger("llm.openai")


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key: str, model: str, client: Any | None = None) -> None:
        if not api_key and client is None:
            raise ProviderConfigError("OPENAI_API_KEY is not set.")
        self.model = model
        if client is None:
            import openai  # imported lazily so mock mode never loads the SDK

            # Retries are owned by the orchestrator so policy is uniform across providers.
            client = openai.AsyncOpenAI(api_key=api_key, max_retries=0)
        self._client = client

    async def generate_structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        max_tokens: int,
        timeout: float,
    ) -> LLMResult:
        started = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_schema.__name__,
                        "schema": strict_json_schema(response_schema),
                        "strict": True,
                    },
                },
                max_completion_tokens=max_tokens,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - translated into safe ProviderErrors
            raise _translate(exc) from exc

        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise InvalidModelOutputError(detail="No choices returned.")
        message = choice.message
        if getattr(message, "refusal", None):
            raise ProviderRefusalError(detail="Model refusal returned.")
        if choice.finish_reason == "length":
            raise InvalidModelOutputError(detail="Output truncated (finish_reason=length).")
        try:
            raw = json.loads(message.content or "")
        except json.JSONDecodeError as exc:
            raise InvalidModelOutputError(detail="Output was not valid JSON.") from exc

        usage = getattr(response, "usage", None)
        return LLMResult(
            parsed_output=validate_output(raw, response_schema),
            provider=self.name,
            model=getattr(response, "model", None) or self.model,
            usage=LLMUsage(
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            )
            if usage is not None
            else None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_id=getattr(response, "_request_id", None),
        )

    async def health_check(self) -> bool:
        """Cheap reachability probe (model metadata lookup, no generation)."""
        try:
            await self._client.models.retrieve(self.model, timeout=5.0)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("openai.health_check_failed", extra={"error": type(exc).__name__})
            return False

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


def _translate(exc: Exception) -> ProviderError:
    """Map SDK exceptions (most specific first) to safe provider errors."""
    import openai

    detail = type(exc).__name__
    if isinstance(exc, openai.APITimeoutError):
        return ProviderTimeoutError(detail=detail)
    if isinstance(exc, openai.RateLimitError):
        return ProviderRateLimitError(detail=detail)
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderAuthError(detail=detail)
    if isinstance(exc, openai.NotFoundError):
        return ProviderConfigError("The configured OpenAI model was not found.", detail=detail)
    if isinstance(exc, openai.BadRequestError):
        return ProviderBadRequestError(detail=detail)
    if isinstance(exc, openai.InternalServerError):
        return ProviderUnavailableError(detail=detail)
    if isinstance(exc, openai.APIConnectionError):
        return ProviderUnavailableError(detail=detail)
    if isinstance(exc, openai.APIStatusError):
        return ProviderUnavailableError(detail=f"{detail} {exc.status_code}")
    return ProviderError(detail=detail)
