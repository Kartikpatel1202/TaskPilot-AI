"""Capability registry, domain router, mock multi-domain classification and the Phase 5
settings guard rails (no fixtures outside dev/test, no Gmail send, no executables...)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.agent.providers.mock_scenarios import classify
from app.integrations.capability_registry import CapabilityError, CapabilityRegistry
from app.integrations.domain_router import route
from app.integrations.registry import IntegrationRegistry, fixture_binding
from app.schemas.integration import DomainType, GmailCreateDraftAction, YouTubePlayAction
from app.schemas.intent import IntentClassification

from ..conftest import make_settings, post_command, wait_for_task_state


def test_registry_reflects_settings() -> None:
    on = CapabilityRegistry(make_settings(integrations_enabled=True))
    assert on.require("gmail_create_draft").domain == DomainType.GMAIL
    assert on.require("calendar_create_event").requires_approval is True
    off = CapabilityRegistry(make_settings(integrations_enabled=True, gmail_enabled=False))
    with pytest.raises(CapabilityError) as exc:
        off.require("gmail_create_draft")
    assert exc.value.code == "CAPABILITY_DISABLED"
    with pytest.raises(CapabilityError) as exc:
        on.require("shell_exec")
    assert exc.value.code == "CAPABILITY_NOT_SUPPORTED"
    none = CapabilityRegistry(make_settings())  # integrations disabled in shared test settings
    assert not any(c.enabled for c in none.all() if c.domain in (DomainType.YOUTUBE, DomainType.GMAIL))


def test_site_bindings_are_exact_hosts_or_exact_fixtures() -> None:
    reg = IntegrationRegistry({DomainType.YOUTUBE, DomainType.GMAIL})
    assert reg.binding_for_website("youtube.com", DomainType.YOUTUBE).key == "youtube"  # type: ignore[union-attr]
    assert reg.binding_for_website("https://www.youtube.com/watch", DomainType.YOUTUBE).key == "youtube"  # type: ignore[union-attr]
    assert reg.binding_for_website("youtube.com.evil.example", DomainType.YOUTUBE).key == "youtube"  # type: ignore[union-attr]  # -> default real site, never the evil host
    assert reg.binding_for_website("mail.google.com", DomainType.YOUTUBE) is None  # domain mismatch
    assert reg.binding_for_website(None, DomainType.GOOGLE_CALENDAR) is None  # disabled domain
    fx = fixture_binding(DomainType.YOUTUBE, "http://127.0.0.1:9000")
    reg.register_fixture(fx)
    assert reg.binding_for_website("youtube.fixture.test", DomainType.YOUTUBE) == fx
    assert fx.owns("http://127.0.0.1:9000/api/v1/dev/fixtures/integrations/youtube/watch.html?v=x")
    assert not fx.owns("http://127.0.0.1:9000/api/v1/dev/fixtures/commerce/blinkit/index.html")


def test_mock_classifier_detects_multi_domain_requests_in_order() -> None:
    c = classify({"command": "Find a Python tutorial on YouTube and email the link to friend@example.com", "language": "en"})
    assert c["intent"] == "MULTI_DOMAIN_WORKFLOW"
    steps = c["entities"]["workflow"]
    assert [s["intent"] for s in steps] == ["YOUTUBE_SEARCH", "EMAIL_DRAFT"]
    assert steps[1]["recipient"] == "friend@example.com" and steps[1]["include_previous_output"] is True
    single = classify({"command": "Draft an email to hr@example.com about internship opportunities", "language": "en"})
    assert single["intent"] == "EMAIL_DRAFT"
    assert classify({"command": "Schedule a meeting tomorrow at 3pm and email the agenda to a@example.com"})["intent"] == "MULTI_DOMAIN_WORKFLOW"


def test_router_maps_intents_to_domain_steps() -> None:
    media = IntentClassification.model_validate({"intent": "MEDIA_SEARCH", "confidence": 0.9, "target_website": "youtube.com",
                                                  "entities": {"search_query": "lofi", "requested_actions": ["search", "play"]}})
    assert [s.intent for s in route(media)] == ["YOUTUBE_PLAYBACK"]
    spotify = media.model_copy(update={"target_website": "open.spotify.com"})
    assert route(spotify) == []
    chat = IntentClassification.model_validate({"intent": "GENERAL_CHAT", "confidence": 0.9})
    assert route(chat) == []


def test_action_schemas_reject_unsafe_values() -> None:
    with pytest.raises(ValidationError):
        YouTubePlayAction(type="youtube_play", video_reference="https://evil.example/watch?v=abcdefgh")
    with pytest.raises(ValidationError):
        GmailCreateDraftAction(type="gmail_create_draft", recipient_emails=["not-an-email"], subject="s", body="b")
    with pytest.raises(ValidationError):
        GmailCreateDraftAction(type="gmail_create_draft", recipient_emails=["a@example.com", "A@example.com"], subject="s", body="b")


@pytest.mark.parametrize("overrides", [
    {"app_env": "production", "integration_enable_fixtures": True},
    {"gmail_automated_send_enabled": True},
    {"gmail_attachment_enabled": True},
    {"calendar_require_creation_approval": False},
    {"calendar_allow_automatic_event_deletion": True},
    {"file_download_allow_executables": True},
    {"file_download_allow_archives": True},
    {"file_download_allowed_extensions": "pdf,exe"},
    {"calendar_default_timezone": "Mars/Olympus"},
    {"workflow_max_concurrency": 8, "execution_concurrency": 2},
])
def test_unsafe_settings_are_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_multi_domain_request_is_rejected_when_integrations_are_off(client) -> None:  # noqa: ANN001
    sid = str(uuid.uuid4())
    task_id = post_command(client, "Find a Python tutorial on YouTube and email the link to friend@example.com", sid)["task_id"]
    task = wait_for_task_state(client, task_id, timeout=10)
    plan = client.get(f"/api/v1/tasks/{task_id}/plan").json()
    assert task["state"] == "FAILED" and plan["status"] == "REJECTED" and "not enabled" in plan["user_facing_message"]
    assert client.get("/api/v1/integrations/status").status_code == 503
    assert all(not c["enabled"] for c in client.get("/api/v1/integrations/capabilities").json() if c["domain"] != "BLINKIT")


def test_fixture_routes_are_off_unless_enabled(client) -> None:  # noqa: ANN001
    assert client.get("/api/v1/dev/fixtures/integrations/gmail/index.html").status_code == 404
