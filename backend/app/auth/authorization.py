"""Central authorization for every REST route (WebSockets authorize in their handshake).

When authentication is enforced, each request must carry a valid access token (HttpOnly cookie or
Bearer). Then, before the endpoint runs:
  - cookie-authenticated mutations must pass CSRF (double submit + digest bound in the token);
  - READ_ONLY users cannot mutate;
  - per-user API rate limits apply;
  - every resource identifier in the request — session ids (path, query, JSON body), task ids,
    approval ids and file ids — must belong to the authenticated user. A client-supplied id is
    never proof of access; unknown resources fall through to the endpoint's own 404.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.auth.authentication import AuthError
from app.auth.context import AuthUser, current_user
from app.auth.csrf import CSRF_COOKIE, CSRF_HEADER, csrf_ok
from app.auth.policies import MUTATING, may_mutate
from app.core.logging import get_logger

logger = get_logger("authz")
ACCESS_COOKIE = "tp_access"
REFRESH_COOKIE = "tp_refresh"

_UUID = r"[0-9a-fA-F-]{36}"
_TASK = re.compile(rf"^/api/v1/tasks/(?P<id>{_UUID})(/|$)")
_APPROVAL = re.compile(rf"^/api/v1/approvals/(?P<id>{_UUID})(/|$)")
_FILE = re.compile(rf"^/api/v1/files/(?P<id>{_UUID})(/|$)")
_BROWSER_SESSION = re.compile(rf"^/api/v1/browser/sessions/(?P<id>{_UUID})(/|$)")
PUBLIC_PREFIXES = (
    "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh",
    "/api/v1/auth/config", "/api/v1/dev/fixtures/",  # fixtures exist only in development/test
)
PUBLIC_EXACT = frozenset({"/api/v1/auth/logout", "/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"})
# Prometheus may scrape these with METRICS_TOKEN instead of a user session.
TOKEN_PATHS = frozenset({"/api/v1/metrics", "/api/v1/health/details"})


def _deny(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    rid = getattr(request.state, "request_id", None)
    if rid:
        body["request_id"] = rid
    return JSONResponse(status_code=status_code, content=body)


class ResourceAuthorizer:
    """Owner lookups shared by the middleware and the WebSocket handshakes."""

    def __init__(self, container: Any) -> None:
        self.c = container

    async def session(self, user: AuthUser, session_id: UUID) -> bool:
        return await self.c.ownership.claim(session_id, user.id)

    async def task(self, user: AuthUser, task_id: UUID) -> bool | None:
        try:
            task = await self.c.tasks.get_task(task_id)
        except LookupError:
            return None
        owner = self.c.tasks.owner_of(task_id)
        if owner is not None:
            return owner == user.id
        return await self.c.ownership.owner(task.session_id) == user.id

    async def approval(self, user: AuthUser, approval_id: UUID) -> bool | None:
        try:
            approval = self.c.approvals.get(approval_id)
            session_id = approval.session_id
        except LookupError:
            row = await self.c.persistence.approvals.get(approval_id)
            if row is None:
                return None
            if row.user_id is not None:
                return row.user_id == user.id
            session_id = row.session_id
        return await self.c.ownership.owner(session_id) == user.id

    async def file(self, user: AuthUser, file_id: UUID) -> bool | None:
        row = await self.c.persistence.files.get(file_id)
        if row is None:
            return None
        if row.user_id is not None:
            return row.user_id == user.id
        return await self.c.ownership.owner(row.session_id) == user.id


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


async def _json_session_id(request: Request, max_bytes: int) -> tuple[UUID | None, bool]:
    """(session_id from a JSON body, body_ok). Invalid JSON is left to the endpoint's own validation."""
    if request.method not in MUTATING or "application/json" not in request.headers.get("content-type", ""):
        return None, True
    body = await request.body()
    if len(body) > max_bytes:
        return None, False
    try:
        data = json.loads(body or b"null")
    except ValueError:
        return None, True
    raw = data.get("session_id") if isinstance(data, dict) else None
    try:
        return (UUID(str(raw)) if raw else None), True
    except ValueError:
        return None, True


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def authorize(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        container = request.app.state.container
        settings = container.settings
        path = request.url.path
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_request_body_bytes:
            return _deny(request, 413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
        if path.startswith("/api/v1/dev/") and settings.app_env not in ("development", "test"):
            return _deny(request, 404, "NOT_FOUND", "Not Found")  # development routes do not exist elsewhere
        if not settings.auth_enforced or not path.startswith("/api/v1/") or path.startswith(PUBLIC_PREFIXES) \
                or path in PUBLIC_EXACT or request.method == "OPTIONS":
            return await call_next(request)

        token = _bearer(request)
        metrics_token = settings.metrics_token
        if path in TOKEN_PATHS and token and metrics_token is not None:
            import hmac

            if hmac.compare_digest(token, metrics_token.get_secret_value()):
                return await call_next(request)
        via_cookie = token is None
        token = token or request.cookies.get(ACCESS_COOKIE)
        if not token:
            return _deny(request, 401, "AUTHENTICATION_REQUIRED", "Please sign in.")
        try:
            user, claims = await container.auth.authenticate_access(token)
        except AuthError as exc:
            return _deny(request, exc.status_code, exc.code, exc.message)
        if via_cookie and settings.csrf_protection_enabled and not csrf_ok(
                request.method, request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER), claims.csrf_hash):
            return _deny(request, 403, "CSRF_FAILED", "Security check failed. Reload the page and try again.")
        if request.method in MUTATING and not may_mutate(user.role, path):
            return _deny(request, 403, "READ_ONLY_ACCOUNT", "This account can only view.")
        limiter = container.rate_limiter
        if not await limiter.hit(f"api:{user.id}", settings.api_rate_limit_per_minute, 60):
            response = _deny(request, 429, "RATE_LIMITED", "Too many requests. Please slow down.")
            response.headers["Retry-After"] = str(limiter.retry_after(60))
            return response
        if request.method == "POST" and path == "/api/v1/tasks" and not await limiter.hit(
                f"plan:{user.id}", settings.planning_requests_per_minute, 60):
            response = _deny(request, 429, "RATE_LIMITED", "Too many new tasks. Please wait a minute.")
            response.headers["Retry-After"] = str(limiter.retry_after(60))
            return response

        authz = container.authorizer
        session_ids: list[UUID] = []
        for raw in [request.query_params.get("session_id")]:
            if raw:
                try:
                    session_ids.append(UUID(raw))
                except ValueError:
                    pass
        body_sid, body_ok = await _json_session_id(request, settings.max_request_body_bytes)
        if not body_ok:
            return _deny(request, 413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
        if body_sid:
            session_ids.append(body_sid)
        m = _BROWSER_SESSION.match(path)
        if m:
            session_ids.append(UUID(m.group("id")))
        for sid in session_ids:
            if not await authz.session(user, sid):
                return _deny(request, 403, "SESSION_ACCESS_DENIED", "This session belongs to a different account.")
        for pattern, check in ((_TASK, authz.task), (_APPROVAL, authz.approval), (_FILE, authz.file)):
            m = pattern.match(path)
            if m:
                allowed = await check(user, UUID(m.group("id")))
                if allowed is False:
                    logger.warning("authz.denied", extra={"path": pattern.pattern[:30], "user": str(user.id)[:8]})
                    return _deny(request, 403, "RESOURCE_ACCESS_DENIED", "You do not have access to this resource.")
        token_ctx = current_user.set(user)
        try:
            return await call_next(request)
        finally:
            current_user.reset(token_ctx)


# ---------------------------------------------------------------------- WebSockets


class _WsConnections:
    """Per-user WebSocket connection counter (both telemetry and stream sockets)."""

    def __init__(self) -> None:
        self.counts: dict[UUID, int] = {}

    def acquire(self, user_id: UUID, limit: int) -> bool:
        if self.counts.get(user_id, 0) >= limit:
            return False
        self.counts[user_id] = self.counts.get(user_id, 0) + 1
        return True

    def release(self, user_id: UUID) -> None:
        left = self.counts.get(user_id, 0) - 1
        if left <= 0:
            self.counts.pop(user_id, None)
        else:
            self.counts[user_id] = left


async def authorize_websocket(websocket: Any, session_id: UUID) -> tuple[bool, AuthUser | None]:
    """(allowed, user). Checks Origin, the access cookie, session ownership and the per-user socket cap.
    The socket is closed with 1008 when refused. Without enforced auth everything is allowed (development)."""
    container = websocket.app.state.container
    settings = container.settings
    if not settings.auth_enforced:
        return True, None
    origin = websocket.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.cors_origin_list:
        await websocket.close(code=1008, reason="Origin not allowed")
        return False, None
    token = websocket.cookies.get(ACCESS_COOKIE)
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return False, None
    try:
        user, _ = await container.auth.authenticate_access(token)
    except AuthError:
        await websocket.close(code=1008, reason="Authentication required")
        return False, None
    if not await container.authorizer.session(user, session_id):
        await websocket.close(code=1008, reason="Session belongs to another account")
        return False, None
    counter = getattr(container, "_ws_counter", None)
    if counter is None:
        counter = container._ws_counter = _WsConnections()
    if not counter.acquire(user.id, settings.max_websocket_connections_per_user):
        await websocket.close(code=1013, reason="Too many connections")
        return False, None
    return True, user


def release_websocket(websocket: Any, user: AuthUser | None) -> None:
    counter = getattr(websocket.app.state.container, "_ws_counter", None)
    if user is not None and counter is not None:
        counter.release(user.id)
