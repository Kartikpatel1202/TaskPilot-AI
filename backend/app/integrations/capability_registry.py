"""Trusted capability registry (Phase 5).

Every capability a plan may use is declared here by trusted code — never by the model.
A capability is usable only when its domain is enabled in settings; plan steps are
validated against this registry before they are accepted and again before they run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.schemas.approval import RiskLevel
from app.schemas.integration import CapabilityDefinition, DomainType, IntegrationCapability

if TYPE_CHECKING:
    from app.config import Settings

C = IntegrationCapability
D = DomainType

# action type -> capability it executes
ACTION_CAPABILITY: dict[str, IntegrationCapability] = {
    "youtube_search": C.YOUTUBE_SEARCH,
    "youtube_play": C.YOUTUBE_PLAY,
    "gmail_create_draft": C.GMAIL_CREATE_DRAFT,
    "calendar_create_event": C.CALENDAR_CREATE_EVENT,
    "file_download": C.FILE_DOWNLOAD,
}

_DEFINITIONS: tuple[tuple[IntegrationCapability, DomainType, str, dict[str, object], bool, bool, RiskLevel, str | None], ...] = (
    (C.YOUTUBE_SEARCH, D.YOUTUBE, "Search YouTube and read the visible results.",
     {"query": "string", "max_results": "int"}, True, False, RiskLevel.LOW, "youtube_search"),
    (C.YOUTUBE_PLAY, D.YOUTUBE, "Open a chosen video and verify that it is playing (no downloading, no ad/DRM bypass).",
     {"video_reference": "selected_from_search | youtube watch URL"}, True, False, RiskLevel.LOW, "youtube_play"),
    (C.GMAIL_CREATE_DRAFT, D.GMAIL, "Compose and save a Gmail DRAFT. Sending is never automated.",
     {"recipient_emails": "list[email]", "subject": "string", "body": "string"}, True, False, RiskLevel.MEDIUM, "gmail_create_draft"),
    (C.GMAIL_READ_DRAFT, D.GMAIL, "Confirm a saved draft appears in Drafts (draft metadata only).",
     {"subject": "string"}, True, False, RiskLevel.LOW, None),
    (C.CALENDAR_LIST_EVENTS, D.GOOGLE_CALENDAR, "Read visible events on one day for an advisory conflict check.",
     {"date": "date"}, True, False, RiskLevel.LOW, None),
    (C.CALENDAR_CREATE_EVENT, D.GOOGLE_CALENDAR, "Create ONE event after exact-event approval, then verify it.",
     {"title": "string", "start_at": "datetime", "end_at": "datetime", "timezone": "IANA"}, True, True, RiskLevel.HIGH,
     "calendar_create_event"),
    (C.FILE_DOWNLOAD, D.FILES, "Download one allow-listed file type into isolated per-session storage (never executed).",
     {"source_url": "http(s) URL", "file_description": "string"}, False, False, RiskLevel.MEDIUM, "file_download"),
    (C.FILE_INSPECT, D.FILES, "Read metadata of a downloaded file (name, type, size, SHA-256).",
     {"file_id": "uuid"}, False, False, RiskLevel.LOW, None),
    (C.COMMERCE_SEARCH, D.BLINKIT, "Phase 4 product search (see commerce docs).", {}, True, False, RiskLevel.LOW, "commerce"),
    (C.COMMERCE_CART, D.AMAZON_IN, "Phase 4 cart preparation (see commerce docs).", {}, True, False, RiskLevel.MEDIUM, "commerce"),
)


class CapabilityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class CapabilityRegistry:
    def __init__(self, settings: Settings) -> None:
        enabled_domains = self.enabled_domains(settings)
        self._defs: dict[IntegrationCapability, CapabilityDefinition] = {}
        for cap, domain, desc, schema, browser, approval, risk, action in _DEFINITIONS:
            self._defs[cap] = CapabilityDefinition(
                capability=cap, domain=domain, description=desc, input_schema=schema, requires_browser=browser,
                requires_approval=approval, risk_level=risk, enabled=domain in enabled_domains, action_type=action,
            )

    @staticmethod
    def enabled_domains(settings: Settings) -> set[DomainType]:
        domains: set[DomainType] = set()
        if settings.commerce_enabled:
            platforms = set(settings.commerce_platform_list)
            if "BLINKIT" in platforms:
                domains.add(D.BLINKIT)
            if "AMAZON_IN" in platforms:
                domains.add(D.AMAZON_IN)
        if not settings.integrations_enabled:
            return domains
        if settings.youtube_enabled:
            domains.add(D.YOUTUBE)
        if settings.gmail_enabled:
            domains.add(D.GMAIL)
        if settings.google_calendar_enabled:
            domains.add(D.GOOGLE_CALENDAR)
        if settings.file_download_enabled:
            domains.add(D.FILES)
        return domains

    def all(self) -> list[CapabilityDefinition]:
        return list(self._defs.values())

    def get(self, capability: IntegrationCapability) -> CapabilityDefinition:
        return self._defs[capability]

    def for_action(self, action_type: str) -> CapabilityDefinition | None:
        cap = ACTION_CAPABILITY.get(action_type)
        return self._defs.get(cap) if cap else None

    def require(self, action_type: str) -> CapabilityDefinition:
        """The enabled capability behind a plan action, or a safe error. Unknown actions are never accepted."""
        definition = self.for_action(action_type)
        if definition is None:
            raise CapabilityError("CAPABILITY_NOT_SUPPORTED", f"'{action_type}' is not a registered integration capability.")
        if not definition.enabled:
            raise CapabilityError("CAPABILITY_DISABLED", f"{definition.domain.value} automation is not enabled on this server.")
        return definition

    def domain_capabilities(self, domain: DomainType) -> list[IntegrationCapability]:
        return [d.capability for d in self._defs.values() if d.domain == domain]
