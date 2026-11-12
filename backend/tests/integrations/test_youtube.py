"""YouTube integration on the LOCAL YouTube-like fixture (real Chromium; never youtube.com)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.integrations.policies import IntegrationPolicy, Purpose
from app.integrations.youtube.ranking import choose, relevance
from app.schemas.youtube import YouTubeVideo

from .conftest import container, events_of, finished, planned, results, run, wait_until, workflow


def _video(n: int, title: str, rel: float) -> YouTubeVideo:
    return YouTubeVideo(option_id=f"v{n}", video_id=f"vid{n:06d}", title=title, video_url=f"https://www.youtube.com/watch?v=vid{n:06d}",
                        relevance=rel, observed_at=datetime.now(timezone.utc))


# ---------------------------------------------------------------------- unit: ranking and policy


def test_relevance_uses_meaningful_query_words() -> None:
    assert relevance("python tutorial", "Python Tutorial for Beginners") == 1.0
    assert relevance("python tutorial", "Learn Python in 1 Hour") == 0.5
    assert relevance("arijit singh songs", "Arijit Singh Live Concert", preferred_channel=None) == pytest.approx(2 / 3, abs=0.01)


def test_choose_auto_selects_only_a_clear_winner() -> None:
    best, options = choose([_video(1, "a", 1.0), _video(2, "b", 0.5)])
    assert best is not None and best.option_id == "v1" and options == []
    best, options = choose([_video(1, "a", 1.0), _video(2, "b", 0.95), _video(3, "c", 0.2)])
    assert best is None and [o.option_id for o in options] == ["v1", "v2", "v3"]


def test_youtube_policy_allows_only_play() -> None:
    policy = IntegrationPolicy()
    assert policy.check_click(Purpose.YOUTUBE_PLAY, "Play (k)").allowed
    for label in ("Subscribe", "Join", "Download", "Sign in", "Buy or rent"):
        assert not policy.check_click(Purpose.YOUTUBE_PLAY, label).allowed


# ---------------------------------------------------------------------- E2E scenario 1


def test_scenario1_youtube_search_select_and_verified_playback(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id, plan = planned(iclient, "Play Python tutorial for beginners on fixture youtube", sid)
    types = [s["action"]["type"] for s in plan["steps"]]
    assert types == ["youtube_search", "youtube_play"]
    assert plan["steps"][0]["action"]["select"] is True
    assert "LOCAL TEST FIXTURE" in " ".join(plan["assumptions"])
    run(iclient, task_id, sid)
    task = finished(iclient, task_id)
    assert task["state"] == "COMPLETED", [(r["error_code"], r["message"]) for r in results(iclient, task_id)]
    data = iclient.get(f"/api/v1/tasks/{task_id}/youtube/results", params={"session_id": sid}).json()
    assert data["results"] and data["selected"]["title"] == "Python Tutorial for Beginners - Full Course"
    assert data["playback"]["state"] == "PLAYING"
    assert data["playback"]["current_time"] > 0
    wf = workflow(iclient, task_id, sid)
    assert wf["status"] == "COMPLETED"
    kinds = {e["type"] for e in events_of(iclient, sid, "youtube.")}
    assert {"youtube.search_started", "youtube.search_completed", "youtube.results_found", "youtube.video_selected",
            "youtube.playback_started"} <= kinds


def test_ambiguous_results_ask_the_user_to_choose(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id, _ = planned(iclient, "Play python on fixture youtube", sid)
    run(iclient, task_id, sid)
    choice = wait_until(lambda: workflow(iclient, task_id, sid).get("pending_choice"), 60)
    assert len(choice["options"]) >= 2
    advanced = next(o for o in choice["options"] if "Decorators" in o["label"])
    r = iclient.post(f"/api/v1/tasks/{task_id}/workflow/choice", json={"session_id": sid, "choice_id": choice["choice_id"],
                                                                        "option_id": advanced["option_id"]})
    assert r.status_code == 202, r.text
    assert finished(iclient, task_id)["state"] == "COMPLETED"
    data = iclient.get(f"/api/v1/tasks/{task_id}/youtube/results", params={"session_id": sid}).json()
    assert data["selected"]["title"] == "Advanced Python Decorators Explained"


def test_other_session_cannot_answer_a_choice(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id, _ = planned(iclient, "Play python on fixture youtube", sid)
    run(iclient, task_id, sid)
    choice = wait_until(lambda: workflow(iclient, task_id, sid).get("pending_choice"), 60)
    other = iclient.post(f"/api/v1/tasks/{task_id}/workflow/choice", json={"session_id": str(uuid.uuid4()), "choice_id": choice["choice_id"],
                                                                            "option_id": "v1"})
    assert other.status_code == 403
    skip = iclient.post(f"/api/v1/tasks/{task_id}/workflow/choice", json={"session_id": sid, "choice_id": choice["choice_id"], "option_id": None})
    assert skip.status_code == 202
    task = finished(iclient, task_id)
    assert task["state"] == "CANCELLED"  # the user skipped: nothing played, nothing claimed


def test_blocked_video_is_reported_not_claimed(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id, _ = planned(iclient, "Play python region locked lecture on fixture youtube", sid)
    run(iclient, task_id, sid)
    task = finished(iclient, task_id)
    assert task["state"] == "FAILED"
    data = iclient.get(f"/api/v1/tasks/{task_id}/youtube/results", params={"session_id": sid}).json()
    assert data["playback"]["state"] == "PLAYBACK_BLOCKED"
    assert any(r["error_code"] == "YOUTUBE_PLAYBACK_BLOCKED" for r in results(iclient, task_id))


def test_search_only_lists_results_without_playing(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id, plan = planned(iclient, "Search arijit singh songs on fixture youtube", sid)
    assert [s["action"]["type"] for s in plan["steps"]] == ["youtube_search"]
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "COMPLETED"
    data = iclient.get(f"/api/v1/tasks/{task_id}/youtube/results", params={"session_id": sid}).json()
    assert len(data["results"]) == 2 and data["playback"] is None


def test_youtube_download_requests_are_refused(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    from ..conftest import post_command, wait_for_task_state

    task_id = post_command(iclient, "download this video https://www.youtube.com/watch?v=abcdefgh123", sid)["task_id"]
    task = wait_for_task_state(iclient, task_id, timeout=10)
    plan = iclient.get(f"/api/v1/tasks/{task_id}/plan").json()
    assert task["state"] == "FAILED" and plan["status"] == "REJECTED" and not plan["steps"]


def test_capabilities_and_status_endpoints(iclient: TestClient) -> None:
    caps = iclient.get("/api/v1/integrations/capabilities").json()
    names = {c["capability"]: c for c in caps}
    assert names["CALENDAR_CREATE_EVENT"]["requires_approval"] is True
    assert names["GMAIL_CREATE_DRAFT"]["enabled"] is True
    statuses = iclient.get("/api/v1/integrations/status", params={"session_id": str(uuid.uuid4())}).json()
    assert {s["domain"]: s["status"] for s in statuses} == {
        "YOUTUBE": "AVAILABLE", "GMAIL": "AVAILABLE", "GOOGLE_CALENDAR": "AVAILABLE", "FILES": "AVAILABLE"}
    assert container(iclient).integrations is not None
