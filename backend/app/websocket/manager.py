"""WebSocket transport for telemetry.

* Session channels: events are only ever delivered to connections of the
  session they were published for.
* Every connection has a bounded outgoing queue drained by a single dedicated
  sender coroutine, so `send_text` is never called concurrently on one socket.
* A consumer whose queue fills up (slow / stalled client) is disconnected
  instead of growing memory without bound; it can reconnect and replay.
* Per-session history is bounded (`history_limit`) and the number of tracked
  sessions is bounded (LRU), so memory use is capped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.logging import get_logger
from app.schemas.telemetry import TelemetryEvent

logger = get_logger("ws")

CLOSE_TRY_AGAIN_LATER = 1013
CLOSE_POLICY_VIOLATION = 1008
CLOSE_GOING_AWAY = 1001


@dataclass(eq=False)
class ClientConnection:
    session_id: UUID
    websocket: WebSocket
    queue: asyncio.Queue[str | None]
    connection_id: UUID = field(default_factory=uuid4)
    sender: asyncio.Task[None] | None = None
    closed: bool = False


class _SessionHistory:
    def __init__(self, limit: int) -> None:
        self.events: deque[TelemetryEvent] = deque(maxlen=limit)
        self.ids: set[UUID] = set()

    def add(self, event: TelemetryEvent) -> bool:
        if event.event_id in self.ids:
            return False
        if len(self.events) == self.events.maxlen:
            self.ids.discard(self.events[0].event_id)
        self.events.append(event)
        self.ids.add(event.event_id)
        return True


class WebSocketManager:
    def __init__(
        self,
        *,
        history_limit: int,
        max_connections: int,
        queue_size: int,
        max_sessions: int,
    ) -> None:
        self._history_limit = history_limit
        self._max_connections = max_connections
        self._queue_size = queue_size
        self._max_sessions = max_sessions
        self._sessions: dict[UUID, set[ClientConnection]] = {}
        self._history: OrderedDict[UUID, _SessionHistory] = OrderedDict()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle

    @property
    def connection_count(self) -> int:
        return sum(len(c) for c in self._sessions.values())

    def session_connection_count(self, session_id: UUID) -> int:
        return len(self._sessions.get(session_id, ()))

    async def connect(self, session_id: UUID, websocket: WebSocket) -> ClientConnection | None:
        """Accept and register a connection. Returns None if the server is at capacity."""
        await websocket.accept()
        async with self._lock:
            if self.connection_count >= self._max_connections:
                full = True
            else:
                full = False
                conn = ClientConnection(
                    session_id=session_id,
                    websocket=websocket,
                    queue=asyncio.Queue(maxsize=self._queue_size),
                )
                self._sessions.setdefault(session_id, set()).add(conn)
                conn.sender = asyncio.create_task(self._sender(conn), name=f"ws-sender-{conn.connection_id}")
        if full:
            logger.warning("ws.rejected_capacity", extra={"session": str(session_id)[:8]})
            with contextlib.suppress(Exception):
                await websocket.close(code=CLOSE_TRY_AGAIN_LATER, reason="Server at connection capacity")
            return None
        logger.info(
            "ws.connected",
            extra={"session": str(session_id)[:8], "connections": self.connection_count},
        )
        return conn

    async def disconnect(self, conn: ClientConnection, *, code: int = 1000) -> None:
        async with self._lock:
            peers = self._sessions.get(conn.session_id)
            if peers is not None:
                peers.discard(conn)
                if not peers:
                    del self._sessions[conn.session_id]
        await self._shutdown_connection(conn, code=code)
        logger.info(
            "ws.disconnected",
            extra={"session": str(conn.session_id)[:8], "connections": self.connection_count},
        )

    async def shutdown(self) -> None:
        conns = [c for peers in self._sessions.values() for c in peers]
        for conn in conns:
            await self.disconnect(conn, code=CLOSE_GOING_AWAY)

    async def _shutdown_connection(self, conn: ClientConnection, *, code: int) -> None:
        if conn.sender is not None and not conn.sender.done():
            conn.closed = True
            conn.sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await conn.sender
        conn.closed = True
        if conn.websocket.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await conn.websocket.close(code=code)

    async def _sender(self, conn: ClientConnection) -> None:
        try:
            while True:
                message = await conn.queue.get()
                if message is None:
                    return
                await conn.websocket.send_text(message)
        except asyncio.CancelledError:
            raise
        except Exception:  # client vanished mid-send
            conn.closed = True
            logger.info("ws.send_failed", extra={"session": str(conn.session_id)[:8]})

    # ------------------------------------------------------------------ sending

    def _enqueue(self, conn: ClientConnection, message: str) -> bool:
        if conn.closed:
            return False
        try:
            conn.queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            logger.warning("ws.slow_consumer_dropped", extra={"session": str(conn.session_id)[:8]})
            conn.closed = True
            asyncio.create_task(self.disconnect(conn, code=CLOSE_TRY_AGAIN_LATER))
            return False

    def send_control(self, conn: ClientConnection, message: dict[str, Any]) -> bool:
        """Send a non-telemetry control frame (pong, subscribed, error) to one connection."""
        return self._enqueue(conn, json.dumps(message))

    def send_event(self, conn: ClientConnection, event: TelemetryEvent) -> bool:
        """Send a telemetry event to a single connection without recording history."""
        return self._enqueue(conn, event.model_dump_json())

    async def publish(self, session_id: UUID, event: TelemetryEvent) -> None:
        """Record an event in session history and fan it out to that session only."""
        if event.session_id != session_id:
            raise ValueError("Event session does not match target session.")
        history = self._history_for(session_id)
        if not history.add(event):
            logger.debug("ws.duplicate_event_ignored", extra={"event_id": str(event.event_id)})
            return
        payload = event.model_dump_json()
        for conn in list(self._sessions.get(session_id, ())):
            self._enqueue(conn, payload)

    def replay(self, session_id: UUID, after_event_id: UUID | None) -> tuple[list[TelemetryEvent], bool]:
        """Return events after `after_event_id` and whether the replay is gap-free.

        If the anchor was evicted from the bounded history, all retained events are
        returned and `complete` is False (the client deduplicates by event_id).
        """
        history = self._history.get(session_id)
        if history is None:
            return [], after_event_id is None
        events = list(history.events)
        if after_event_id is None:
            return events, True
        for index, event in enumerate(events):
            if event.event_id == after_event_id:
                return events[index + 1 :], True
        return events, False

    def _history_for(self, session_id: UUID) -> _SessionHistory:
        history = self._history.get(session_id)
        if history is None:
            history = _SessionHistory(self._history_limit)
            self._history[session_id] = history
        else:
            self._history.move_to_end(session_id)
        if len(self._history) > self._max_sessions:
            # Evict least-recently-used histories, never one with live connections.
            for sid in list(self._history):
                if len(self._history) <= self._max_sessions:
                    break
                if sid != session_id and sid not in self._sessions:
                    del self._history[sid]
        return history
