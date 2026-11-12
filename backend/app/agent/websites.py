"""Known website catalog (aliases -> canonical domain).

Used to normalise `target_website` values and by the mock planner. This is
reference data, not an allow-list: URL safety is enforced by `url_policy`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Website:
    key: str
    name: str
    domain: str
    base_url: str
    category: str  # grocery | ecommerce | media | email | calendar | general
    aliases: tuple[str, ...]


WEBSITES: tuple[Website, ...] = (
    Website("blinkit", "Blinkit", "blinkit.com", "https://blinkit.com", "grocery",
            # Speech recognition often splits or mishears the name ("blink it", "billing kit").
            ("blinkit", "blink it", "blink-it", "blinket", "blinkitt", "blink kit", "billing kit", "blinkeet", "ब्लिंकिट", "ब्लिंक इट")),
    Website("zepto", "Zepto", "zeptonow.com", "https://www.zeptonow.com", "grocery", ("zepto", "ज़ेप्टो")),
    Website("bigbasket", "BigBasket", "bigbasket.com", "https://www.bigbasket.com", "grocery", ("bigbasket", "big basket")),
    Website("instamart", "Swiggy Instamart", "swiggy.com", "https://www.swiggy.com/instamart", "grocery", ("instamart",)),
    Website("amazon", "Amazon", "amazon.in", "https://www.amazon.in", "ecommerce", ("amazon", "amezon", "amazone", "अमेज़न", "अमेजन")),
    Website("flipkart", "Flipkart", "flipkart.com", "https://www.flipkart.com", "ecommerce", ("flipkart", "फ्लिपकार्ट")),
    Website("myntra", "Myntra", "myntra.com", "https://www.myntra.com", "ecommerce", ("myntra",)),
    Website("youtube", "YouTube", "youtube.com", "https://www.youtube.com", "media", ("youtube", "you tube", "यूट्यूब")),
    Website("spotify", "Spotify", "open.spotify.com", "https://open.spotify.com", "media", ("spotify",)),
    Website("gmail", "Gmail", "mail.google.com", "https://mail.google.com", "email", ("gmail", "जीमेल")),
    Website("outlook", "Outlook", "outlook.live.com", "https://outlook.live.com", "email", ("outlook",)),
    Website(
        "gcalendar", "Google Calendar", "calendar.google.com", "https://calendar.google.com", "calendar",
        ("google calendar", "gcal", "calendar"),
    ),
    Website("google", "Google", "google.com", "https://www.google.com", "general", ("google",)),
    Website("wikipedia", "Wikipedia", "wikipedia.org", "https://www.wikipedia.org", "general", ("wikipedia",)),
    Website("github", "GitHub", "github.com", "https://github.com", "general", ("github",)),
)

_BY_DOMAIN: dict[str, Website] = {w.domain: w for w in WEBSITES}
_EXTRA: list[Website] = []


def all_websites() -> tuple[Website, ...]:
    return (*WEBSITES, *_EXTRA)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    # Devanagari has no \b semantics in `re`, so match those aliases as substrings.
    if alias.isascii():
        return re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", re.IGNORECASE)
    return re.compile(re.escape(alias))


_ALIAS_PATTERNS = [(w, _alias_pattern(a)) for w in WEBSITES for a in w.aliases]


def register_website(site: Website) -> None:
    """Register a runtime site (only the dev/test demo shop). Idempotent per key."""
    global _EXTRA
    _EXTRA = [w for w in _EXTRA if w.key != site.key] + [site]
    for domain in [d for d, w in _BY_DOMAIN.items() if w.key == site.key]:
        del _BY_DOMAIN[domain]
    _BY_DOMAIN[site.domain] = site
    _ALIAS_PATTERNS[:] = [(w, p) for w, p in _ALIAS_PATTERNS if w.key != site.key]
    _ALIAS_PATTERNS.extend((site, _alias_pattern(a)) for a in site.aliases)


def unregister_website(key: str) -> None:
    global _EXTRA
    _EXTRA = [w for w in _EXTRA if w.key != key]
    for domain in [d for d, w in _BY_DOMAIN.items() if w.key == key]:
        del _BY_DOMAIN[domain]
    _ALIAS_PATTERNS[:] = [(w, p) for w, p in _ALIAS_PATTERNS if w.key != key]


DEMO_SHOP_KEY = "demoshop"
DEMO_SHOP_PATH = "/api/v1/dev/fixtures/shop/index.html"


def demo_shop_website(origin: str) -> Website:
    """The local fixture shop (development/test only; served by the backend itself)."""
    netloc = re.sub(r"^https?://", "", origin.rstrip("/"))
    return Website(
        DEMO_SHOP_KEY,
        "TaskPilot Demo Shop",
        netloc,
        origin.rstrip("/") + DEMO_SHOP_PATH,
        "grocery",
        ("demo shop", "demo shopping website", "demo shopping site", "demo store", "taskpilot shop"),
    )


def find_websites(text: str) -> list[Website]:
    """All catalog websites mentioned in `text`, ordered by first mention."""
    hits: dict[str, tuple[int, Website]] = {}
    for website, pattern in _ALIAS_PATTERNS:
        match = pattern.search(text)
        if match and (website.key not in hits or match.start() < hits[website.key][0]):
            hits[website.key] = (match.start(), website)
    # "google calendar" should win over "google" when both match at the same place.
    ordered = sorted(hits.values(), key=lambda item: (item[0], -len(item[1].name)))
    result: list[Website] = []
    for _, site in ordered:
        if site.key == "google" and any(w.key == "gcalendar" for _, w in ordered):
            continue
        result.append(site)
    return result


def lookup(value: str | None) -> Website | None:
    """Resolve a domain, URL-ish string or alias to a catalog entry."""
    if not value:
        return None
    cleaned = value.strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned).split("/")[0].removeprefix("www.")
    if cleaned in _BY_DOMAIN:
        return _BY_DOMAIN[cleaned]
    for website in all_websites():
        if cleaned == website.key or cleaned in website.aliases or cleaned == website.name.lower():
            return website
    found = find_websites(value)
    return found[0] if found else None


def normalize_website(value: str | None) -> str | None:
    """Canonical domain for known sites; a cleaned hostname-like string otherwise."""
    if not value:
        return None
    site = lookup(value)
    if site:
        return site.domain
    cleaned = re.sub(r"^https?://", "", value.strip().lower()).split("/")[0].removeprefix("www.")
    return cleaned[:253] or None
