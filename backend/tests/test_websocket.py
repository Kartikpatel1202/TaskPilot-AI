from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.schemas.common import utc_now
from app.schemas.telemetry import TelemetryEvent, TelemetryEventType
from app.websocket.manager import WebSocketManager

from .conftest import of_type, receive_until, wait_for


def _ws_url(session_id: str) -> str:
    return f"/api/v1/ws/{session_id}"


def _post_task(client: TestClient, session_id: str, command: str = "hello") -> str:
    r = client.post("/api/v1/tasks", json={"command": command, "session_id": session_id, "input_mode": "TEXT"})
    assert r.status_code == 202
    return r.json()["task_id"]


def test_client_can_connect_and_receives_connection_ready(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "connection.ready"
        assert ready["session_id"] == session_id
        assert ready["task_id"] is None
        assert ready["sequence"] >= 1
        assert ready["data"]["assistant_name"] == "Kamlesh Bhai"
        assert ready["data"]["demo_endpoints_enabled"] is True
        uuid.UUID(ready["event_id"])


def test_subscribe_is_handled(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "after_event_id": None})
        msg = ws.receive_json()
        assert msg == {"type": "subscribed", "replayed": 0, "complete": True}


def test_ping_receives_pong(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_events_reach_the_correct_session_with_ordering(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        task_id = _post_task(client, session_id, "Open YouTube and search for Python tutorials")
        accepted, _ = receive_until(ws, of_type("task.accepted"))
        assert accepted["task_id"] == task_id
        assert accepted["data"]["state"] == "IDLE"
        log, _ = receive_until(ws, of_type("log.created"))
        assert log["data"]["source"] == "assistant"
        assert log["data"]["language"] == "en"
        assert log["sequence"] > accepted["sequence"]


def test_session_isolation(client: TestClient) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    with client.websocket_connect(_ws_url(a)) as ws_a, client.websocket_connect(_ws_url(b)) as ws_b:
        ws_a.receive_json()
        ws_b.receive_json()
        _post_task(client, a, "secret command for A")
        receive_until(ws_a, of_type("task.accepted"))
        # B must not have received anything; the first thing it sees is the pong.
        ws_b.send_json({"type": "ping"})
        assert ws_b.receive_json() == {"type": "pong"}
        ws_b.send_json({"type": "subscribe", "after_event_id": None})
        assert ws_b.receive_json()["replayed"] == 0


def test_multiple_tabs_share_one_session(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(_ws_url(session_id)) as t1, client.websocket_connect(_ws_url(session_id)) as t2:
        t1.receive_json()
        t2.receive_json()
        task_id = _post_task(client, session_id)
        assert receive_until(t1, of_type("task.accepted"))[0]["task_id"] == task_id
        assert receive_until(t2, of_type("task.accepted"))[0]["task_id"] == task_id


def test_disconnect_cleanup(client: TestClient, session_id: str) -> None:
    manager = client.app.state.container.ws_manager  # type: ignore[attr-defined]
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        assert manager.session_connection_count(uuid.UUID(session_id)) == 1
    assert wait_for(lambda: manager.connection_count == 0)


def test_replay_after_reconnect(client_factory: Any, session_id: str) -> None:
    # Planning disabled so the exact Phase 1 event sequence is asserted.
    client = client_factory(agent_planning_enabled=False)
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        _post_task(client, session_id, "first")
        first, _ = receive_until(ws, of_type("log.created"))
    # Events published while the client is offline are replayed after `after_event_id`.
    _post_task(client, session_id, "second")
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "after_event_id": first["event_id"]})
        replayed = [ws.receive_json(), ws.receive_json()]
        assert [m["type"] for m in replayed] == ["task.accepted", "log.created"]
        assert replayed[0]["data"]["command"] == "second"
        assert ws.receive_json() == {"type": "subscribed", "replayed": 2, "complete": True}


def test_replay_respects_history_limit(client_factory: Any, session_id: str) -> None:
    client = client_factory(telemetry_history_limit=3, agent_planning_enabled=False)
    for i in range(5):  # 5 tasks x 2 events = 10 events
        _post_task(client, session_id, f"cmd {i}")
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "after_event_id": None})
        events = [ws.receive_json() for _ in range(3)]
        done = ws.receive_json()
        assert done == {"type": "subscribed", "replayed": 3, "complete": True}
        seqs = [e["sequence"] for e in events]
        assert seqs == sorted(seqs)
        assert events[-1]["data"]["message"]  # last event is the newest log
        # An evicted anchor yields everything retained, flagged as incomplete.
        ws.send_json({"type": "subscribe", "after_event_id": str(uuid.uuid4())})
        for _ in range(3):
            ws.receive_json()
        assert ws.receive_json() == {"type": "subscribed", "replayed": 3, "complete": False}


