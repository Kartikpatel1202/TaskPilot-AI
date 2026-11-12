"""Binary frame protocol + live stream WebSocket (real frames from Chromium via the fixture site)."""

from __future__ import annotations

import json
import struct
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.browser.stream_manager import (
    FrameProtocolError,
    StreamSubscriber,
    decode_frame,
    encode_frame,
)
from app.schemas.browser import FrameMetadata
from app.schemas.common import utc_now

from ..conftest import wait_for_execution
from ..execution.conftest import client, execute, install_plan, nav, planned_task, stop  # noqa: F401

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


def meta(**overrides: Any) -> FrameMetadata:
    base: dict[str, Any] = {
        "frame_id": uuid4(), "session_id": uuid4(), "task_id": None, "sequence": 1,
        "captured_at": utc_now(), "width": 1440, "height": 900,
    }
    base.update(overrides)
    return FrameMetadata(**base)


def test_round_trip() -> None:
    m = meta(sequence=7)
    decoded, image = decode_frame(encode_frame(m, JPEG), max_frame_bytes=10_000)
    assert decoded["sequence"] == 7 and decoded["mime_type"] == "image/jpeg" and image == JPEG
    assert struct.unpack(">I", encode_frame(m, JPEG)[:4])[0] == len(m.model_dump_json().encode())


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\x00\x00",
        struct.pack(">I", 0) + JPEG,
        struct.pack(">I", 999_999) + b"{}" + JPEG,
        struct.pack(">I", 5) + b"nope!" + JPEG,
        struct.pack(">I", 2) + b"[]" + JPEG,
        struct.pack(">I", 2) + b"{}" + JPEG,  # metadata missing required fields
    ],
)
def test_malformed_packets_are_rejected(packet: bytes) -> None:
    with pytest.raises((FrameProtocolError, ValueError)):
        decode_frame(packet, max_frame_bytes=10_000)


def test_non_jpeg_and_oversized_frames_are_rejected() -> None:
    with pytest.raises(FrameProtocolError):
        decode_frame(encode_frame(meta(), b"\x89PNG\r\n" + b"0" * 10), max_frame_bytes=10_000)
    with pytest.raises(FrameProtocolError):
        decode_frame(encode_frame(meta(), JPEG + b"0" * 200), max_frame_bytes=100)


def test_slow_subscriber_keeps_only_the_newest_frame() -> None:
    sub = StreamSubscriber(uuid4(), websocket=None)  # type: ignore[arg-type]
    for i in range(1, 6):
        sub.offer_frame(encode_frame(meta(sequence=i), JPEG))
    decoded, _ = decode_frame(sub.pending_frame or b"", max_frame_bytes=10_000)
    assert decoded["sequence"] == 5 and sub.dropped_frames == 4


def test_control_queue_is_bounded() -> None:
    sub = StreamSubscriber(uuid4(), websocket=None)  # type: ignore[arg-type]
    for i in range(50):
        sub.offer_control({"type": "pong", "i": i})
    assert len(sub.controls) == 16


def _receive_json(ws: Any) -> dict[str, Any]:
    message = ws.receive()
    assert message.get("text") is not None, message
    return json.loads(message["text"])


def test_stream_handshake_ping_and_errors(client: TestClient) -> None:  # noqa: F811
    sid = str(uuid4())
    with client.websocket_connect(f"/api/v1/browser/sessions/{sid}/stream") as ws:
        ws.send_text(json.dumps({"type": "subscribe"}))
        ready = _receive_json(ws)
        assert ready["type"] == "stream.ready" and ready["status"] == "waiting" and ready["format"] == "jpeg"
        ws.send_text(json.dumps({"type": "ping"}))
        assert _receive_json(ws) == {"type": "pong"}
        ws.send_text("not json")
        assert _receive_json(ws)["code"] == "INVALID_MESSAGE"
        ws.send_bytes(b"\x00\x01")
        assert _receive_json(ws)["code"] == "INVALID_MESSAGE"
    # the server notices the disconnect asynchronously; it must release the subscriber promptly
    stream = client.app.state.container.stream  # type: ignore[attr-defined]
    deadline = time.monotonic() + 2.0
    while stream.subscriber_count(UUID(sid)) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert stream.subscriber_count(UUID(sid)) == 0


def test_live_frames_are_real_and_isolated_per_session(client: TestClient, fixture_origin: str) -> None:  # noqa: F811
    sid, other = str(uuid4()), str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [nav(fixture_origin, "index.html"), stop()])
    execute(client, task_id, sid)
    assert wait_for_execution(client, task_id, timeout=60)["state"] == "COMPLETED"

    with client.websocket_connect(f"/api/v1/browser/sessions/{sid}/stream") as ws:
        ws.send_text(json.dumps({"type": "subscribe"}))
        assert _receive_json(ws)["status"] == "live"
        packet = ws.receive()["bytes"]
        decoded, image = decode_frame(packet, max_frame_bytes=300_000)
        assert decoded["session_id"] == sid and image[:3] == b"\xff\xd8\xff" and len(image) > 1000
        latest = client.get(f"/api/v1/browser/sessions/{sid}/screenshot")
        assert latest.status_code == 200 and latest.headers["content-type"] == "image/jpeg"

    # a different session's stream never receives this session's frames
    with client.websocket_connect(f"/api/v1/browser/sessions/{other}/stream") as ws:
        ws.send_text(json.dumps({"type": "subscribe"}))
        ready = _receive_json(ws)
        assert ready["status"] == "waiting" and ready["session_id"] == other
        ws.send_text(json.dumps({"type": "ping"}))
        assert _receive_json(ws) == {"type": "pong"}  # next message is the pong, not a frame


def test_invalid_session_id_is_refused(client: TestClient) -> None:  # noqa: F811
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/browser/sessions/not-a-uuid/stream") as ws:
            ws.receive_text()
