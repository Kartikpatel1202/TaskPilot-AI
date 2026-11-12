"""`WS /api/v1/ws/{session_id}` — real-time telemetry channel."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError

from app.auth.authorization import authorize_websocket, release_websocket
from app.config import APP_VERSION
from app.container import Container
from app.core.logging import get_logger
from app.schemas.telemetry import (
    ConnectionReadyPayload,
    PingMessage,
    SubscribeMessage,
    TelemetryEventType,
    client_message_adapter,
)
from app.websocket.manager import CLOSE_POLICY_VIOLATION

router = APIRouter(tags=["websocket"])
logger = get_logger("ws.endpoint")


@router.websocket("/ws/{session_id}")
async def telemetry_socket(websocket: WebSocket, session_id: str) -> None:
    try:
        sid = UUID(session_id)
    except ValueError:
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="Invalid session id")
        return

    container: Container = websocket.app.state.container
    manager = container.ws_manager
    settings = container.settings

    allowed, ws_user = await authorize_websocket(websocket, sid)  # Phase 6: cookie auth, Origin, ownership, per-user cap
    if not allowed:
        return
    conn = await manager.connect(sid, websocket)
    if conn is None:
        release_websocket(websocket, ws_user)
        return

    try:
        # Sent only to this connection and not stored in history.
        ready = await container.events.build(
            sid,
            TelemetryEventType.CONNECTION_READY,
            ConnectionReadyPayload(
                connection_id=conn.connection_id,
                server_version=APP_VERSION,
                assistant_name=settings.assistant_name,
                heartbeat_interval_seconds=settings.websocket_heartbeat_seconds,
                history_limit=settings.telemetry_history_limit,
                demo_endpoints_enabled=settings.demo_endpoints_active,
            ),
        )
        manager.send_event(conn, ready)

        while not conn.closed:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            raw = message.get("text")
            if raw is None:
                manager.send_control(
                    conn, {"type": "error", "code": "UNSUPPORTED_FRAME", "message": "Only text frames are supported."}
                )
                continue
            if len(raw.encode("utf-8")) > settings.websocket_max_message_bytes:
                manager.send_control(
                    conn, {"type": "error", "code": "MESSAGE_TOO_LARGE", "message": "Message exceeds size limit."}
                )
                continue
            try:
                parsed = client_message_adapter.validate_json(raw)
            except ValidationError:
                logger.info("ws.malformed_message", extra={"session": str(sid)[:8]})
                manager.send_control(
                    conn, {"type": "error", "code": "INVALID_MESSAGE", "message": "Malformed or unknown message."}
                )
                continue

            if isinstance(parsed, PingMessage):
                manager.send_control(conn, {"type": "pong"})
            elif isinstance(parsed, SubscribeMessage):
                events, complete = manager.replay(sid, parsed.after_event_id)
                for event in events:
                    manager.send_event(conn, event)
                manager.send_control(conn, {"type": "subscribed", "replayed": len(events), "complete": complete})
    except RuntimeError:
        # Raised by Starlette if the socket is already closed underneath us.
        pass
    finally:
        await manager.disconnect(conn)
        release_websocket(websocket, ws_user)
