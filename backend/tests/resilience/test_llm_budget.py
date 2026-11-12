"""Phase 6 LLM cost control: the daily token budget refuses further calls explicitly (no mock fallback)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.agent.llm_runner import StructuredLLMRunner
from app.agent.providers.base import LLMResult, LLMUsage
from app.resilience.llm_budget import LLMBudgetExceededError, TokenBudget


class _Out(BaseModel):
    ok: bool


class _Provider:
    name = "fake-real"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured_output(self, *_: Any, **__: Any) -> LLMResult:
        self.calls += 1
        return LLMResult(parsed_output={"ok": True}, provider=self.name, model=self.model, latency_ms=1, usage=LLMUsage(input_tokens=600, output_tokens=500))


@pytest.mark.asyncio
async def test_budget_blocks_calls_once_spent() -> None:
    provider = _Provider()
    runner = StructuredLLMRunner(provider, timeout=5, max_tokens=100, max_retries=0, retry_base_delay=0)  # type: ignore[arg-type]
    runner.budget = TokenBudget(1000)

    async def hook(**kw: Any) -> None:
        usage = kw["usage"]
        await runner.budget.add(usage.input_tokens + usage.output_tokens)

    runner.usage_hook = hook
    await runner.run("system", {"q": 1}, _Out)          # 1100 tokens used -> over budget
    assert await runner.budget.used_today() == 1100
    with pytest.raises(LLMBudgetExceededError) as err:
        await runner.run("system", {"q": 2}, _Out)
    assert err.value.code == "LLM_BUDGET_EXCEEDED" and not err.value.retryable
    assert provider.calls == 1                           # the provider was never called again


@pytest.mark.asyncio
async def test_budget_counter_is_shared_through_redis_when_available() -> None:
    from tests.resilience.conftest import REDIS_URL, redis_available

    if not redis_available():
        pytest.skip("local Redis not available")
    from uuid import uuid4

    from redis.asyncio import from_url

    r = from_url(REDIS_URL.replace("localhost", "127.0.0.1"), decode_responses=True)
    prefix = f"tp:test:{uuid4().hex[:8]}:"
    a, b = TokenBudget(100, r, prefix=prefix), TokenBudget(100, r, prefix=prefix)
    await a.add(60)
    await b.add(50)
    with pytest.raises(LLMBudgetExceededError):
        await a.check()
    keys = [k async for k in r.scan_iter(prefix + "*")]
    await r.delete(*keys)
    await r.aclose()
