from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from pydantic import BaseModel  # noqa: F401  (used by ScriptedProvider annotations)
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.config import Settings
from app.main import create_app


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "test",
        "enable_demo_endpoints": True,
        "demo_event_delay_ms": 0,
        "telemetry_history_limit": 100,
        "websocket_max_connections": 10,
        "log_level": "WARNING",
        "agent_mock_latency_ms": 0,
        "agent_retry_base_delay_seconds": 0,
        # Phase 1-3 regression tests exercise the generic planner for every site; Phase 4 commerce
        # tests opt in with commerce_settings() (commerce is enabled by default in real configs).
        "commerce_enabled": False,
        # Same for Phase 5 integrations (YouTube/Gmail/Calendar/downloads); integration tests opt in.
        "integrations_enabled": False,
        # Phase 6: every test app gets its own in-memory database; rate limits are exercised by the security tests
        # (the older tests poll endpoints far faster than a person would).
        "database_url": "sqlite+aiosqlite://",
        "rate_limit_enabled": False,
        "redis_url": "",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def production_overrides(**extra: Any) -> dict[str, Any]:
    """Phase 6: the minimum configuration production now accepts (no real secrets; nothing is contacted)."""
    base: dict[str, Any] = {
        "app_env": "production", "auth_required": True, "allow_dev_auth_bypass": False,
        "app_secret_key": "test-only-secret-key-0123456789-abcdefghij", "database_url": "postgresql+asyncpg://tp:tp@db:5432/taskpilot",
        "database_auto_create": False, "redis_url": "redis://redis:6379/0", "queue_backend": "redis", "session_cookie_secure": True,
        "csrf_protection_enabled": True, "enable_demo_endpoints": False, "require_egress_proxy": True,
        "egress_proxy_url": "http://egress:3128", "rate_limit_enabled": True,
    }
    base.update(extra)
    return base


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # The context manager keeps a single event loop alive for the whole test,
    # so HTTP requests and WebSocket handlers share asyncio primitives.
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def client_factory() -> Iterator[Callable[..., TestClient]]:
    opened: list[TestClient] = []

    def factory(**overrides: Any) -> TestClient:
        c = TestClient(create_app(make_settings(**overrides)))
        c.__enter__()
        opened.append(c)
        return c

    yield factory
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def session_id() -> str:
    return str(uuid.uuid4())


