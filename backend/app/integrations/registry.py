"""Maps validated sites to integration domains (Phase 5).

A binding is chosen from a *validated* canonical host (youtube.com, mail.google.com,
calendar.google.com) or, in development/test only, from the exact local fixture domain —
never from an arbitrary user-supplied name.
"""

from __future__ import annotations

from app.agent.websites import Website
from app.integrations.base import DomainBinding
from app.schemas.integration import DomainType

FIXTURE_PATH = "/api/v1/dev/fixtures/integrations/"

REAL_BINDINGS = (
    DomainBinding("youtube", DomainType.YOUTUBE, "YouTube", "https://www.youtube.com/", "https://www.youtube.com"),
    DomainBinding("gmail", DomainType.GMAIL, "Gmail", "https://mail.google.com/mail/u/0/#inbox", "https://mail.google.com"),
    DomainBinding("gcalendar", DomainType.GOOGLE_CALENDAR, "Google Calendar", "https://calendar.google.com/calendar/r",
                  "https://calendar.google.com"),
)
REAL_DOMAINS = {
    DomainType.YOUTUBE: ("youtube.com", "youtu.be"),
    DomainType.GMAIL: ("mail.google.com",),
    DomainType.GOOGLE_CALENDAR: ("calendar.google.com",),
}
FIXTURE_FOLDERS = {DomainType.YOUTUBE: "youtube", DomainType.GMAIL: "gmail", DomainType.GOOGLE_CALENDAR: "calendar", DomainType.FILES: "files"}
FIXTURE_KEYS = {DomainType.YOUTUBE: "fx-youtube", DomainType.GMAIL: "fx-gmail", DomainType.GOOGLE_CALENDAR: "fx-calendar",
                DomainType.FILES: "fx-files"}
FIXTURE_DOMAINS = {DomainType.YOUTUBE: "youtube.fixture.test", DomainType.GMAIL: "gmail.fixture.test",
                   DomainType.GOOGLE_CALENDAR: "calendar.fixture.test", DomainType.FILES: "files.fixture.test"}
_FIXTURE_NAMES = {DomainType.YOUTUBE: "YouTube test fixture", DomainType.GMAIL: "Gmail test fixture",
                  DomainType.GOOGLE_CALENDAR: "Calendar test fixture", DomainType.FILES: "Files test fixture"}
_FIXTURE_ALIASES = {
    DomainType.YOUTUBE: ("fixture youtube", "youtube fixture", "test youtube", "demo youtube"),
    DomainType.GMAIL: ("fixture gmail", "gmail fixture", "test gmail", "demo gmail"),
    DomainType.GOOGLE_CALENDAR: ("fixture calendar", "calendar fixture", "test calendar", "demo calendar"),
    DomainType.FILES: ("fixture files", "files fixture", "test files", "demo files"),
}
_CATEGORY = {DomainType.YOUTUBE: "media", DomainType.GMAIL: "email", DomainType.GOOGLE_CALENDAR: "calendar", DomainType.FILES: "general"}
_FIRST_PAGE = {DomainType.YOUTUBE: "index.html", DomainType.GMAIL: "index.html", DomainType.GOOGLE_CALENDAR: "index.html",
               DomainType.FILES: "index.html"}


def fixture_binding(domain: DomainType, origin: str) -> DomainBinding:
    prefix = origin.rstrip("/") + FIXTURE_PATH + FIXTURE_FOLDERS[domain]
    return DomainBinding(FIXTURE_KEYS[domain], domain, _FIXTURE_NAMES[domain], prefix + "/" + _FIRST_PAGE[domain], prefix, is_fixture=True)


def fixture_website(domain: DomainType, origin: str) -> Website:
    binding = fixture_binding(domain, origin)
    return Website(binding.key, binding.name, FIXTURE_DOMAINS[domain], binding.base_url, _CATEGORY[domain], _FIXTURE_ALIASES[domain])


class IntegrationRegistry:
    def __init__(self, enabled: set[DomainType]) -> None:
        self._enabled = enabled
        self._bindings: dict[str, DomainBinding] = {b.key: b for b in REAL_BINDINGS if b.domain in enabled}
        self._host_to_key: dict[str, str] = {}
        for b in self._bindings.values():
            for host in REAL_DOMAINS[b.domain]:
                self._host_to_key[host] = b.key

    def register_fixture(self, binding: DomainBinding) -> None:
        """Development/test only (the container checks INTEGRATION_ENABLE_FIXTURES + APP_ENV)."""
        if binding.domain in self._enabled:
            self._bindings[binding.key] = binding
            self._host_to_key[FIXTURE_DOMAINS[binding.domain]] = binding.key

    def binding(self, key: str) -> DomainBinding | None:
        return self._bindings.get(key)

    def default(self, domain: DomainType) -> DomainBinding | None:
        return next((b for b in self._bindings.values() if b.domain == domain and not b.is_fixture), None)

    def binding_for_website(self, website: str | None, domain: DomainType) -> DomainBinding | None:
        """Exact canonical host (or the exact fixture domain) of the requested domain; else the real default."""
        if website:
            host = website.lower().strip().removeprefix("https://").removeprefix("http://").split("/")[0].removeprefix("www.")
            key = self._host_to_key.get(host)
            if key is not None:
                b = self._bindings[key]
                return b if b.domain == domain else None
        return self.default(domain)

    def fixture_for(self, domain: DomainType) -> DomainBinding | None:
        return next((b for b in self._bindings.values() if b.domain == domain and b.is_fixture), None)

    def bindings(self) -> list[DomainBinding]:
        return list(self._bindings.values())
