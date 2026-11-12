"""LLM provider layer: one stable boundary, three interchangeable implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import LLMProvider, LLMResult, LLMUsage, ProviderConfigError, ProviderError
from .mock_provider import MockLLMProvider

if TYPE_CHECKING:
    from app.config import Settings


def create_provider(settings: Settings, *, mock_latency_ms: int = 0) -> LLMProvider:
    """Build the configured provider once per app. Never falls back to mock silently."""
    provider = settings.effective_agent_provider
    if provider == "mock":
        return MockLLMProvider(latency_ms=mock_latency_ms)
    if provider == "openai":
        if settings.openai_api_key is None:
            raise ProviderConfigError("AGENT_PROVIDER=openai requires OPENAI_API_KEY.")
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=settings.openai_api_key.get_secret_value(), model=settings.resolved_agent_model)
    if provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise ProviderConfigError("AGENT_PROVIDER=anthropic requires ANTHROPIC_API_KEY.")
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.resolved_agent_model,
            effort=settings.anthropic_effort,
            server_fallbacks=settings.anthropic_server_fallbacks,
        )
    raise ProviderConfigError(f"Unknown AGENT_PROVIDER {settings.agent_provider!r}.")


__all__ = [
    "LLMProvider",
    "LLMResult",
    "LLMUsage",
    "MockLLMProvider",
    "ProviderConfigError",
    "ProviderError",
    "create_provider",
]
