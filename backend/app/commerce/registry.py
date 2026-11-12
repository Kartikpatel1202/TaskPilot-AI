"""Maps validated sites to commerce adapters.

An adapter is chosen from a *validated* host (blinkit.com / amazon.in, exact or real
subdomain) or, in development/test only, from the exact local fixture prefix — never
from an arbitrary user-supplied name.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.agent.websites import Website
from app.browser.navigation_guard import domain_allowed
from app.commerce.base import CommerceAdapter, SiteBinding
from app.schemas.product import CommercePlatform

FIXTURE_PATH = "/api/v1/dev/fixtures/commerce/"

REAL_BINDINGS = (
    SiteBinding("blinkit", CommercePlatform.BLINKIT, "Blinkit", "https://blinkit.com/", "https://blinkit.com"),
    SiteBinding("amazon", CommercePlatform.AMAZON_IN, "Amazon India", "https://www.amazon.in/", "https://www.amazon.in"),
)
REAL_DOMAINS = {CommercePlatform.BLINKIT: "blinkit.com", CommercePlatform.AMAZON_IN: "amazon.in"}

FIXTURE_KEYS = {CommercePlatform.BLINKIT: "fx-blinkit", CommercePlatform.AMAZON_IN: "fx-amazon"}
FIXTURE_DOMAINS = {CommercePlatform.BLINKIT: "blinkit.fixture.test", CommercePlatform.AMAZON_IN: "amazon.fixture.test"}


def fixture_binding(platform: CommercePlatform, origin: str) -> SiteBinding:
    folder = "blinkit" if platform == CommercePlatform.BLINKIT else "amazon"
    prefix = origin.rstrip("/") + FIXTURE_PATH + folder
    name = "Blinkit test fixture" if platform == CommercePlatform.BLINKIT else "Amazon test fixture"
    return SiteBinding(FIXTURE_KEYS[platform], platform, name, prefix + "/index.html", prefix, is_fixture=True)


def fixture_website(platform: CommercePlatform, origin: str) -> Website:
    binding = fixture_binding(platform, origin)
    if platform == CommercePlatform.BLINKIT:
        aliases = ("fixture blinkit", "blinkit fixture", "test blinkit", "demo blinkit")
    else:
        aliases = ("fixture amazon", "amazon fixture", "test amazon", "demo amazon")
    category = "grocery" if platform == CommercePlatform.BLINKIT else "ecommerce"
    return Website(binding.key, binding.name, FIXTURE_DOMAINS[platform], binding.base_url, category, aliases)


class CommerceRegistry:
    def __init__(self, adapters: dict[CommercePlatform, CommerceAdapter], enabled_platforms: list[str]) -> None:
        self._adapters = adapters
        self._enabled = {CommercePlatform(p) for p in enabled_platforms}
        self._bindings: dict[str, SiteBinding] = {b.key: b for b in REAL_BINDINGS if b.platform in self._enabled}
        self._domain_to_key: dict[str, str] = {REAL_DOMAINS[b.platform]: b.key for b in self._bindings.values()}

    def register_fixture(self, binding: SiteBinding) -> None:
        """Development/test only (the container checks COMMERCE_ENABLE_FIXTURES + APP_ENV)."""
        if binding.platform in self._enabled:
            self._bindings[binding.key] = binding
            self._domain_to_key[FIXTURE_DOMAINS[binding.platform]] = binding.key

    def binding(self, key: str) -> SiteBinding | None:
        return self._bindings.get(key)

    def adapter(self, platform: CommercePlatform) -> CommerceAdapter:
        return self._adapters[platform]

    def binding_for_website(self, domain: str | None) -> SiteBinding | None:
        """Resolve a classified target website to a binding — exact canonical domains only."""
        if not domain:
            return None
        host = domain.lower().strip().removeprefix("https://").removeprefix("http://").split("/")[0].removeprefix("www.")
        key = self._domain_to_key.get(host)
        return self._bindings.get(key) if key else None

    def binding_for_url(self, url: str | None) -> SiteBinding | None:
        """Which site a live page belongs to (domain-validated; fixtures by exact prefix)."""
        if not url:
            return None
        for binding in self._bindings.values():
            if binding.is_fixture and url.startswith(binding.url_prefix + "/"):
                return binding
        host = (urlsplit(url).hostname or "").lower()
        for binding in self._bindings.values():
            if not binding.is_fixture and domain_allowed(host, [REAL_DOMAINS[binding.platform]]):
                return binding
        return None

    def bindings(self) -> list[SiteBinding]:
        return list(self._bindings.values())
