"""Liveness, readiness and detailed health. Details need an OWNER (or METRICS_TOKEN) and never expose
secrets, connection strings or internal addresses."""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import APP_VERSION


async def _redis_ok(redis: Any) -> bool | None:
    if redis is None:
        return None
    try:
        async with asyncio.timeout(2):
            return bool(await redis.ping())
    except Exception:  # noqa: BLE001
        return False


async def readiness(container: Any) -> tuple[bool, dict[str, Any]]:
    db_ok = await container.db.ping()
    redis_ok = await _redis_ok(container.redis)
    checks: dict[str, Any] = {
        "database": "ok" if db_ok else "unavailable",
        "redis": "not_configured" if redis_ok is None else ("ok" if redis_ok else "unavailable"),
        "planner_queue": "ok" if container.planning.queue.is_running or not container.planning.enabled else "stopped",
        "configuration": "ok",
        # Browser availability is reported, but does not make the API unready (execution may be disabled on purpose).
        "browser": "available" if container.execution.available else "unavailable",
    }
    ready = db_ok and redis_ok is not False and checks["planner_queue"] == "ok"
    if container.settings.queue_backend == "redis" and redis_ok is not True:
        ready = False
    return ready, checks


async def details(container: Any) -> dict[str, Any]:
    ready, checks = await readiness(container)
    s = container.settings
    return {
        "version": APP_VERSION,
        "environment": s.app_env,
        "ready": ready,
        "checks": checks,
        "auth_enforced": s.auth_enforced,
        "queue_backend": s.queue_backend,
        "egress_proxy_configured": bool(s.egress_proxy_url),
        "llm": {"provider": container.provider.name, "model": container.provider.model,
                "circuit": container.breakers["llm"].snapshot()},
        "circuits": {name: b.snapshot() for name, b in container.breakers.items()},
        "browser_sessions": len(container.browser.sessions_snapshot()) if hasattr(container.browser, "sessions_snapshot") else None,
        "approvals_pending": container.approvals.pending_count(),
        "persistence_write_failures": container.persistence.write_failures,
        "audit_write_failures": container.audit.failures,
        "rate_limiter_degraded": container.rate_limiter.degraded,
    }
