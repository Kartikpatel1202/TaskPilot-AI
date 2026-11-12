"""Browser status, session, screenshot and live-stream endpoints."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Response, WebSocket
from fastapi.responses import JSONResponse

from app.container import Container
from app.schemas.browser import (
    BrowserSessionCloseRequest,
    BrowserSessionCloseResponse,
    BrowserSessionInfo,
    BrowserStatusResponse,
)
from app.schemas.common import APIError
from app.services.browser_service import BrowserService

from .deps import get_browser_service

router = APIRouter(prefix="/browser", tags=["browser"])
stream_router = APIRouter(prefix="/browser", tags=["browser"])


@router.get("/status", response_model=BrowserStatusResponse, summary="Browser availability (no paths or secrets)")
async def browser_status(service: BrowserService = Depends(get_browser_service)) -> BrowserStatusResponse:
    return service.status()


@router.get("/sessions/{session_id}", response_model=BrowserSessionInfo, responses={404: {"model": APIError}})
async def browser_session(session_id: UUID, service: BrowserService = Depends(get_browser_service)) -> BrowserSessionInfo:
    return service.session_info(session_id)


@router.post(
    "/sessions/{session_id}/close",
    response_model=BrowserSessionCloseResponse,
    responses={403: {"model": APIError}, 404: {"model": APIError}},
)
async def close_browser_session(
    session_id: UUID, body: BrowserSessionCloseRequest, service: BrowserService = Depends(get_browser_service)
) -> BrowserSessionCloseResponse:
    if body.session_id != session_id:
        from app.services.planning_service import TaskSessionMismatchError

        raise TaskSessionMismatchError("Session mismatch.")
    return await service.close_session(session_id)


@router.get(
    "/sessions/{session_id}/screenshot",
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"model": APIError}},
    summary="Latest real browser screenshot (JPEG)",
)
async def browser_screenshot(session_id: UUID, service: BrowserService = Depends(get_browser_service)) -> Response:
    frame = service.latest_frame(session_id)
    if frame is None:
        return JSONResponse(
            status_code=404, content={"code": "SCREENSHOT_NOT_AVAILABLE", "message": "No screenshot has been captured yet."}
        )
    return Response(
        content=frame.jpeg,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Id": str(frame.frame_id),
            "X-Frame-Sequence": str(frame.sequence),
            "X-Captured-At": frame.captured_at.isoformat(),
        },
    )


@stream_router.websocket("/sessions/{session_id}/stream")
async def browser_stream(websocket: WebSocket, session_id: str) -> None:
    try:
        sid = UUID(session_id)
    except ValueError:
        await websocket.close(code=1008, reason="Invalid session id")
        return
    from app.auth.authorization import authorize_websocket, release_websocket

    allowed, ws_user = await authorize_websocket(websocket, sid)
    if not allowed:
        return
    container: Container = websocket.app.state.container
    stream = container.stream
    sub = await stream.connect(sid, websocket)
    if sub is None:
        release_websocket(websocket, ws_user)
        return
    try:
        while not sub.closed:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            raw = message.get("text")
            if raw is None or len(raw) > 1024:
                stream.send_control(sub, {"type": "error", "code": "INVALID_MESSAGE", "message": "Text JSON only."})
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            kind = data.get("type") if isinstance(data, dict) else None
            if kind == "ping":
                stream.send_control(sub, {"type": "pong"})
            elif kind == "subscribe":
                session = container.browser.peek_session(sid)
                settings = container.settings
                stream.send_control(
                    sub,
                    {
                        "type": "stream.ready",
                        "session_id": str(sid),
                        "format": "jpeg",
                        "width": settings.browser_viewport_width,
                        "height": settings.browser_viewport_height,
                        "status": "live" if session is not None else "waiting",
                        "max_fps": settings.browser_screenshot_fps,
                    },
                )
                if session is not None:
                    stream.send_latest(sub)
                    stream.ensure_loop(sid)
            else:
                stream.send_control(sub, {"type": "error", "code": "INVALID_MESSAGE", "message": "Unknown message."})
    except RuntimeError:
        pass
    finally:
        await stream.disconnect(sub)
        release_websocket(websocket, ws_user)
