"""Scenario 10 — queue resilience against a real (local) Redis: bounded depth, de-duplication, worker crash
+ restart recovery, bounded retries, dead letters, locks with ownership tokens, and Run Plan via Redis."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.queue.base import Job, QueueFullError
from app.queue.job_registry import JobRegistry
from app.queue.locks import RedisLock, SessionLocks, LockNotAcquiredError
from app.queue.redis_queue import RedisJobQueue
from app.queue.worker import QueueWorker

from .conftest import REDIS_URL, needs_redis

pytestmark = needs_redis


def _queue(r: object, prefix: str, **kw: object) -> RedisJobQueue:
    return RedisJobQueue(r, "execution", max_depth=kw.get("max_depth", 3), max_attempts=kw.get("max_attempts", 3), prefix=prefix)  # type: ignore[arg-type]


async def test_overload_is_rejected_and_duplicates_are_ignored(redis_client, prefix) -> None:  # noqa: ANN001
    q = _queue(redis_client, prefix)
    assert await q.enqueue(Job("execution", {"n": 1}, dedupe_key="task:1"))
    assert not await q.enqueue(Job("execution", {"n": 1}, dedupe_key="task:1"))  # one live job per task
    assert await q.enqueue(Job("execution", {"n": 2}))
    assert await q.enqueue(Job("execution", {"n": 3}))
    with pytest.raises(QueueFullError):
        await q.enqueue(Job("execution", {"n": 4}))
    assert await q.depth() == 3  # bounded, nothing silently dropped or added


async def test_worker_crash_then_restart_recovers_the_job(redis_client, prefix) -> None:  # noqa: ANN001
    q = _queue(redis_client, prefix)
    await q.enqueue(Job("execution", {"task": "t1"}, dedupe_key="task:t1"))
    # worker A reserves the job and dies (no heartbeat, never acks)
    job, raw = await q.reserve("worker-a", timeout=1)
    assert job.payload == {"task": "t1"} and await q.depth() == 0
    handled: list[dict] = []
    registry = JobRegistry()

    async def handle(payload: dict) -> None:
        handled.append(payload)

    registry.register("execution", handle)
    worker_b = QueueWorker(q, registry, worker_id="worker-b", heartbeat_seconds=1)
    await worker_b.start()  # start() reaps jobs of dead workers before consuming
    for _ in range(50):
        if handled:
            break
        await asyncio.sleep(0.1)
    await worker_b.stop()
    assert handled == [{"task": "t1"}]
    assert await redis_client.llen(q.processing_key("worker-a")) == 0 and await q.depth() == 0
    assert (await q.dead_letters()) == []


async def test_failing_jobs_retry_boundedly_then_dead_letter(redis_client, prefix) -> None:  # noqa: ANN001
    q = _queue(redis_client, prefix, max_attempts=2)
    await q.enqueue(Job("execution", {"x": 1}))
    registry = JobRegistry()
    calls = {"n": 0}

    async def boom(payload: dict) -> None:
        calls["n"] += 1
        raise RuntimeError("transient")

    registry.register("execution", boom)
    worker = QueueWorker(q, registry, worker_id="w-dlq", heartbeat_seconds=1)
    for _ in range(3):
        reserved = await q.reserve("w-dlq", timeout=1)
        if reserved is None:
            break
        await worker.run_one(*reserved)
    dead = await q.dead_letters()
    assert calls["n"] == 2 and len(dead) == 1 and dead[0].attempts == 2 and "transient" in (dead[0].last_error or "")
    unknown = Job("mystery", {})
    await q.enqueue(unknown)
    await worker.run_one(*(await q.reserve("w-dlq", timeout=1)))  # unknown kinds go straight to the dead-letter list
    assert any(j.kind == "mystery" for j in await q.dead_letters())
    assert await q.requeue_dead(dead[0].job_id) and await q.depth() == 1


async def test_locks_have_owners_and_expire(redis_client, prefix) -> None:  # noqa: ANN001
    a = RedisLock(redis_client, prefix + "lock", ttl_ms=500)
    b = RedisLock(redis_client, prefix + "lock", ttl_ms=500)
    assert await a.acquire() and not await b.acquire()
    assert not await b.release()  # a different owner can never release it
    assert await a.renew()
    await asyncio.sleep(0.7)
    assert await b.acquire()  # no permanent locks
    locks = SessionLocks(redis_client, ttl_ms=600, prefix=prefix + "session:")
    async with locks.hold("s1"):
        with pytest.raises(LockNotAcquiredError):
            async with locks.hold("s1", wait_seconds=0.2):
                pass


def test_run_plan_through_the_redis_queue(fixture_origin: str) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    from ..conftest import browser_settings
    from ..execution.conftest import execute, install_plan, nav, planned_task, results, stop
    from ..conftest import wait_for_execution

    settings = browser_settings(fixture_origin, redis_url=REDIS_URL, queue_backend="redis", queue_max_depth=50)
    with TestClient(create_app(settings)) as client:
        sid = str(uuid.uuid4())
        task_id = planned_task(client, sid)
        install_plan(client, task_id, [nav(fixture_origin, "index.html"), stop()])
        assert execute(client, task_id, sid).status_code == 202
        assert wait_for_execution(client, task_id)["state"] == "COMPLETED"
        assert [r["status"] for r in results(client, task_id)] == ["SUCCEEDED", "SUCCEEDED"]
        assert type(client.app.state.container.execution.queue).__name__ == "RedisExecutionQueue"  # type: ignore[attr-defined]
