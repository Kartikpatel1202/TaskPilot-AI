"""Anthropic provider (official `anthropic` SDK, structured outputs).

Uses `output_config.format` (JSON-schema structured outputs). Forced tool use is
avoided on purpose: current Claude models reject `tool_choice` `tool`/`any`.
Thinking is adaptive on current models; `effort` controls depth and cost.
"""

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

logger = get_logger("llm.anthropic")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        effort: str = "medium",
        server_fallbacks: bool = True,
        client: Any | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ProviderConfigError("ANTHROPIC_API_KEY is not set.")
        self.model = model
        self._effort = effort
        self._server_fallbacks = server_fallbacks
        if client is None:
            import anthropic  # lazy: mock mode never loads the SDK

            client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
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
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "output_config": {
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": strict_json_schema(response_schema)},
            },
            "timeout": timeout,
        }
        try:
            if self._server_fallbacks:
                # On a policy decline the API re-runs the request on a fallback model.
                response = await self._client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **params
                )
            else:
                response = await self._client.messages.create(**params)
        except Exception as exc:  # noqa: BLE001 - translated into safe ProviderErrors
            raise _translate(exc) from exc

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise ProviderRefusalError(detail="stop_reason=refusal")
        if stop_reason == "max_tokens":
            raise InvalidModelOutputError(detail="Output truncated (stop_reason=max_tokens).")

        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if not text:
            raise InvalidModelOutputError(detail="No text block in response.")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidModelOutputError(detail="Output was not valid JSON.") from exc

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        return LLMResult(
            parsed_output=validate_output(raw, response_schema),
            provider=self.name,
            model=getattr(response, "model", None) or self.model,
            usage=LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=(input_tokens or 0) + (output_tokens or 0) if usage is not None else None,
            )
            if usage is not None
            else None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_id=getattr(response, "_request_id", None),
        )

    async def health_check(self) -> bool:
        """Cheap probe via the Models API (no generation, no token spend)."""
        try:
            await self._client.models.retrieve(self.model, timeout=5.0)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("anthropic.health_check_failed", extra={"error": type(exc).__name__})
            return False

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()


def _translate(exc: Exception) -> ProviderError:
    """Map SDK exceptions (most specific first) to safe provider errors."""
    import anthropic

    detail = type(exc).__name__
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderTimeoutError(detail=detail)
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderRateLimitError(detail=detail)
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ProviderAuthError(detail=detail)
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderConfigError("The configured Anthropic model was not found.", detail=detail)
    if isinstance(exc, anthropic.BadRequestError):
        return ProviderBadRequestError(detail=detail)
    if isinstance(exc, anthropic.InternalServerError):
        return ProviderUnavailableError(detail=detail)
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderUnavailableError(detail=detail)
    if isinstance(exc, anthropic.APIStatusError):
        # 529 overloaded and other 5xx-like statuses are transient.
        return ProviderUnavailableError(detail=f"{detail} {exc.status_code}")
    return ProviderError(detail=detail)
