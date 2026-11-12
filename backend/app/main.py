"""TaskPilot AI backend — FastAPI application factory.

Run with:  python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import time

from app.agent.providers import LLMProvider
from app.auth.authorization import install_auth_middleware
from app.auth.context import correlation_id
from app.database.session import DatabaseUnavailableError
from app.queue.base import QueueFullError, QueueUnavailableError
from app.api import api_router, ws_router
from app.config import APP_VERSION, Settings, get_settings
from app.container import build_container
from app.core.logging import configure_logging, get_logger
from app.core.state_machine import InvalidTransitionError
from app.schemas.common import APIError
from app.services.approval_service import (
    ApprovalAlreadyResolvedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
)
from app.services.planning_service import (
    PlannerBusyError,
    PlanNotFoundError,
    PlanNotReadyError,
    TaskNotAwaitingClarificationError,
    TaskSessionMismatchError,
)
from app.services.task_service import TaskNotFoundError
from app.browser.errors import BrowserError
from app.commerce.commerce_manager import CommerceRequestError
from app.integrations.integration_manager import IntegrationRequestError
from app.execution.execution_manager import ExecutionError

_BROWSER_STATUS = {
    "BROWSER_SESSION_NOT_FOUND": 404,
    "BROWSER_UNAVAILABLE": 503,
    "BROWSER_SESSION_LIMIT_REACHED": 503,
}

logger = get_logger("app")
REQUEST_ID_HEADER = "X-Request-ID"

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    410: "GONE",
    413: "PAYLOAD_TOO_LARGE",
    429: "TOO_MANY_REQUESTS",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error(request: Request, status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None) -> JSONResponse:
    body = APIError(code=code, message=message, request_id=_request_id(request), details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": str(err.get("msg", "")), "type": err.get("type")}
            for err in exc.errors()
        ]
        return _error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Request validation failed.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error(request, exc.status_code, code, message)

    @app.exception_handler(TaskNotFoundError)
    async def _task_nf(request: Request, exc: TaskNotFoundError) -> JSONResponse:
        return _error(request, 404, "TASK_NOT_FOUND", "Task not found.")

    @app.exception_handler(ApprovalNotFoundError)
    async def _appr_nf(request: Request, exc: ApprovalNotFoundError) -> JSONResponse:
        return _error(request, 404, "APPROVAL_NOT_FOUND", "Approval request not found.")

    @app.exception_handler(ApprovalAlreadyResolvedError)
    async def _appr_conflict(request: Request, exc: ApprovalAlreadyResolvedError) -> JSONResponse:
        return _error(
            request, 409, "APPROVAL_ALREADY_RESOLVED",
            f"This approval was already resolved ({exc.status.value}). Decisions are immutable.",
        )

    @app.exception_handler(ApprovalExpiredError)
    async def _appr_expired(request: Request, exc: ApprovalExpiredError) -> JSONResponse:
        return _error(request, 410, "APPROVAL_EXPIRED", "This approval request has expired and can no longer be decided.")

    @app.exception_handler(PlannerBusyError)
    async def _busy(request: Request, exc: PlannerBusyError) -> JSONResponse:
        response = _error(request, 503, "PLANNER_BUSY", str(exc))
        response.headers["Retry-After"] = "5"
        return response

    @app.exception_handler(TaskSessionMismatchError)
    async def _mismatch(request: Request, exc: TaskSessionMismatchError) -> JSONResponse:
        return _error(request, 403, "TASK_SESSION_MISMATCH", "This task belongs to a different session.")

    @app.exception_handler(TaskNotAwaitingClarificationError)
    async def _not_awaiting(request: Request, exc: TaskNotAwaitingClarificationError) -> JSONResponse:
        return _error(
            request, 409, "TASK_NOT_AWAITING_CLARIFICATION",
            f"This task is {exc.state.value} and is not waiting for a clarification.",
        )

    @app.exception_handler(PlanNotReadyError)
    async def _plan_not_ready(request: Request, exc: PlanNotReadyError) -> JSONResponse:
        return _error(request, 409, "PLAN_NOT_READY", f"Planning has not finished yet (task is {exc.state.value}).")

    @app.exception_handler(PlanNotFoundError)
    async def _plan_not_found(request: Request, exc: PlanNotFoundError) -> JSONResponse:
        return _error(request, 404, "PLAN_NOT_FOUND", "No plan exists for this task.")

    @app.exception_handler(CommerceRequestError)
    async def _commerce(request: Request, exc: CommerceRequestError) -> JSONResponse:
        return _error(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(IntegrationRequestError)
    async def _integration(request: Request, exc: IntegrationRequestError) -> JSONResponse:
        return _error(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(ExecutionError)
    async def _execution(request: Request, exc: ExecutionError) -> JSONResponse:
        response = _error(request, exc.status_code, exc.code, exc.message)
        if exc.status_code == 503:
            response.headers["Retry-After"] = "10"
        return response

    @app.exception_handler(BrowserError)
    async def _browser(request: Request, exc: BrowserError) -> JSONResponse:
        return _error(request, _BROWSER_STATUS.get(exc.code, 409), exc.code, exc.message)

    @app.exception_handler(InvalidTransitionError)
    async def _transition(request: Request, exc: InvalidTransitionError) -> JSONResponse:
        return _error(request, 409, "INVALID_STATE_TRANSITION", str(exc))

    @app.exception_handler(DatabaseUnavailableError)
    async def _db_down(request: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        response = _error(request, 503, "DATABASE_UNAVAILABLE", "The service is temporarily unavailable. Nothing was saved; please retry.")
        response.headers["Retry-After"] = "10"
        return response

    @app.exception_handler(QueueFullError)
    async def _queue_full(request: Request, exc: QueueFullError) -> JSONResponse:
        response = _error(request, 503, "QUEUE_FULL", "The system is busy. Please try again shortly.")
        response.headers["Retry-After"] = "10"
        return response

    @app.exception_handler(QueueUnavailableError)
    async def _queue_down(request: Request, exc: QueueUnavailableError) -> JSONResponse:
        return _error(request, 503, "QUEUE_UNAVAILABLE", "The task queue is temporarily unavailable.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        from app.observability.error_reporting import report

        report(exc, component="api", metrics=request.app.state.container.metrics, path=request.url.path, request_id=_request_id(request))
        return _error(request, 500, "INTERNAL_ERROR", "An unexpected error occurred.")


async def _approval_sweeper(app: FastAPI) -> None:
    container = app.state.container
    interval = container.settings.approval_sweep_interval_seconds
    ticks = 0
    while True:
        await asyncio.sleep(interval)
        ticks += 1
        try:
            await container.approvals.expire_overdue()
            if ticks % 12 == 0:  # roughly once a minute at the default interval
                container.memory.prune_expired()
                await container.browser.expire_idle()
            if ticks % 60 == 0:  # roughly every five minutes: expired files and persisted memory
                await container.run_maintenance()
        except Exception:
            logger.exception("approval_sweeper_failed")


def create_app(settings: Settings | None = None, *, provider: LLMProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "startup",
            extra={
                "env": settings.app_env,
                "demo_endpoints": settings.demo_endpoints_active,
                "version": APP_VERSION,
                "agent_provider": settings.effective_agent_provider,
                "agent_model": settings.resolved_agent_model,
                "planning_enabled": settings.agent_planning_enabled,
            },
        )
        await app.state.container.startup()  # Phase 6: schema check, bootstrap owner, recovery
        sweeper = asyncio.create_task(_approval_sweeper(app), name="approval-sweeper")
        await app.state.container.planning.start()
        # Chromium itself is launched lazily, on the first accepted Run Plan (never during planning).
        await app.state.container.execution.start()
        await app.state.container.run_recovery()  # Phase 6: reconcile persisted state before serving traffic
        try:
            yield
        finally:
            # Order: stop accepting/cancel executions -> close streams -> close browser -> planner.
            await app.state.container.execution.stop()
            await app.state.container.stream.shutdown()
            await app.state.container.browser.shutdown()
            await app.state.container.planning.stop()
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper
            await app.state.container.demo.shutdown()
            await app.state.container.ws_manager.shutdown()
            await app.state.container.shutdown()
            logger.info("shutdown")

    production = settings.app_env in ("staging", "production")
    app = FastAPI(
        title=settings.app_name,
        version=APP_VERSION,
        description=(
            "TaskPilot AI backend — Kamlesh Bhai planning, approval-gated browser automation, commerce and "
            "multi-domain integrations, with authentication, persistence and audit (Phase 6)."
        ),
        lifespan=lifespan,
        # API docs are not served in staging/production (smaller attack surface).
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.state.container = build_container(settings, provider=provider)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER, "X-CSRF-Token", "Authorization"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    install_auth_middleware(app)  # inner: runs after the request id / security headers middleware below

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if 0 < len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        request.state.request_id = request_id
        cid = correlation_id.set(str(uuid.UUID(request_id)) if len(request_id.replace("-", "")) == 32 else str(uuid.uuid4()))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            correlation_id.reset(cid)
        metrics = request.app.state.container.metrics
        metrics.http_requests.labels(method=request.method, status_class=f"{response.status_code // 100}xx").inc()
        metrics.http_duration.labels(method=request.method).observe(time.perf_counter() - started)
        response.headers[REQUEST_ID_HEADER] = request_id
        # Security headers for API responses (the reverse proxy adds HSTS in production).
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response

    _register_exception_handlers(app)
    app.include_router(api_router)
    app.include_router(ws_router)
    return app


app = create_app()
