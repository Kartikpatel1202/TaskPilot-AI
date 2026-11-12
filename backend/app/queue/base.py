"""Queue contracts shared by the Redis implementation and tests."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


class QueueFullError(RuntimeError):
    """The queue is at its configured depth — callers get a clear overload response (HTTP 503)."""


class QueueUnavailableError(RuntimeError):
    """Redis could not be reached."""


@dataclass
class Job:
    kind: str                     # e.g. "execution", "planning", "cleanup"
    payload: dict[str, Any]
    job_id: str = field(default_factory=lambda: uuid4().hex)
    attempts: int = 0
    enqueued_at: float = field(default_factory=time.time)
    dedupe_key: str | None = None  # one live job per key (e.g. one execution per task)
    last_error: str | None = None

    def dumps(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def loads(raw: str | bytes) -> Job:
        data = json.loads(raw)
        return Job(**data)
