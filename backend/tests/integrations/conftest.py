"""Phase 5 integration test helpers: real Chromium + LOCAL YouTube-/Gmail-/Calendar-like fixture
sites and local download test files. Nothing here contacts youtube.com, google.com or any real
mail/calendar account — fixture pages are clearly labelled fakes.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from ..conftest import browser_settings, post_command, wait_for_task_state

PREFIX = "/api/v1/dev/fixtures/integrations"


def integration_settings(origin: str, storage: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "integrations_enabled": True, "integration_enable_fixtures": True, "file_download_storage": str(storage),
        "youtube_search_timeout_seconds": 8, "telemetry_history_limit": 1000, "youtube_playback_timeout_seconds": 10,
    }
    base.update(overrides)
    return browser_settings(origin, **base)


@pytest.fixture
def iclient(fixture_origin: str, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(integration_settings(fixture_origin, tmp_path / "downloads"))) as c:
        yield c


def container(client: TestClient) -> Any:
    return client.app.state.container  # type: ignore[attr-defined]


def planned(client: TestClient, command: str, session_id: str) -> tuple[str, dict[str, Any]]:
    task_id = post_command(client, command, session_id)["task_id"]
    task = wait_for_task_state(client, task_id, timeout=10)
    assert task["state"] == "PLANNED", task
    return task_id, client.get(f"/api/v1/tasks/{task_id}/plan").json()


def run(client: TestClient, task_id: str, session_id: str) -> None:
    r = client.post(f"/api/v1/tasks/{task_id}/execute", json={"session_id": session_id, "confirm_execution": True})
    assert r.status_code == 202, r.text


def wait_until(predicate: Any, timeout: float = 60.0, interval: float = 0.1) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("Condition not met in time")


def finished(client: TestClient, task_id: str, timeout: float = 90) -> dict[str, Any]:
    return wait_for_task_state(client, task_id, ("COMPLETED", "FAILED", "CANCELLED"), timeout=timeout)


def workflow(client: TestClient, task_id: str, session_id: str) -> dict[str, Any]:
    return client.get(f"/api/v1/tasks/{task_id}/workflow", params={"session_id": session_id}).json()


def results(client: TestClient, task_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/tasks/{task_id}/execution").json()["results"]


def pending_calendar_approval(client: TestClient, task_id: str, timeout: float = 60) -> Any:
    approvals = container(client).approvals

    def find() -> Any:
        return next((a for a in list(approvals._approvals.values())
                     if str(a.task_id) == task_id and a.status.value == "PENDING" and a.calendar is not None), None)

    return wait_until(find, timeout)


def browser_eval(client: TestClient, session_id: str, script: str) -> Any:
    async def go() -> Any:
        session = container(client).browser.peek_session(UUID(session_id))
        return await session.page.evaluate(script)

    return client.portal.call(go)  # type: ignore[union-attr]


def prime(client: TestClient, session_id: str, origin: str, site: str, page: str) -> None:
    """Open a fixture page (with control parameters such as reset=1) in this session's browser before a run."""

    async def go() -> None:
        browser = container(client).browser
        await browser.get_or_create_session(UUID(session_id))
        session = browser.peek_session(UUID(session_id))
        await session.page.goto(f"{origin}{PREFIX}/{site}/{page}")

    client.portal.call(go)  # type: ignore[union-attr]


def events_of(client: TestClient, session_id: str, prefix: str) -> list[dict[str, Any]]:
    history = container(client).ws_manager._history.get(UUID(session_id))
    events = list(history.events) if history is not None else []
    return [e.model_dump(mode="json") for e in events if e.type.value.startswith(prefix)]
