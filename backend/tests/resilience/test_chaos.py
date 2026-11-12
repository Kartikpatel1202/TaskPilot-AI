"""Chaos tests: dependency outages and invalid configuration produce clear statuses — no silent data
loss, no false completion, no secret leakage, no mock fallback."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.providers.base import ProviderTimeoutError
from app.database.session import DatabaseUnavailableError
from app.main import create_app

from ..conftest import ScriptedProvider, make_settings, post_command, wait_for_task_state


def test_postgres_outage_refuses_new_tasks_with_503_and_keeps_nothing_half_created(client: TestClient) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]

    async def down(*a: object, **k: object) -> None:
        raise DatabaseUnavailableError("down")

    original = container.persistence.tasks.upsert
    container.persistence.tasks.upsert = down
    try:
        r = client.post("/api/v1/tasks", json={"command": "hello", "session_id": str(uuid4()), "input_mode": "TEXT"})
    finally:
        container.persistence.tasks.upsert = original
    assert r.status_code == 503 and r.json()["code"] == "DATABASE_UNAVAILABLE" and "Retry-After" in r.headers
    assert container.tasks.list_tasks(uuid4()) == []


def test_best_effort_write_failures_are_counted_not_fatal(client: TestClient) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    original = container.persistence.plans.save

    async def broken(*a: object, **k: object) -> None:
        raise OSError("disk full")

    container.persistence.plans.save = broken
    try:
        task_id = post_command(client, "hello there", str(uuid4()))["task_id"]
        assert wait_for_task_state(client, task_id)["state"] in ("PLANNED", "FAILED")
    finally:
        container.persistence.plans.save = original
    assert container.persistence.write_failures >= 1
    details = client.get("/api/v1/health/details").json()
    assert details["persistence_write_failures"] >= 1


def test_redis_outage_makes_a_redis_backed_api_unready(fixture_origin: str) -> None:
    settings = make_settings(redis_url="redis://127.0.0.1:1/0", queue_backend="inprocess")
    with TestClient(create_app(settings)) as c:
        ready = c.get("/api/v1/health/ready")
        assert ready.status_code == 503 and ready.json()["checks"]["redis"] == "unavailable"
        assert c.get("/api/v1/health/live").status_code == 200


def test_llm_timeouts_open_the_circuit_and_never_fall_back_to_the_mock(provider_client) -> None:  # noqa: ANN001
    provider = ScriptedProvider({"IntentClassification": [ProviderTimeoutError(detail="slow"), ProviderTimeoutError(detail="slow")]})
    client = provider_client(provider, agent_max_retries=0, circuit_breaker_failure_threshold=2)
    states = []
    for _ in range(3):
        task_id = post_command(client, "open youtube", str(uuid4()))["task_id"]
        states.append(wait_for_task_state(client, task_id)["state"])
    assert states == ["FAILED", "FAILED", "FAILED"]
    container = client.app.state.container  # type: ignore[attr-defined]
    assert container.breakers["llm"].state.value == "OPEN"
    assert provider.calls.count("IntentClassification") == 2  # third call failed fast; the mock was never used
    assert container.provider.name == "fake"


def test_invalid_configuration_is_refused_at_startup() -> None:
    with pytest.raises(ValidationError):
        make_settings(queue_backend="redis", redis_url="")
    with pytest.raises(ValidationError):
        make_settings(auth_required=True, app_secret_key=None)
    with pytest.raises(ValidationError):
        make_settings(app_secret_key="too-short")
