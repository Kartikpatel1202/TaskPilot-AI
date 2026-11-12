"""Reliable Redis queue (works with Redis >= 5): pending list -> per-worker processing list.

- enqueue: bounded (atomic Lua depth check) and de-duplicated by `dedupe_key`;
- reserve: BRPOPLPUSH into `processing:<worker>` so a crash never loses the job;
- ack / nack: remove from processing; nack re-queues with the attempt count or dead-letters it;
- reap: a worker whose heartbeat key expired is presumed dead and its processing list is moved
  back to pending (attempts + 1) or to the dead-letter list.
"""

from __future__ import annotations

from typing import Any

from app.queue.base import Job, QueueFullError, QueueUnavailableError

_ENQUEUE = """
if redis.call('LLEN', KEYS[1]) >= tonumber(ARGV[2]) then return -1 end
if ARGV[3] ~= '' then
  if redis.call('SET', KEYS[2], ARGV[4], 'NX', 'EX', tonumber(ARGV[5])) == false then return 0 end
end
redis.call('LPUSH', KEYS[1], ARGV[1])
return 1
"""


class RedisJobQueue:
    def __init__(self, redis: Any, name: str, *, max_depth: int, max_attempts: int, dedupe_ttl_seconds: int = 86_400,
                 prefix: str = "tp:q:") -> None:
        self.r = redis
        self.name = name
        self.max_depth = max_depth
        self.max_attempts = max_attempts
        self.dedupe_ttl = dedupe_ttl_seconds
        base = f"{prefix}{name}"
        self.pending_key = f"{base}:pending"
        self.dlq_key = f"{base}:dead"
        self.proc_prefix = f"{base}:processing:"
        self.dedupe_prefix = f"{base}:dedupe:"
        self.heartbeat_prefix = f"{prefix}worker:"
        self._enqueue = redis.register_script(_ENQUEUE)

    def processing_key(self, worker_id: str) -> str:
        return self.proc_prefix + worker_id

    async def enqueue(self, job: Job) -> bool:
        """True = queued; False = an identical live job already exists. QueueFullError when at max depth."""
        dedupe = job.dedupe_key or ""
        try:
            result = await self._enqueue(keys=[self.pending_key, self.dedupe_prefix + dedupe],
                                         args=[job.dumps(), self.max_depth, dedupe, job.job_id, self.dedupe_ttl])
        except Exception as exc:  # noqa: BLE001
            raise QueueUnavailableError(str(exc)[:200]) from exc
        if int(result) == -1:
            raise QueueFullError(f"The {self.name} queue is full ({self.max_depth} jobs).")
        return int(result) == 1

    async def reserve(self, worker_id: str, timeout: float = 1.0) -> tuple[Job, str] | None:
        raw = await self.r.brpoplpush(self.pending_key, self.processing_key(worker_id), timeout=max(1, int(timeout)))
        if raw is None:
            return None
        return Job.loads(raw), raw if isinstance(raw, str) else raw.decode()

    async def ack(self, worker_id: str, raw: str, job: Job) -> None:
        await self.r.lrem(self.processing_key(worker_id), 1, raw)
        if job.dedupe_key:
            await self.r.delete(self.dedupe_prefix + job.dedupe_key)

    async def nack(self, worker_id: str, raw: str, job: Job, error: str) -> str:
        """Retry (bounded) or dead-letter. Returns 'retried' or 'dead'."""
        job.attempts += 1
        job.last_error = error[:300]
        pipe = self.r.pipeline()
        pipe.lrem(self.processing_key(worker_id), 1, raw)
        if job.attempts >= self.max_attempts:
            pipe.lpush(self.dlq_key, job.dumps())
            if job.dedupe_key:
                pipe.delete(self.dedupe_prefix + job.dedupe_key)
            outcome = "dead"
        else:
            pipe.rpush(self.pending_key, job.dumps())  # front of the queue (consumed from the right)
            outcome = "retried"
        await pipe.execute()
        return outcome

    async def heartbeat(self, worker_id: str, ttl_seconds: int) -> None:
        await self.r.set(self.heartbeat_prefix + worker_id, "1", ex=ttl_seconds)

    async def reap(self) -> dict[str, int]:
        """Return jobs held by dead workers to the queue (or the dead-letter list)."""
        moved = {"requeued": 0, "dead": 0}
        async for key in self.r.scan_iter(match=self.proc_prefix + "*"):
            key = key if isinstance(key, str) else key.decode()
            worker = key[len(self.proc_prefix):]
            if await self.r.exists(self.heartbeat_prefix + worker):
                continue
            while True:
                raw = await self.r.rpop(key)
                if raw is None:
                    break
                job = Job.loads(raw)
                job.attempts += 1
                job.last_error = "worker heartbeat lost"
                if job.attempts >= self.max_attempts:
                    await self.r.lpush(self.dlq_key, job.dumps())
                    if job.dedupe_key:
                        await self.r.delete(self.dedupe_prefix + job.dedupe_key)
                    moved["dead"] += 1
                else:
                    await self.r.rpush(self.pending_key, job.dumps())
                    moved["requeued"] += 1
        return moved

    async def depth(self) -> int:
        return int(await self.r.llen(self.pending_key))

    async def dead_letters(self, limit: int = 100) -> list[Job]:
        return [Job.loads(raw) for raw in await self.r.lrange(self.dlq_key, 0, limit - 1)]

    async def requeue_dead(self, job_id: str) -> bool:
        for raw in await self.r.lrange(self.dlq_key, 0, -1):
            job = Job.loads(raw)
            if job.job_id == job_id:
                await self.r.lrem(self.dlq_key, 1, raw)
                job.attempts = 0
                return await self.enqueue(job)
        return False
