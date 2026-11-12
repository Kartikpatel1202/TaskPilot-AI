"""Website security checks (Cloudflare "Just a moment…", CAPTCHA) are reported honestly, never bypassed.

TaskPilot waits a bounded time (a check may finish by itself, or the user completes it in the visible window)
and otherwise stops with CAPTCHA_REQUIRED — it never treats the interstitial as the real site."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from ..conftest import browser_settings, wait_for_execution
from .conftest import execute, install_plan, nav, planned_task, results, telemetry_types


@pytest.fixture
def quick_client(fixture_origin: str) -> Iterator[TestClient]:
    with TestClient(create_app(browser_settings(fixture_origin, browser_human_check_wait_seconds=3))) as c:
        yield c


def test_security_check_that_never_clears_blocks_with_captcha_required(quick_client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(quick_client, sid)
    install_plan(quick_client, task_id, [nav(fixture_origin, "challenge.html")])
    execute(quick_client, task_id, sid)
    # CAPTCHA_REQUIRED stops the run as "needs you" (CANCELLED), like sign-in walls — never as success.
    assert wait_for_execution(quick_client, task_id, timeout=60)["state"] == "CANCELLED"
    step = results(quick_client, task_id)[0]
    assert step["status"] == "BLOCKED" and step["error_code"] == "CAPTCHA_REQUIRED"
    assert "never bypasses" in step["message"]
    assert "browser.authentication_required" in telemetry_types(quick_client, sid)  # the user is told what to do


def test_security_check_that_clears_by_itself_continues(quick_client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(quick_client, sid)
    install_plan(quick_client, task_id, [nav(fixture_origin, "challenge.html?clear=800")])
    execute(quick_client, task_id, sid)
    assert wait_for_execution(quick_client, task_id, timeout=60)["state"] == "COMPLETED", results(quick_client, task_id)
    assert "Fixture Shop Home" in results(quick_client, task_id)[0]["message"]
