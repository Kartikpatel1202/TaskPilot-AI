"""Health: legacy `/health`, liveness, readiness, details (OWNER or METRICS_TOKEN) and Prometheus `/metrics`."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.auth.context import current_user
from app.auth.policies import is_admin
from app.config import APP_VERSION, SERVICE_NAME
from app.observability.health import details, readiness
from app.schemas.common import HealthResponse, utc_now

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", service=SERVICE_NAME, version=APP_VERSION, timestamp=utc_now())


@router.get("/health/live", summary="Liveness: the API process is running")
async def live() -> dict[str, str]:
    return {"status": "alive", "version": APP_VERSION}


@router.get("/health/ready", summary="Readiness: database, Redis/queue and configuration")
async def ready(request: Request) -> JSONResponse:
    ok, checks = await readiness(request.app.state.container)
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not_ready", "checks": checks})


def _privileged(request: Request) -> bool:
    container = request.app.state.container
    token = container.settings.metrics_token
    header = request.headers.get("authorization", "")
    if token is not None and header.lower().startswith("bearer ") and hmac.compare_digest(header[7:].strip(), token.get_secret_value()):
        return True
    user = current_user.get()
    if user is not None:
        return is_admin(user.role)
    return not container.settings.auth_enforced  # development without authentication


@router.get("/health/details", summary="Detailed subsystem status (OWNER only)")
async def health_details(request: Request) -> JSONResponse:
    if not _privileged(request):
        return JSONResponse(status_code=403, content={"code": "FORBIDDEN", "message": "Administrators only."})
    return JSONResponse(content=await details(request.app.state.container))


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    container = request.app.state.container
    if not container.settings.metrics_enabled:
        return Response(status_code=404)
    if not _privileged(request):
        return Response(status_code=403)
    return Response(content=container.metrics.render(), media_type="text/plain; version=0.0.4")
