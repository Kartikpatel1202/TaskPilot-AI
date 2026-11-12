"""WebSockets: authenticated handshake, Origin validation, session ownership and per-user caps."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from .conftest import Users


def _connect(client: TestClient, path: str, origin: str | None = "http://localhost:3000") -> None:
    headers = {"origin": origin} if origin else {}
    with client.websocket_connect(path, headers=headers) as ws:
        ws.receive_json()


def test_unauthenticated_socket_is_refused(secure_app: TestClient) -> None:
    secure_app.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as exc:
        _connect(secure_app, "/api/v1/ws/00000000-0000-4000-8000-000000000001")
    assert exc.value.code == 1008


def test_owner_connects_others_and_foreign_origins_do_not(users: Users) -> None:
    a = users.new("ws1@example.com")
    b = users.new("ws2@example.com")
    _connect(users.as_(a), f"/api/v1/ws/{a.session_id}")  # connection.ready received
    with pytest.raises(WebSocketDisconnect) as exc:
        _connect(users.as_(b), f"/api/v1/ws/{a.session_id}")
    assert exc.value.code == 1008
    with pytest.raises(WebSocketDisconnect) as exc:
        _connect(users.as_(a), f"/api/v1/ws/{a.session_id}", origin="https://evil.example")
    assert exc.value.code == 1008
    with pytest.raises(WebSocketDisconnect) as exc:  # the binary screenshot stream is protected the same way
        with users.as_(b).websocket_connect(f"/api/v1/browser/sessions/{a.session_id}/stream") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_per_user_connection_cap(secure_factory) -> None:  # noqa: ANN001
    client = secure_factory(max_websocket_connections_per_user=1)
    users = Users(client)
    a = users.new("ws3@example.com")
    c = users.as_(a)
    with c.websocket_connect(f"/api/v1/ws/{a.session_id}", headers={"origin": "http://localhost:3000"}) as first:
        first.receive_json()
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect(f"/api/v1/ws/{a.session_id}") as second:
                second.receive_json()
        assert exc.value.code == 1013
