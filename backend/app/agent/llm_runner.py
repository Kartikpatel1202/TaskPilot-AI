"""Uniform timeout + retry policy around any `LLMProvider`.

* Transient errors (timeouts, rate limits, 5xx, connection, invalid output) are
  retried up to AGENT_MAX_RETRIES with exponential backoff.
* Auth, configuration, bad-request and refusal errors are never retried.
* A failing real provider never falls back to the mock provider.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel

from app.observability.tracing import span
from app.agent.prompts import build_user_prompt
from app.agent.providers.base import LLMProvider, LLMResult, ProviderError, ProviderTimeoutError, ProviderUnavailableError
from app.resilience.circuit_breaker import CircuitOpenError
from app.core.logging import get_logger

logger = get_logger("agent.llm")


class StructuredLLMRunner:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        timeout: float,
        max_tokens: int,
        max_retries: int,
        retry_base_delay: float,
    ) -> None:
        self.provider = provider
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._delay = retry_base_delay
        # Phase 6 (set by the container): circuit breaker, per-call usage hook, per-user request limits.
        self.breaker: Any = None
        self.usage_hook: Any = None
        self.budget: Any = None  # TokenBudget (real providers only)
        self.prompt_version = "2026-11-p6"

    async def run(self, system_prompt: str, payload: dict[str, Any], schema: type[BaseModel]) -> LLMResult:
        with span("llm.structured_output", component="llm", provider=str(getattr(self.provider, "name", "")),
                  model=str(getattr(self.provider, "model", "") or "")):
            return await self._run(system_prompt, payload, schema)

    async def _run(self, system_prompt: str, payload: dict[str, Any], schema: type[BaseModel]) -> LLMResult:
        if self.budget is not None:
            await self.budget.check()  # LLM_BUDGET_EXCEEDED: explicit failure, never a silent mock fallback
        user_prompt = build_user_prompt(payload)
        attempt = 0
        while True:
            async def _call() -> LLMResult:
                return await asyncio.wait_for(
                    self.provider.generate_structured_output(
                        system_prompt, user_prompt, schema, self._max_tokens, self._timeout
                    ),
                    timeout=self._timeout + 5,
                )

            started = asyncio.get_running_loop().time()
            try:
                if self.breaker is not None:
                    result = await self.breaker.call(_call, is_failure=_transient)
                else:
                    result = await _call()
            except CircuitOpenError as exc:
                # A real provider is failing repeatedly: report it explicitly (never fall back to the mock).
                error = ProviderUnavailableError(detail="circuit open")
                error.retryable = False
                error.__cause__ = exc
            except asyncio.TimeoutError as exc:
                error: ProviderError = ProviderTimeoutError(detail="asyncio timeout")
                error.__cause__ = exc
            except ProviderError as exc:
                error = exc
            else:
                logger.info(
                    "llm.call_ok",
                    extra={
                        "provider": result.provider,
                        "model": result.model,
                        "schema": schema.__name__,
                        "latency_ms": result.latency_ms,
                        "input_tokens": result.usage.input_tokens if result.usage else None,
                        "output_tokens": result.usage.output_tokens if result.usage else None,
                        "attempt": attempt + 1,
                    },
                )
                await self._record(result, schema.__name__, "OK", started)
                return result

            logger.warning(
                "llm.call_failed",
                extra={"provider": self.provider.name, "code": error.code, "detail": error.detail, "attempt": attempt + 1},
            )
            if not error.retryable or attempt >= self._max_retries:
                await self._record(None, schema.__name__, error.code, started)
                raise error
            await asyncio.sleep(self._delay * (2**attempt))
            attempt += 1


    async def _record(self, result: LLMResult | None, request_type: str, outcome: str, started: float) -> None:
        if self.usage_hook is None:
            return
        try:
            latency = int((asyncio.get_running_loop().time() - started) * 1000)
            await self.usage_hook(provider=self.provider.name, model=self.provider.model, request_type=request_type,
                                  prompt_version=self.prompt_version, usage=result.usage if result else None, latency_ms=latency,
                                  outcome=outcome)
        except Exception:  # noqa: BLE001 - accounting never breaks planning
            logger.warning("llm.usage_record_failed")


def _transient(exc: BaseException) -> bool:
    """Only transient provider failures open the circuit (auth/config/bad-request errors never do)."""
    if isinstance(exc, asyncio.TimeoutError):
        return True
    return isinstance(exc, ProviderError) and exc.retryable
