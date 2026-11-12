"""Provider layer: mock determinism, factory/config validation, SDK error translation (mocked SDKs)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from app.agent.prompts import build_user_prompt
from app.agent.providers import MockLLMProvider, create_provider
from app.agent.providers.anthropic_provider import AnthropicProvider
from app.agent.providers.base import (
    InvalidModelOutputError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    strict_json_schema,
)
from app.agent.providers.openai_provider import OpenAIProvider
from app.schemas.intent import IntentClassification
from app.schemas.plan import PlanDraft

from .conftest import make_settings, production_overrides

FAKE_KEY = "sk-test-not-a-real-key-000000000000"
VALID_INTENT = {
    "intent": "MEDIA_SEARCH", "confidence": 0.9, "language": "en", "target_website": "youtube.com",
    "entities": {"products": [], "search_query": "python", "recipient": None, "subject": None, "message_topic": None,
                 "datetime_text": None, "url": None, "requested_actions": ["search"]},
    "missing_information": [], "requires_clarification": False, "clarification_question": None, "is_follow_up": False,
}


def _req() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.example.test/v1")


def _resp(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=_req())


# ---------------------------------------------------------------------- mock provider


async def test_mock_provider_returns_valid_structured_output() -> None:
    provider = MockLLMProvider()
    prompt = build_user_prompt({"task": "classify_intent", "command": "Open YouTube and search for Python", "language": "en"})
    result = await provider.generate_structured_output("sys", prompt, IntentClassification, 1000, 5)
    parsed = IntentClassification.model_validate(result.parsed_output)
    assert parsed.intent.value == "MEDIA_SEARCH"
    assert result.provider == "mock" and result.model == "taskpilot-mock-v1"


async def test_mock_provider_is_scenario_specific_not_generic() -> None:
    provider = MockLLMProvider()
    intents = set()
    for command in ("Open YouTube and search for Python", "Blinkit par 2 litre Amul milk add karo", "Draft an email to a@b.com about leave"):
        prompt = build_user_prompt({"task": "classify_intent", "command": command, "language": "en"})
        intents.add((await provider.generate_structured_output("s", prompt, IntentClassification, 100, 5)).parsed_output["intent"])
    assert intents == {"MEDIA_SEARCH", "ECOMMERCE_SHOPPING", "EMAIL_DRAFT"}


async def test_mock_plans_are_labelled_mock() -> None:
    provider = MockLLMProvider()
    prompt = build_user_prompt({"task": "build_plan", "language": "en", "intent": {**VALID_INTENT}})
    result = await provider.generate_structured_output("s", prompt, PlanDraft, 100, 5)
    assert any("mock" in a.lower() for a in result.parsed_output["assumptions"])


# ---------------------------------------------------------------------- factory / config


def test_factory_selects_mock_by_default() -> None:
    provider = create_provider(make_settings())
    assert isinstance(provider, MockLLMProvider)


def test_factory_builds_real_providers_when_configured() -> None:
    openai_p = create_provider(make_settings(agent_provider="openai", openai_api_key=FAKE_KEY))
    assert isinstance(openai_p, OpenAIProvider) and openai_p.model == "gpt-4o"
    anthropic_p = create_provider(make_settings(agent_provider="anthropic", anthropic_api_key=FAKE_KEY))
    assert isinstance(anthropic_p, AnthropicProvider) and anthropic_p.model == "claude-opus-5-5"


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_missing_api_key_is_a_clear_error(provider: str) -> None:
    with pytest.raises(ValidationError, match=f"AGENT_PROVIDER={provider} requires"):
        make_settings(agent_provider=provider)
    with pytest.raises(ValidationError):
        make_settings(agent_provider=provider, openai_api_key="   ", anthropic_api_key="")


def test_mock_model_name_cannot_be_used_with_real_provider() -> None:
    with pytest.raises(ValidationError, match="Clear AGENT_MODEL"):
        make_settings(agent_provider="openai", openai_api_key=FAKE_KEY, agent_model="taskpilot-mock-v1")


def test_production_refuses_silent_mock() -> None:
    with pytest.raises(ValidationError, match="not allowed in production"):
        make_settings(**production_overrides())
    # Phase 6: production also needs auth, PostgreSQL, Redis, TLS cookies and the egress proxy (see production_overrides).
    assert make_settings(**production_overrides(agent_allow_mock_in_production=True)).agent_provider == "mock"


def test_browser_execution_is_a_separate_switch_from_planning() -> None:
    # Phase 3: execution is enabled by default but stays an independent switch; planning never needs it.
    assert make_settings().agent_browser_execution_enabled is True
    planning_only = make_settings(agent_browser_execution_enabled=False)
    assert planning_only.agent_planning_enabled is True and planning_only.agent_browser_execution_enabled is False
    # Local fixture origins can never be configured outside development/test.
    with pytest.raises(ValidationError, match="BROWSER_TEST_ALLOWED_ORIGINS"):
        make_settings(app_env="production", agent_allow_mock_in_production=True,
                      browser_test_allowed_origins="http://127.0.0.1:9000")


def test_secrets_are_not_exposed_in_settings_repr() -> None:
    settings = make_settings(agent_provider="openai", openai_api_key=FAKE_KEY)
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in str(settings.model_dump())


def test_strict_schema_is_closed_and_fully_required() -> None:
    schema = strict_json_schema(PlanDraft)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "default" not in node and "discriminator" not in node and "const" not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


# ---------------------------------------------------------------------- OpenAI (mocked SDK)


class FakeOpenAIClient:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.kwargs: dict[str, Any] = {}

        async def create(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            if isinstance(self.outcome, BaseException):
                raise self.outcome
            return self.outcome

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def _openai_response(content: str, finish: str = "stop", refusal: str | None = None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, refusal=refusal), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model="gpt-4o-2024",
        _request_id="req_123",
    )


async def test_openai_success_uses_strict_json_schema() -> None:
    client = FakeOpenAIClient(_openai_response(json.dumps(VALID_INTENT)))
    provider = OpenAIProvider(api_key=FAKE_KEY, model="gpt-4o", client=client)
    result = await provider.generate_structured_output("sys", "user", IntentClassification, 500, 9)
    assert result.parsed_output["intent"] == "MEDIA_SEARCH"
    assert result.usage and result.usage.total_tokens == 15 and result.request_id == "req_123"
    fmt = client.kwargs["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert client.kwargs["timeout"] == 9 and client.kwargs["max_completion_tokens"] == 500


@pytest.mark.parametrize(
    ("content", "finish", "refusal", "error"),
    [
        ("not json", "stop", None, InvalidModelOutputError),
        (json.dumps({"intent": "NOPE"}), "stop", None, InvalidModelOutputError),
        ("{", "length", None, InvalidModelOutputError),
        ("", "stop", "I can't help", ProviderRefusalError),
    ],
)
async def test_openai_invalid_responses_are_rejected(content: str, finish: str, refusal: str | None, error: type) -> None:
    provider = OpenAIProvider(api_key=FAKE_KEY, model="gpt-4o", client=FakeOpenAIClient(_openai_response(content, finish, refusal)))
    with pytest.raises(error):
        await provider.generate_structured_output("s", "u", IntentClassification, 100, 5)


def _openai_errors() -> list[tuple[BaseException, type]]:
    import openai

    return [
        (openai.APITimeoutError(request=_req()), ProviderTimeoutError),
        (openai.RateLimitError("slow down", response=_resp(429), body=None), ProviderRateLimitError),
        (openai.AuthenticationError("bad key " + FAKE_KEY, response=_resp(401), body=None), ProviderAuthError),
        (openai.InternalServerError("boom", response=_resp(500), body=None), ProviderUnavailableError),
        (openai.APIConnectionError(request=_req()), ProviderUnavailableError),
    ]


@pytest.mark.parametrize("pair", range(5))
async def test_openai_sdk_errors_are_translated_without_leaking(pair: int) -> None:
    exc, expected = _openai_errors()[pair]
    provider = OpenAIProvider(api_key=FAKE_KEY, model="gpt-4o", client=FakeOpenAIClient(exc))
    with pytest.raises(expected) as info:
        await provider.generate_structured_output("s", "u", IntentClassification, 100, 5)
    assert FAKE_KEY not in info.value.message
    assert info.value.retryable is (expected is not ProviderAuthError)


# ---------------------------------------------------------------------- Anthropic (mocked SDK)


class FakeAnthropicClient:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.kwargs: dict[str, Any] = {}

        async def create(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            if isinstance(self.outcome, BaseException):
                raise self.outcome
            return self.outcome

        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def _anthropic_response(text: str | None, stop: str = "end_turn") -> Any:
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        content=content, stop_reason=stop, usage=SimpleNamespace(input_tokens=20, output_tokens=7),
        model="claude-opus-5-5", _request_id="req_abc",
    )


async def test_anthropic_success_uses_structured_outputs_and_fallbacks() -> None:
    client = FakeAnthropicClient(_anthropic_response(json.dumps(VALID_INTENT)))
    provider = AnthropicProvider(api_key=FAKE_KEY, model="claude-opus-5-5", client=client)
    result = await provider.generate_structured_output("sys", "user", IntentClassification, 4000, 30)
    assert result.parsed_output["target_website"] == "youtube.com"
    assert result.usage and result.usage.total_tokens == 27
    assert client.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert client.kwargs["output_config"]["effort"] == "medium"
    assert client.kwargs["fallbacks"] == "default" and "tool_choice" not in client.kwargs


async def test_anthropic_without_fallbacks_uses_standard_endpoint() -> None:
    client = FakeAnthropicClient(_anthropic_response(json.dumps(VALID_INTENT)))
    provider = AnthropicProvider(api_key=FAKE_KEY, model="claude-opus-5-5", server_fallbacks=False, client=client)
    await provider.generate_structured_output("sys", "user", IntentClassification, 4000, 30)
    assert "fallbacks" not in client.kwargs and "betas" not in client.kwargs


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (_anthropic_response('{"partial": ', "max_tokens"), InvalidModelOutputError),
        (_anthropic_response(None, "refusal"), ProviderRefusalError),
        (_anthropic_response(None), InvalidModelOutputError),
        (_anthropic_response(json.dumps({"intent": "MEDIA_SEARCH"})), InvalidModelOutputError),
    ],
)
async def test_anthropic_invalid_responses_are_rejected(response: Any, error: type) -> None:
    provider = AnthropicProvider(api_key=FAKE_KEY, model="m", client=FakeAnthropicClient(response))
    with pytest.raises(error):
        await provider.generate_structured_output("s", "u", IntentClassification, 100, 5)


async def test_anthropic_sdk_errors_are_translated() -> None:
    import anthropic

    cases = [
        (anthropic.APITimeoutError(request=_req()), ProviderTimeoutError),
        (anthropic.RateLimitError("slow", response=_resp(429), body=None), ProviderRateLimitError),
        (anthropic.AuthenticationError("bad " + FAKE_KEY, response=_resp(401), body=None), ProviderAuthError),
        (anthropic.InternalServerError("boom", response=_resp(500), body=None), ProviderUnavailableError),
    ]
    for exc, expected in cases:
        provider = AnthropicProvider(api_key=FAKE_KEY, model="m", client=FakeAnthropicClient(exc))
        with pytest.raises(expected) as info:
            await provider.generate_structured_output("s", "u", IntentClassification, 100, 5)
        assert FAKE_KEY not in info.value.message


async def test_provider_failure_never_falls_back_to_mock(provider_client: Any, session_id: str) -> None:
    from .conftest import ScriptedProvider, post_command, wait_for_task_state

    fake = ScriptedProvider({"IntentClassification": [ProviderAuthError()]})
    client = provider_client(fake)
    task_id = post_command(client, "Open YouTube and search for Python", session_id)["task_id"]
    task = wait_for_task_state(client, task_id)
    assert task["state"] == "FAILED"
    assert fake.calls == ["IntentClassification"]  # auth errors are not retried
    assert client.get(f"/api/v1/tasks/{task_id}/plan").status_code == 404


def test_api_key_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    create_provider(make_settings(agent_provider="anthropic", anthropic_api_key=FAKE_KEY))
    assert FAKE_KEY not in caplog.text
