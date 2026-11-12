"""Bounded planning queue: processing, concurrency, overload, failures, shutdown, dedupe."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.core.planner_queue import DuplicateJobError, PlannerQueue, PlannerQueueClosedError, PlannerQueueFullError, PlanningJob


class Recorder:
    def __init__(self) -> None:
        self.done: list[PlanningJob] = []
        self.failed: list[tuple[PlanningJob, str]] = []
        self.running = 0
        self.max_running = 0

    async def failure(self, job: PlanningJob, code: str) -> None:
        self.failed.append((job, code))


def job() -> PlanningJob:
    return PlanningJob(uuid4(), uuid4())


def make(rec: Recorder, handler=None, **kw) -> PlannerQueue:  # type: ignore[no-untyped-def]
    async def default(j: PlanningJob) -> None:
        rec.running += 1
        rec.max_running = max(rec.max_running, rec.running)
        await asyncio.sleep(0.02)
        rec.running -= 1
        rec.done.append(j)

    opts = {"concurrency": 2, "maxsize": 10, "job_timeout": 5.0}
    opts.update(kw)
    return PlannerQueue(handler or default, on_failure=rec.failure, **opts)


async def test_insertion_and_processing() -> None:
    rec = Recorder()
    q = make(rec)
    await q.start()
    j = job()
    q.submit(j)
    await q.join()
    assert rec.done == [j] and not q.is_active(j.task_id)
    await q.stop()


async def test_concurrency_is_bounded() -> None:
    rec = Recorder()
    q = make(rec, concurrency=3)
    await q.start()
    for _ in range(9):
        q.submit(job())
    await q.join()
    assert len(rec.done) == 9 and rec.max_running == 3
    await q.stop()


async def test_queue_full_is_rejected_not_dropped() -> None:
    rec = Recorder()
    q = make(rec, maxsize=2)
    await q.start()
    gate = asyncio.Event()

    async def blocked(j: PlanningJob) -> None:
        await gate.wait()

    q._handler = blocked  # type: ignore[assignment]
    for _ in range(2):
        q.submit(job())
    await asyncio.sleep(0.01)  # two workers pick them up
    q.submit(job())
    q.submit(job())
    assert q.is_full
    with pytest.raises(PlannerQueueFullError):
        q.submit(job())
    gate.set()
    await q.join()
    await q.stop()


async def test_duplicate_jobs_are_rejected() -> None:
    rec = Recorder()
    q = make(rec)
    await q.start()
    j = job()
    q.submit(j)
    with pytest.raises(DuplicateJobError):
        q.submit(PlanningJob(j.task_id, j.session_id, "clarification"))
    await q.join()
    q.submit(j)  # allowed again once finished
    await q.join()
    assert len(rec.done) == 2
    await q.stop()


async def test_timeout_and_worker_exception_report_failure_and_worker_survives() -> None:
    rec = Recorder()
    calls = {"n": 0}

    async def handler(j: PlanningJob) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(1)  # exceeds timeout
        elif calls["n"] == 2:
            raise RuntimeError("bug")
        rec.done.append(j)

    q = make(rec, handler, concurrency=1, job_timeout=0.05)
    await q.start()
    a, b, c = job(), job(), job()
    for j in (a, b, c):
        q.submit(j)
    await q.join()
    assert rec.failed == [(a, "PLANNING_TIMEOUT"), (b, "INTERNAL_PLANNING_ERROR")]
    assert rec.done == [c]
    await q.stop()


async def test_shutdown_cancels_in_flight_and_fails_queued_jobs() -> None:
    rec = Recorder()

    async def slow(j: PlanningJob) -> None:
        await asyncio.sleep(10)

    q = make(rec, slow, concurrency=1)
    await q.start()
    running, queued = job(), job()
    q.submit(running)
    q.submit(queued)
    await asyncio.sleep(0.01)
    await q.stop()
    codes = {j.task_id: code for j, code in rec.failed}
    assert codes == {running.task_id: "PLANNING_CANCELLED", queued.task_id: "PLANNING_CANCELLED"}
    with pytest.raises(PlannerQueueClosedError):
        q.submit(job())
