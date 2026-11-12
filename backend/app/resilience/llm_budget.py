"""Daily LLM token budget (cost control).

Counts input+output tokens of real-provider calls per UTC day. Once the budget is reached, new LLM calls are
refused with LLM_BUDGET_EXCEEDED until the next UTC day — planning then fails explicitly (it never falls back to
the mock planner). Uses Redis when configured so the count is shared and survives restarts; otherwise counts in
process (reset on restart, reported as such in the docs).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.agent.providers.base import ProviderError


class LLMBudgetExceededError(ProviderError):
    code = "LLM_BUDGET_EXCEEDED"
    retryable = False
    default_message = "Today's AI usage limit has been reached. Please try again tomorrow or ask the administrator to raise it."


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


class TokenBudget:
    def __init__(self, daily_tokens: int, redis: Any = None, *, prefix: str = "tp:llm:tokens:") -> None:
        self.daily_tokens = daily_tokens
        self.redis = redis
        self.prefix = prefix
        self._local: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def used_today(self) -> int:
        day = _day()
        if self.redis is not None:
            try:
                value = await self.redis.get(self.prefix + day)
                return int(value or 0)
            except Exception:  # noqa: BLE001 - fall back to the local count when Redis is down
                pass
        return self._local.get(day, 0)

    async def check(self) -> None:
        if await self.used_today() >= self.daily_tokens:
            raise LLMBudgetExceededError(detail=f"daily budget {self.daily_tokens} reached")

    async def add(self, tokens: int) -> None:
        if tokens <= 0:
            return
        day = _day()
        async with self._lock:
            self._local = {day: self._local.get(day, 0) + tokens}
        if self.redis is not None:
            try:
                key = self.prefix + day
                await self.redis.incrby(key, tokens)
                await self.redis.expire(key, 2 * 86_400)
            except Exception:  # noqa: BLE001
                pass
