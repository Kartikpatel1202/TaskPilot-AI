"""Rate limits: per-user API and planning limits (429 + Retry-After), Redis-shared counters, degraded fallback."""

from __future__ import annotations

import asyncio

import pytest

from app.resilience.rate_limiter import RateLimiter

from .conftest import Users


def test_api_limit_returns_429_with_retry_after(secure_factory) -> None:  # noqa: ANN001
    client = secure_factory(api_rate_limit_per_minute=5)
    users = Users(client)
    a = users.new("rl@example.com")
    codes = [users.get(a, "/api/v1/auth/me").status_code for _ in range(7)]
    assert codes.count(429) >= 1 and codes[0] == 200
    r = users.get(a, "/api/v1/auth/me")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    b = users.new("rl2@example.com")  # limits are per user
    assert users.get(b, "/api/v1/auth/me").status_code == 200


def test_planning_limit(secure_factory) -> None:  # noqa: ANN001
    client = secure_factory(planning_requests_per_minute=2)
    users = Users(client)
    a = users.new("rl3@example.com")
    codes = [users.post(a, "/api/v1/tasks", {"command": "hello", "session_id": a.session_id, "input_mode": "TEXT"}).status_code
             for _ in range(3)]
    assert codes == [202, 202, 429]


def _redis_available() -> bool:
    try:
        import redis

        return bool(redis.Redis(socket_connect_timeout=0.5).ping())
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _redis_available(), reason="local Redis not running")
async def test_redis_counters_are_shared_between_processes() -> None:
    from redis.asyncio import Redis

    r1, r2 = Redis(decode_responses=True), Redis(decode_responses=True)
    prefix = f"tp:test:rl:{id(r1)}:"
    a, b = RateLimiter(r1, prefix=prefix), RateLimiter(r2, prefix=prefix)
    results = [await a.hit("k", 3, 60), await b.hit("k", 3, 60), await a.hit("k", 3, 60), await b.hit("k", 3, 60)]
    assert results == [True, True, True, False]
    await r1.aclose()
    await r2.aclose()


async def test_redis_outage_degrades_to_local_limits_not_fail_open() -> None:
    class DeadRedis:
        def pipeline(self) -> "DeadRedis":
            return self

        def incr(self, *_: object) -> None:
            pass

        def expire(self, *_: object) -> None:
            pass

        async def execute(self) -> None:
            raise ConnectionError("redis down")

    limiter = RateLimiter(DeadRedis())
    results = [await limiter.hit("login:x", 2, 60) for _ in range(3)]
    assert results == [True, True, False] and limiter.degraded
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_browser_action_limit_blocks_before_the_step_runs() -> None:
    """A limited step is reported BLOCKED/RATE_LIMITED and its handler (and journal) never run."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.browser.executor import PlanExecutor

    ran: list[str] = []
    executor = PlanExecutor(stream=None, step_timeout_seconds=5)  # type: ignore[arg-type]
    limiter = RateLimiter(None, enabled=True)
    executor.rate_limiter, executor.actions_per_minute = limiter, 2

    async def journaled(ctx, step):  # noqa: ANN001, ANN202
        ran.append(step.order)
        return "RAN"

    executor._run_step_journaled = journaled  # type: ignore[method-assign]
    results: list[object] = []
    ctx = SimpleNamespace(user_id=uuid4(), session_id=uuid4(),
                          result=lambda status, message, error_code=None: (status.value, error_code))
    step = SimpleNamespace(order=1, action=SimpleNamespace(type="click"))
    for _ in range(3):
        results.append(await executor._run_step(ctx, step))  # type: ignore[arg-type]
    assert results[:2] == ["RAN", "RAN"]
    assert results[2] == ("BLOCKED", "RATE_LIMITED")
    assert len(ran) == 2


@pytest.mark.asyncio
async def test_commerce_search_limit_is_wired() -> None:
    """The container gives the commerce manager and the executor the shared limiter with the configured limits."""
    from app.container import build_container

    from tests.conftest import make_settings

    container = build_container(make_settings(commerce_enabled=True, rate_limit_enabled=True, browser_actions_per_minute=7))
    assert container.execution.executor.rate_limiter is container.rate_limiter
    assert container.execution.executor.actions_per_minute == 7
    assert container.commerce is not None and container.commerce.rate_limiter is container.rate_limiter
