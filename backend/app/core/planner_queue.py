"""Bounded asynchronous planning queue with a fixed pool of workers.

* `submit()` never blocks and never grows the queue past `maxsize`.
* A task id can only be queued or in flight once at a time.
* Every job ends in a callback: success, error, timeout, or cancellation on shutdown,
  so callers can guarantee no task is left in PLANNING.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger("planner_queue")

JobKind = Literal["new", "clarification"]


@dataclass(frozen=True)
class PlanningJob:
    task_id: UUID
    session_id: UUID
    kind: JobKind = "new"


class PlannerQueueFullError(RuntimeError):
    pass


class DuplicateJobError(RuntimeError):
    pass


class PlannerQueueClosedError(RuntimeError):
    pass


Handler = Callable[[PlanningJob], Awaitable[None]]
FailureHandler = Callable[[PlanningJob, str], Awaitable[None]]


class PlannerQueue:
    def __init__(
        self,
        handler: Handler,
        *,
        concurrency: int,
        maxsize: int,
        job_timeout: float,
        on_failure: FailureHandler,
    ) -> None:
        self._handler = handler
        self._concurrency = concurrency
        self._queue: asyncio.Queue[PlanningJob] = asyncio.Queue(maxsize=maxsize)
        self._maxsize = maxsize
        self._job_timeout = job_timeout
        self._on_failure = on_failure
        self._workers: list[asyncio.Task[None]] = []
        self._active: set[UUID] = set()
        self._closed = True

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._workers:
            return
        self._closed = False
        self._workers = [
            asyncio.create_task(self._worker(i), name=f"planner-worker-{i}") for i in range(self._concurrency)
        ]

    async def stop(self) -> None:
        self._closed = True
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        # Anything still queued will never run: fail it explicitly.
        while not self._queue.empty():
            job = self._queue.get_nowait()
            self._queue.task_done()
            self._active.discard(job.task_id)
            await self._safe_failure(job, "PLANNING_CANCELLED")

    # ---------------------------------------------------------------- submission

    @property
    def is_running(self) -> bool:
        return bool(self._workers)

    @property
    def is_full(self) -> bool:
        return self._queue.full()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def in_flight(self) -> int:
        return len(self._active) - self._queue.qsize()

    def is_active(self, task_id: UUID) -> bool:
        return task_id in self._active

    def submit(self, job: PlanningJob) -> None:
        if self._closed:
            raise PlannerQueueClosedError("Planner is shutting down.")
        if job.task_id in self._active:
            raise DuplicateJobError(str(job.task_id))
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as exc:
            raise PlannerQueueFullError("Planner queue is full.") from exc
        self._active.add(job.task_id)

    async def join(self) -> None:
        """Wait until every submitted job has finished (tests / graceful drains)."""
        await self._queue.join()

    # ---------------------------------------------------------------- workers

    async def _worker(self, index: int) -> None:
        while True:
            job = await self._queue.get()
            try:
                await asyncio.wait_for(self._handler(job), timeout=self._job_timeout)
            except asyncio.TimeoutError:
                logger.warning("planner.job_timeout", extra={"task_id": str(job.task_id)})
                await self._safe_failure(job, "PLANNING_TIMEOUT")
            except asyncio.CancelledError:
                await asyncio.shield(self._safe_failure(job, "PLANNING_CANCELLED"))
                raise
            except Exception:  # handler bugs must never kill the worker
                logger.exception("planner.job_crashed", extra={"task_id": str(job.task_id)})
                await self._safe_failure(job, "INTERNAL_PLANNING_ERROR")
            finally:
                self._active.discard(job.task_id)
                self._queue.task_done()

    async def _safe_failure(self, job: PlanningJob, code: str) -> None:
        with contextlib.suppress(Exception):
            await self._on_failure(job, code)