@pytest.mark.parametrize(
    "payload",
    ["not json", '{"type": "explode"}', '{"no_type": 1}', '{"type": "subscribe", "after_event_id": "nope"}', "[]"],
)
def test_malformed_messages_do_not_crash_server(client: TestClient, session_id: str, payload: str) -> None:
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        ws.send_text(payload)
        err = ws.receive_json()
        assert err["type"] == "error" and err["code"] == "INVALID_MESSAGE"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_oversized_and_binary_messages_are_rejected(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(_ws_url(session_id)) as ws:
        ws.receive_json()
        ws.send_text('{"type":"ping","x":"' + "a" * 5000 + '"}')
        assert ws.receive_json()["code"] == "MESSAGE_TOO_LARGE"
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_json()["code"] == "UNSUPPORTED_FRAME"


def test_invalid_session_id_is_refused(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(_ws_url("not-a-uuid")) as ws:
            ws.receive_json()


def test_connection_limit_enforced(client_factory: Any) -> None:
    client = client_factory(websocket_max_connections=1)
    with client.websocket_connect(_ws_url(str(uuid.uuid4()))) as ws1:
        ws1.receive_json()
        with client.websocket_connect(_ws_url(str(uuid.uuid4()))) as ws2:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws2.receive_json()
            assert exc.value.code == 1013


# ----------------------------------------------------------------- manager unit tests


class FakeWebSocket:
    def __init__(self, *, fail_send: bool = False, block: bool = False) -> None:
        self.sent: list[str] = []
        self.closed_with: int | None = None
        self.application_state = WebSocketState.CONNECTING
        self._fail = fail_send
        self._block = block

    async def accept(self) -> None:
        self.application_state = WebSocketState.CONNECTED

    async def send_text(self, data: str) -> None:
        if self._fail:
            raise RuntimeError("client went away")
        if self._block:
            await asyncio.sleep(3600)
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_with = code
        self.application_state = WebSocketState.DISCONNECTED


def _event(session_id: uuid.UUID, seq: int, event_id: uuid.UUID | None = None) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=event_id or uuid.uuid4(),
        session_id=session_id,
        task_id=None,
        sequence=seq,
        type=TelemetryEventType.LOG_CREATED,
        occurred_at=utc_now(),
        data={"level": "INFO", "message": f"m{seq}"},
    )


def _manager(**kw: int) -> WebSocketManager:
    defaults = {"history_limit": 5, "max_connections": 10, "queue_size": 8, "max_sessions": 10}
    defaults.update(kw)
    return WebSocketManager(**defaults)


async def test_duplicate_events_are_not_redelivered() -> None:
    manager = _manager()
    sid = uuid.uuid4()
    ws = FakeWebSocket()
    conn = await manager.connect(sid, ws)  # type: ignore[arg-type]
    assert conn is not None
    event = _event(sid, 1)
    await manager.publish(sid, event)
    await manager.publish(sid, event)
    await asyncio.sleep(0.01)
    assert len(ws.sent) == 1
    assert len(manager.replay(sid, None)[0]) == 1
    await manager.disconnect(conn)


async def test_history_is_bounded() -> None:
    manager = _manager(history_limit=5)
    sid = uuid.uuid4()
    for i in range(1, 21):
        await manager.publish(sid, _event(sid, i))
    events, complete = manager.replay(sid, None)
    assert [e.sequence for e in events] == [16, 17, 18, 19, 20]
    assert complete


async def test_tracked_sessions_are_bounded() -> None:
    manager = _manager(max_sessions=3)
    for _ in range(10):
        sid = uuid.uuid4()
        await manager.publish(sid, _event(sid, 1))
    assert len(manager._history) == 3


async def test_slow_consumer_is_dropped_not_buffered_forever() -> None:
    manager = _manager(queue_size=8)
    sid = uuid.uuid4()
    slow = FakeWebSocket(block=True)
    conn = await manager.connect(sid, slow)  # type: ignore[arg-type]
    assert conn is not None
    for i in range(1, 30):
        await manager.publish(sid, _event(sid, i))
    await asyncio.sleep(0.05)
    assert conn.closed
    assert slow.closed_with == 1013
    assert manager.connection_count == 0


async def test_client_disconnect_while_sending_is_handled() -> None:
    manager = _manager()
    sid = uuid.uuid4()
    broken = FakeWebSocket(fail_send=True)
    conn = await manager.connect(sid, broken)  # type: ignore[arg-type]
    assert conn is not None
    await manager.publish(sid, _event(sid, 1))
    await asyncio.sleep(0.01)
    assert conn.closed
    await manager.publish(sid, _event(sid, 2))  # must not raise
    await manager.disconnect(conn)
    assert manager.connection_count == 0


async def test_publish_rejects_cross_session_event() -> None:
    manager = _manager()
    with pytest.raises(ValueError):
        await manager.publish(uuid.uuid4(), _event(uuid.uuid4(), 1))
