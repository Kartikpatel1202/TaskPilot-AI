"""ExecutionQueue: bounded, one job per task and per session, concurrency, withdraw, shutdown."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.execution.execution_queue import (
    ExecutionAlreadyActiveError,
    ExecutionJob,
    ExecutionQueue,
    ExecutionQueueClosedError,
    ExecutionQueueFullError,
)


class Recorder:
    def __init__(self, hold: asyncio.Event | None = None) -> None:
        self.started: list[UUID] = []
        self.finished: list[UUID] = []
        self.abandoned: list[tuple[UUID, str]] = []
        self.hold = hold or asyncio.Event()
        self.running = 0
        self.peak = 0

    async def handler(self, job: ExecutionJob) -> None:
        self.started.append(job.task_id)
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await self.hold.wait()
        finally:
            self.running -= 1
        self.finished.append(job.task_id)

    async def abandoned_cb(self, job: ExecutionJob, code: str) -> None:
        self.abandoned.append((job.task_id, code))


def job() -> ExecutionJob:
    return ExecutionJob(uuid4(), uuid4())


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_submit_requires_a_started_queue() -> None:
    rec = Recorder()
    q = ExecutionQueue(rec.handler, concurrency=1, maxsize=2, on_abandoned=rec.abandoned_cb)
    with pytest.raises(ExecutionQueueClosedError):
        q.submit(job())


async def test_one_job_per_task_and_per_session() -> None:
    rec = Recorder()
    q = ExecutionQueue(rec.handler, concurrency=1, maxsize=5, on_abandoned=rec.abandoned_cb)
    await q.start()
    first = job()
    q.submit(first)
    with pytest.raises(ExecutionAlreadyActiveError):
        q.submit(ExecutionJob(first.task_id, uuid4()))
    with pytest.raises(ExecutionAlreadyActiveError):
        q.submit(ExecutionJob(uuid4(), first.session_id))
    assert q.is_active(first.task_id) and q.session_busy(first.session_id)
    rec.hold.set()
    await q.join()
    assert not q.is_active(first.task_id) and not q.session_busy(first.session_id)
    await q.stop()


async def test_queue_is_bounded() -> None:
    rec = Recorder()
    q = ExecutionQueue(rec.handler, concurrency=1, maxsize=1, on_abandoned=rec.abandoned_cb)
    await q.start()
    q.submit(job())
    await settle()  # first job taken by the worker (running)
    q.submit(job())  # fills the single queue slot
    assert q.is_full
    with pytest.raises(ExecutionQueueFullError):
        q.submit(job())
    rec.hold.set()
    await q.join()
    await q.stop()


async def test_concurrency_limit_is_respected() -> None:
    rec = Recorder()
    q = ExecutionQueue(rec.handler, concurrency=2, maxsize=10, on_abandoned=rec.abandoned_cb)
    await q.start()
    for _ in range(5):
        q.submit(job())
    await settle()
    assert rec.running == 2
    rec.hold.set()
    await q.join()
    assert rec.peak == 2 and len(rec.finished) == 5
    await q.stop()


async def test_withdrawn_queued_job_never_runs() -> None:
    rec = Recorder()
    q = ExecutionQueue(rec.handler, concurrency=1, maxsize=5, on_abandoned=rec.abandoned_cb)
    await q.start()
    running, queued = job(), job()
    q.submit(running)
    q.submit(queued)
    await settle()
    assert q.is_running(running.task_id) and not q.withdraw_queued(running.task_id)
    assert q.withdraw_queued(queued.task_id)
    rec.hold.set()
    await q.join()
    assert queued.task_id not in rec.started
    assert rec.abandoned == [(queued.task_id, "USER_CANCELLED")]
    await q.stop()


async def test_crashing_handler_releases_the_slot() -> None:
    rec = Recorder()

    async def boom(j: ExecutionJob) -> None:
        raise RuntimeError("worker bug")

    q = ExecutionQueue(boom, concurrency=1, maxsize=2, on_abandoned=rec.abandoned_cb)
    await q.start()
    j = job()
    q.submit(j)
    await q.join()
    assert rec.abandoned == [(j.task_id, "EXECUTION_WORKER_ERROR")]
    q.submit(ExecutionJob(uuid4(), j.session_id))  # the session is usable again
    await q.join()
    await q.stop()


async def test_stop_cancels_running_and_abandons_queued() -> None:
    rec = Recorder()
    q = ExecutionQueue(rec.handler, concurrency=1, maxsize=5, on_abandoned=rec.abandoned_cb)
    await q.start()
    running, queued = job(), job()
    q.submit(running)
    q.submit(queued)
    await settle()
    await q.stop()
    assert running.task_id not in rec.finished
    assert (queued.task_id, "SERVER_SHUTDOWN") in rec.abandoned
    with pytest.raises(ExecutionQueueClosedError):
        q.submit(job())
