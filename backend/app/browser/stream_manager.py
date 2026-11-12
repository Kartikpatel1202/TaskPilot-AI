"""Live browser frame streaming (binary WebSocket, separate from text telemetry).

Packet: 4-byte big-endian metadata length | UTF-8 JSON metadata | JPEG bytes.

Each subscriber holds at most ONE pending frame: a newer frame replaces an
unsent older one (stale frames are dropped, memory stays bounded), and one
sender coroutine per connection performs every write (no concurrent sends).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import struct
import time
from collections import deque
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.browser.errors import ScreenshotError
from app.browser.session import CapturedFrame
from app.core.execution_events import ExecutionEvents
from app.core.logging import get_logger
from app.schemas.browser import BrowserStreamPayload, FrameMetadata
from app.schemas.telemetry import TelemetryEventType

if TYPE_CHECKING:
    from fastapi import WebSocket

    from app.browser.manager import BrowserManager
    from app.browser.screenshot_manager import ScreenshotManager

logger = get_logger("browser.stream")

HEADER = struct.Struct(">I")
MAX_METADATA_BYTES = 4096
JPEG_MAGIC = b"\xff\xd8\xff"


class FrameProtocolError(ValueError):
    pass


def encode_frame(meta: FrameMetadata, jpeg: bytes) -> bytes:
    body = meta.model_dump_json().encode()
    return HEADER.pack(len(body)) + body + jpeg


def decode_frame(packet: bytes, *, max_frame_bytes: int) -> tuple[dict[str, Any], bytes]:
    """Strict parser (mirrors the frontend's); used by tests and diagnostics."""
    if len(packet) < HEADER.size + 2:
        raise FrameProtocolError("Packet too short.")
    (length,) = HEADER.unpack_from(packet)
    if length == 0 or length > MAX_METADATA_BYTES or HEADER.size + length >= len(packet):
        raise FrameProtocolError("Invalid metadata length.")
    try:
        meta = json.loads(packet[HEADER.size : HEADER.size + length])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameProtocolError("Metadata is not valid JSON.") from exc
    if not isinstance(meta, dict):
        raise FrameProtocolError("Metadata must be an object.")
    FrameMetadata.model_validate(meta)
    image = packet[HEADER.size + length :]
    if len(image) > max_frame_bytes:
        raise FrameProtocolError("Frame exceeds the maximum size.")
    if not image.startswith(JPEG_MAGIC):
        raise FrameProtocolError("Frame is not a JPEG.")
    return meta, image


def frame_metadata(session_id: UUID, frame: CapturedFrame) -> FrameMetadata:
    return FrameMetadata(
        frame_id=frame.frame_id, session_id=session_id, task_id=frame.task_id, sequence=frame.sequence,
        captured_at=frame.captured_at, width=frame.width, height=frame.height,
    )


class StreamSubscriber:
    def __init__(self, session_id: UUID, websocket: WebSocket) -> None:
        self.session_id = session_id
        self.websocket = websocket
        self.pending_frame: bytes | None = None
        self.controls: deque[str] = deque(maxlen=16)
        self.event = asyncio.Event()
        self.dropped_frames = 0
        self.closed = False
        self.sender: asyncio.Task[None] | None = None

    def offer_frame(self, packet: bytes) -> None:
        if self.pending_frame is not None:
            self.dropped_frames += 1  # consumer is behind: keep only the newest frame
        self.pending_frame = packet
        self.event.set()

    def offer_control(self, message: dict[str, Any]) -> None:
        self.controls.append(json.dumps(message, default=str))
        self.event.set()


class BrowserStreamManager:
    def __init__(
        self,
        *,
        manager: BrowserManager,
        screenshots: ScreenshotManager,
        telemetry: ExecutionEvents,
        max_frame_bytes: int,
        max_subscribers_per_session: int = 4,
    ) -> None:
        self._manager = manager
        self._screenshots = screenshots
        self._telemetry = telemetry
        self.max_frame_bytes = max_frame_bytes
        self._max_subs = max_subscribers_per_session
        self._subs: dict[UUID, set[StreamSubscriber]] = {}
        self._loops: dict[UUID, asyncio.Task[None]] = {}
        self._keepalive: dict[UUID, float] = {}

    # ---------------------------------------------------------------- subscribers

    def subscriber_count(self, session_id: UUID) -> int:
        return len(self._subs.get(session_id, ()))

    async def connect(self, session_id: UUID, websocket: WebSocket) -> StreamSubscriber | None:
        await websocket.accept()
        if self.subscriber_count(session_id) >= self._max_subs:
            with contextlib.suppress(Exception):
                await websocket.close(code=1013, reason="Too many stream subscribers for this session")
            return None
        sub = StreamSubscriber(session_id, websocket)
        self._subs.setdefault(session_id, set()).add(sub)
        sub.sender = asyncio.create_task(self._sender(sub), name=f"stream-sender-{session_id}")
        await self._telemetry.emit(
            session_id, TelemetryEventType.BROWSER_STREAM_CONNECTED,
            BrowserStreamPayload(subscribers=self.subscriber_count(session_id)),
        )
        if self._manager.peek_session(session_id) is not None:
            self.ensure_loop(session_id)
        return sub

    async def disconnect(self, sub: StreamSubscriber) -> None:
        if sub.closed:
            return
        sub.closed = True
        peers = self._subs.get(sub.session_id)
        if peers is not None:
            peers.discard(sub)
            if not peers:
                del self._subs[sub.session_id]
        if sub.sender is not None:
            sub.sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sub.sender
        await self._telemetry.emit(
            sub.session_id, TelemetryEventType.BROWSER_STREAM_DISCONNECTED,
            BrowserStreamPayload(subscribers=self.subscriber_count(sub.session_id)),
        )

    async def _sender(self, sub: StreamSubscriber) -> None:
        try:
            while not sub.closed:
                await sub.event.wait()
                sub.event.clear()
                while sub.controls:
                    await sub.websocket.send_text(sub.controls.popleft())
                if sub.pending_frame is not None:
                    packet, sub.pending_frame = sub.pending_frame, None
                    await sub.websocket.send_bytes(packet)
        except asyncio.CancelledError:
            raise
        except Exception:  # client went away mid-send
            sub.closed = True

    def send_control(self, sub: StreamSubscriber, message: dict[str, Any]) -> None:
        if not sub.closed:
            sub.offer_control(message)

    def send_latest(self, sub: StreamSubscriber) -> bool:
        session = self._manager.peek_session(sub.session_id)
        if session is None or session.latest_frame is None:
            return False
        sub.offer_frame(encode_frame(frame_metadata(sub.session_id, session.latest_frame), session.latest_frame.jpeg))
        return True

    # ---------------------------------------------------------------- frames

    def publish(self, session_id: UUID, frame: CapturedFrame) -> int:
        if len(frame.jpeg) > self.max_frame_bytes:
            return 0
        peers = list(self._subs.get(session_id, ()))
        if not peers:
            return 0
        packet = encode_frame(frame_metadata(session_id, frame), frame.jpeg)
        for sub in peers:  # only this session's subscribers — strict isolation
            if not sub.closed:
                sub.offer_frame(packet)
        return len(peers)

    async def capture_and_publish(self, session_id: UUID) -> CapturedFrame | None:
        session = self._manager.peek_session(session_id)
        if session is None:
            return None
        try:
            frame = await self._screenshots.capture(session)
        except ScreenshotError:
            return None
        if frame is not None:
            self.publish(session_id, frame)
        return frame

    def keep_alive(self, session_id: UUID, seconds: float = 6.0) -> None:
        self._keepalive[session_id] = time.monotonic() + seconds
        self.ensure_loop(session_id)

    def ensure_loop(self, session_id: UUID) -> None:
        task = self._loops.get(session_id)
        if task is None or task.done():
            self._loops[session_id] = asyncio.create_task(self._live_loop(session_id), name=f"live-capture-{session_id}")

    async def _live_loop(self, session_id: UUID) -> None:
        """At most `BROWSER_SCREENSHOT_FPS` frames/s while someone watches or an execution runs."""
        try:
            while True:
                session = self._manager.peek_session(session_id)
                if session is None:
                    return
                watching = self.subscriber_count(session_id) > 0
                busy = session.lock.locked() or time.monotonic() < self._keepalive.get(session_id, 0.0)
                if not watching and not busy:
                    return
                if watching and self._screenshots.due(session_id):
                    await self.capture_and_publish(session_id)
                await asyncio.sleep(self._screenshots.min_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stream.live_loop_failed")
        finally:
            self._loops.pop(session_id, None)

    async def close_session(self, session_id: UUID) -> None:
        task = self._loops.pop(session_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for sub in list(self._subs.get(session_id, ())):
            self.send_control(sub, {"type": "stream.ended", "reason": "Browser session closed"})
        self._screenshots.forget(session_id)

    async def shutdown(self) -> None:
        for session_id in list(self._loops):
            await self.close_session(session_id)
        for peers in list(self._subs.values()):
            for sub in list(peers):
                with contextlib.suppress(Exception):
                    await sub.websocket.close(code=1001)
                await self.disconnect(sub)
