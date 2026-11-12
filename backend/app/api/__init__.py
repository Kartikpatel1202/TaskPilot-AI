"""HTTP + WebSocket routers (thin: validation and delegation only)."""

from fastapi import APIRouter

from app.dev.demo_events import router as demo_router

from app.dev.fixtures import commerce_router as commerce_fixtures_router
from app.dev.fixtures import integrations_router as integration_fixtures_router
from app.dev.fixtures import router as fixtures_router

from . import activity, agent, approvals, audit, auth, browser, commerce, execution, health, integrations, preferences, tasks, websocket

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(audit.router)
api_router.include_router(tasks.router)
api_router.include_router(tasks.history_router)
api_router.include_router(preferences.router)
api_router.include_router(activity.router)
api_router.include_router(approvals.router)
api_router.include_router(agent.router)
api_router.include_router(execution.router)
api_router.include_router(browser.router)
api_router.include_router(commerce.router)
api_router.include_router(integrations.router)
api_router.include_router(fixtures_router)
api_router.include_router(commerce_fixtures_router)
api_router.include_router(integration_fixtures_router)
api_router.include_router(demo_router)

ws_router = APIRouter(prefix="/api/v1")
ws_router.include_router(websocket.router)
ws_router.include_router(browser.stream_router)

__all__ = ["api_router", "ws_router"]
