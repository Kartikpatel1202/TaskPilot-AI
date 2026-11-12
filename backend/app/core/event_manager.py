"""Event generation.

The EventManager builds telemetry envelopes (unique IDs, per-session monotonic
sequence numbers, UTC timestamps) and hands them to a transport-agnostic
`EventPublisher`. It knows nothing about WebSockets.
"""

from __future__ import annotations

from typing import Any

import asyncio
from collections import OrderedDict
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.core.logging import get_logger, redact
from app.schemas.common import utc_now
from app.schemas.telemetry import (
    Language,
    LogLevel,
    LogPayload,
    LogSource,
    TelemetryEvent,
    TelemetryEventType,
)

logger = get_logger("events")


class EventPublisher(Protocol):
    async def publish(self, session_id: UUID, event: TelemetryEvent) -> None: ...


class EventManager:
    def __init__(self, publisher: EventPublisher, max_sessions: int) -> None:
        self._publisher = publisher
        self._max_sessions = max_sessions
        self._sequences: OrderedDict[UUID, int] = OrderedDict()
        self._lock = asyncio.Lock()
        # Phase 6: audit trail, metrics and persistence observe every published event (never block it).
        self.taps: list[Any] = []

    async def _next_sequence(self, session_id: UUID) -> int:
        async with self._lock:
            value = self._sequences.pop(session_id, 0) + 1
            self._sequences[session_id] = value  # move to MRU end
            while len(self._sequences) > self._max_sessions:
                self._sequences.popitem(last=False)
            return value

    async def build(
        self,
        session_id: UUID,
        event_type: TelemetryEventType,
        payload: BaseModel,
        task_id: UUID | None = None,
    ) -> TelemetryEvent:
        return TelemetryEvent(
            event_id=uuid4(),
            session_id=session_id,
            task_id=task_id,
            sequence=await self._next_sequence(session_id),
            type=event_type,
            occurred_at=utc_now(),
            data=payload.model_dump(mode="json"),
        )

    async def emit(
        self,
        session_id: UUID,
        event_type: TelemetryEventType,
        payload: BaseModel,
        task_id: UUID | None = None,
    ) -> TelemetryEvent:
        event = await self.build(session_id, event_type, payload, task_id)
        logger.debug(
            "telemetry.emit",
            extra={"event_type": event_type.value, "session": str(session_id)[:8], "seq": event.sequence},
        )
        await self._publisher.publish(session_id, event)
        for tap in self.taps:
            try:
                await tap(event)
            except Exception:  # noqa: BLE001 - an observer must never break the action that emitted the event
                logger.exception("telemetry.tap_failed")
        return event

    async def log(
        self,
        session_id: UUID,
        level: LogLevel,
        message: str,
        *,
        task_id: UUID | None = None,
        source: LogSource = "system",
        language: Language | None = None,
        metadata: dict[str, object] | None = None,
        is_demo: bool = False,
    ) -> TelemetryEvent:
        payload = LogPayload(
            level=level,
            message=message[:2000],
            source=source,
            language=language,
            metadata=redact(metadata) if metadata else None,
            is_demo=is_demo,
        )
        return await self.emit(session_id, TelemetryEventType.LOG_CREATED, payload, task_id)
