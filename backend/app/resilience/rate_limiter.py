"""Fixed-window rate limiter: Redis-backed (shared across processes) with a bounded in-memory fallback.

If Redis becomes unreachable the limiter keeps enforcing limits per process (degraded, logged) rather
than failing open silently.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from app.core.logging import get_logger

logger = get_logger("ratelimit")


class RateLimiter:
    def __init__(self, redis: Any | None = None, *, enabled: bool = True, prefix: str = "tp:rl:", max_keys: int = 50_000) -> None:
        self._redis = redis
        self.enabled = enabled
        self._prefix = prefix
        self._local: OrderedDict[str, tuple[int, int]] = OrderedDict()
        self._max = max_keys
        self.degraded = False

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Count one event; True if it is within the limit."""
        count = await self.count(key, window_seconds)
        return count <= limit

    async def count(self, key: str, window_seconds: int) -> int:
        if not self.enabled:
            return 0
        window = int(time.time() // window_seconds)
        full = f"{self._prefix}{key}:{window}"
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(full)
                pipe.expire(full, window_seconds + 1)
                value, _ = await pipe.execute()
                self.degraded = False
                return int(value)
            except Exception:  # noqa: BLE001
                if not self.degraded:
                    logger.warning("ratelimit.redis_unavailable_using_local")
                self.degraded = True
        start, value = self._local.get(full, (window, 0))
        value += 1
        self._local[full] = (start, value)
        self._local.move_to_end(full)
        while len(self._local) > self._max:
            self._local.popitem(last=False)
        return value

    def retry_after(self, window_seconds: int) -> int:
        return max(1, window_seconds - int(time.time()) % window_seconds)