def receive_until(
    ws: WebSocketTestSession, predicate: Callable[[dict[str, Any]], bool], max_messages: int = 60
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read messages until `predicate` matches. Returns (match, everything_seen)."""
    seen: list[dict[str, Any]] = []
    for _ in range(max_messages):
        message = ws.receive_json()
        seen.append(message)
        if predicate(message):
            return message, seen
    raise AssertionError(f"Expected message not received. Saw: {[m.get('type') for m in seen]}")


def of_type(event_type: str) -> Callable[[dict[str, Any]], bool]:
    return lambda m: m.get("type") == event_type


def wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


# ---------------------------------------------------------------------- Phase 2 helpers

TERMINAL_PLANNING_STATES = ("PLANNED", "NEEDS_CLARIFICATION", "FAILED")


def wait_for_task_state(client: TestClient, task_id: str, states: tuple[str, ...] = TERMINAL_PLANNING_STATES, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    task: dict[str, Any] = {}
    while time.monotonic() < deadline:
        task = client.get(f"/api/v1/tasks/{task_id}").json()
        if task.get("state") in states:
            return task
        time.sleep(0.01)
    raise AssertionError(f"Task {task_id} stuck in {task.get('state')}")


def post_command(client: TestClient, command: str, session_id: str, mode: str = "TEXT") -> dict[str, Any]:
    response = client.post("/api/v1/tasks", json={"command": command, "session_id": session_id, "input_mode": mode})
    assert response.status_code == 202, response.text
    return response.json()


def plan_for(client: TestClient, command: str, session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Submit a command, wait for planning to settle, return (task, plan_response_json)."""
    task_id = post_command(client, command, session_id)["task_id"]
    task = wait_for_task_state(client, task_id)
    return task, client.get(f"/api/v1/tasks/{task_id}/plan").json()


class ScriptedProvider:
    """Fake LLMProvider: returns scripted outputs or raises scripted errors, per schema name."""

    name = "fake"
    model = "fake-model-1"

    def __init__(self, script: dict[str, list[Any]] | None = None, *, delay: float = 0.0) -> None:
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[str] = []
        self.delay = delay
        self.closed = False

    async def generate_structured_output(self, system_prompt, user_prompt, response_schema, max_tokens, timeout):  # type: ignore[no-untyped-def]
        import asyncio

        from app.agent.providers.base import LLMResult, validate_output

        self.calls.append(response_schema.__name__)
        if self.delay:
            await asyncio.sleep(self.delay)
        queue = self.script.get(response_schema.__name__) or []
        item = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else None)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(user_prompt)
        if item is None:
            raise AssertionError(f"No scripted output for {response_schema.__name__}")
        return LLMResult(parsed_output=validate_output(item, response_schema), provider=self.name, model=self.model, latency_ms=1)

    async def health_check(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def provider_client() -> Iterator[Callable[..., TestClient]]:
    opened: list[TestClient] = []

    def factory(provider: Any, **overrides: Any) -> TestClient:
        c = TestClient(create_app(make_settings(**overrides), provider=provider))
        c.__enter__()
        opened.append(c)
        return c

    yield factory
    for c in opened:
        c.__exit__(None, None, None)


# ---------------------------------------------------------------------- Phase 3: browser fixture site

import http.server
import threading
from pathlib import Path

FIXTURE_SITE = Path(__file__).resolve().parent / "fixtures" / "browser_site"
FIXTURE_PREFIX = "/api/v1/dev/fixtures/shop/"
COMMERCE_PREFIX = "/api/v1/dev/fixtures/commerce/"
INTEGRATIONS_PREFIX = "/api/v1/dev/fixtures/integrations/"
OVERSIZED_BYTES = 26 * 1024 * 1024


class _FixtureHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the fixture site at the same paths as the dev route (and the same redirect tests)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(FIXTURE_SITE.parent), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path.startswith(FIXTURE_PREFIX + "redirect/"):
            target = path.rsplit("/", 1)[-1]
            location = {"index": FIXTURE_PREFIX + "index.html", "outside": "http://10.0.0.1/admin", "script": FIXTURE_PREFIX + "shop.js"}.get(target)
            self.send_response(302 if location else 404)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            return
        if path.startswith(INTEGRATIONS_PREFIX + "files/redirect/"):
            target = path.rsplit("/", 1)[-1]
            location = {"inside": INTEGRATIONS_PREFIX + "files/report.pdf", "outside": "http://10.0.0.1/report.pdf"}.get(target)
            self.send_response(302 if location else 404)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            return
        if path == INTEGRATIONS_PREFIX + "files/oversized_file.pdf":
            # Streamed (never stored in the repo): larger than the 25 MB default download cap.
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(OVERSIZED_BYTES))
            self.end_headers()
            try:
                self.wfile.write(b"%PDF-1.4\n")
                block = b"0" * 65536
                sent = 9
                while sent < OVERSIZED_BYTES:
                    chunk = block[: min(len(block), OVERSIZED_BYTES - sent)]
                    self.wfile.write(chunk)
                    sent += len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        if path.startswith(INTEGRATIONS_PREFIX):
            self.path = "/integrations/" + self.path[len(INTEGRATIONS_PREFIX):]
        elif path.startswith(COMMERCE_PREFIX):
            self.path = "/commerce/" + self.path[len(COMMERCE_PREFIX):]
        elif path.startswith(FIXTURE_PREFIX):
            self.path = "/browser_site/" + self.path[len(FIXTURE_PREFIX):]
        else:
            self.send_error(404)
            return
        super().do_GET()

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope="session")
def fixture_origin() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def browser_settings(origin: str, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "browser_test_allowed_origins": origin,
        "browser_dev_fixtures_enabled": True,
        "browser_action_timeout_ms": 5_000,
        "browser_navigation_timeout_ms": 10_000,
        "execution_approval_ttl_seconds": 10,
    }
    base.update(overrides)
    return make_settings(**base)


def wait_for_execution(client: TestClient, task_id: str, timeout: float = 45.0) -> dict[str, Any]:
    return wait_for_task_state(client, task_id, ("COMPLETED", "FAILED", "CANCELLED"), timeout=timeout)
