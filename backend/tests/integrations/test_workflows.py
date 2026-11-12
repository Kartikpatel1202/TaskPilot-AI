"""Multi-domain workflows end to end (LOCAL fixtures): typed result handoff, partial success,
dependency skipping, session isolation and the Phase 4 commerce regression with integrations on."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

from ..commerce.conftest import commerce_settings
from .conftest import (
    PREFIX,
    browser_eval,
    events_of,
    finished,
    integration_settings,
    planned,
    prime,
    results,
    run,
    workflow,
)

DRAFTS = "() => JSON.parse(localStorage.getItem('fx_gmail_drafts') || '[]')"
SEND_CLICKS = "() => Number(localStorage.getItem('fx_gmail_sent_clicks') || '0')"


def test_scenario5_youtube_then_gmail_with_the_video_link(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "gmail", "index.html?reset=1")
    task_id, plan = planned(iclient, "Find a Python tutorial for beginners on fixture youtube and email the link to friend@example.com on fixture gmail", sid)
    assert plan["intent"] == "MULTI_DOMAIN_WORKFLOW"
    search, draft = plan["steps"]
    assert search["action"]["type"] == "youtube_search" and search["action"]["select"] is True
    assert draft["action"]["insert_outputs"] == ["youtube.video_reference"] and draft["depends_on"] == [search["step_id"]]
    assert "{{youtube.video_url}}" in draft["action"]["body"]
    planned_wf = workflow(iclient, task_id, sid)
    assert planned_wf["status"] == "PLANNED" and [s["domain"] for s in planned_wf["steps"]] == ["YOUTUBE", "GMAIL"]
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "COMPLETED", [(r["error_code"], r["message"]) for r in results(iclient, task_id)]
    wf = workflow(iclient, task_id, sid)
    assert wf["status"] == "COMPLETED" and all(s["status"] == "COMPLETED" for s in wf["steps"])
    video = next(o for o in wf["outputs"] if o["type"] == "youtube.video_reference")["data"]
    saved = browser_eval(iclient, sid, DRAFTS)[-1]
    assert video["video_url"] in saved["body"] and video["title"] in saved["body"] and "{{" not in saved["body"]
    assert saved["to"] == ["friend@example.com"] and browser_eval(iclient, sid, SEND_CLICKS) == 0
    kinds = [e["type"] for e in events_of(iclient, sid, "workflow.")]
    assert kinds.count("workflow.step_started") == 2 and kinds.count("workflow.step_completed") == 2 and kinds[-1] == "workflow.completed"


def test_scenario6_download_then_gmail_mentions_the_file(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "gmail", "index.html?reset=1")
    url = f"{fixture_origin}{PREFIX}/files/report.pdf"
    task_id, plan = planned(iclient, f"Download the report from {url} and draft an email to hr@example.com about it on fixture gmail", sid)
    assert [s["action"]["type"] for s in plan["steps"]] == ["file_download", "gmail_create_draft"]
    assert plan["steps"][1]["action"]["insert_outputs"] == ["file.reference"]
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "COMPLETED", [(r["error_code"], r["message"]) for r in results(iclient, task_id)]
    saved = browser_eval(iclient, sid, DRAFTS)[-1]
    assert "report.pdf" in saved["body"] and saved["subject"] == "File: report.pdf"
    files = iclient.get("/api/v1/files", params={"session_id": sid}).json()
    assert [f["original_name"] for f in files] == ["report.pdf"]  # downloaded, NOT attached (attachments are disabled)


def test_partial_success_and_dependency_skipping(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "gmail", "index.html?reset=1")
    bad = f"{fixture_origin}{PREFIX}/files/fake_executable.bin"
    # (a) the email needs the file -> it is skipped, nothing is drafted
    task_id, _ = planned(iclient, f"Download the installer from {bad} and draft an email to hr@example.com about it on fixture gmail", sid)
    run(iclient, task_id, sid)
    finished(iclient, task_id)
    wf = workflow(iclient, task_id, sid)
    assert [s["status"] for s in wf["steps"]] == ["BLOCKED", "SKIPPED"] and wf["status"] == "FAILED"
    assert [r["status"] for r in results(iclient, task_id)] == ["BLOCKED", "SKIPPED"]
    assert browser_eval(iclient, sid, DRAFTS) == []
    # (b) an independent email still runs -> PARTIAL, reported honestly
    task_id, _ = planned(iclient, f"Download the installer from {bad} and draft an email to hr@example.com about my leave on fixture gmail", sid)
    run(iclient, task_id, sid)
    task = finished(iclient, task_id)
    assert task["state"] == "FAILED"
    wf = workflow(iclient, task_id, sid)
    assert [s["status"] for s in wf["steps"]] == ["BLOCKED", "COMPLETED"] and wf["status"] == "PARTIAL"
    assert "1 of 2 step(s) finished" in wf["final_result"]
    summary = iclient.get(f"/api/v1/tasks/{task_id}/execution").json()
    assert summary["message"].startswith("Partial result:")
    assert [e for e in events_of(iclient, sid, "workflow.partial_success")]


def test_scenario7_sessions_are_isolated(iclient: TestClient, fixture_origin: str) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    url = f"{fixture_origin}{PREFIX}/files/sample.txt"
    ta, _ = planned(iclient, f"Download the notes from {url}", a)
    tb, _ = planned(iclient, f"Download the notes from {url}", b)
    run(iclient, ta, a)
    run(iclient, tb, b)
    assert finished(iclient, ta)["state"] == "COMPLETED" and finished(iclient, tb)["state"] == "COMPLETED"
    fa = iclient.get("/api/v1/files", params={"session_id": a}).json()
    fb = iclient.get("/api/v1/files", params={"session_id": b}).json()
    assert len(fa) == 1 and len(fb) == 1 and fa[0]["file_id"] != fb[0]["file_id"]
    assert iclient.get(f"/api/v1/files/{fa[0]['file_id']}", params={"session_id": b}).status_code == 403
    assert iclient.get(f"/api/v1/tasks/{ta}/workflow", params={"session_id": b}).status_code == 403
    assert iclient.get(f"/api/v1/tasks/{ta}/gmail/draft", params={"session_id": b}).status_code in (403, 404)
    assert not events_of(iclient, b, "file.") or all(e["task_id"] == tb for e in events_of(iclient, b, "file."))


def test_scenario8_commerce_still_works_with_integrations_enabled(fixture_origin: str, tmp_path: Path) -> None:
    settings = commerce_settings(fixture_origin, **{k: v for k, v in integration_settings(fixture_origin, tmp_path / "dl").model_dump().items()
                                                     if k in ("integrations_enabled", "integration_enable_fixtures", "file_download_storage")})
    with TestClient(create_app(settings)) as client:
        sid = str(uuid.uuid4())
        from ..commerce.conftest import prime as cprime

        cprime(client, sid, fixture_origin, "blinkit", "index.html?reset=1")
        task_id, plan = planned(client, "Add 2 litres of Amul Taaza milk on fixture blinkit", sid)
        assert {s["action"]["type"] for s in plan["steps"]} == {"commerce"}
        run(client, task_id, sid)
        assert finished(client, task_id)["state"] == "COMPLETED"
        assert client.get(f"/api/v1/tasks/{task_id}/workflow", params={"session_id": sid}).status_code == 404  # no integration workflow
        # and an integration request in the same app still plans as an integration
        _, yt = planned(client, "Search lofi beats on fixture youtube", sid)
        assert yt["steps"][0]["action"]["type"] == "youtube_search"
