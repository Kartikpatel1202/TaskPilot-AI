"""SelectorResolver on real pages: priority strategies, ambiguity, healing, cache, no raw CSS."""

from __future__ import annotations

import pytest

from app.browser.dom_inspector import DOMInspector
from app.browser.errors import SelectorAmbiguousError, SelectorResolutionError
from app.browser.selector_resolver import SelectorResolver, score_candidate
from app.browser.session import BrowserSession
from app.schemas.browser import DOMElementInfo, TargetDescription

from .conftest import open_fixture


def resolver(attempts: int = 2) -> SelectorResolver:
    return SelectorResolver(DOMInspector(), min_confidence=0.82, max_attempts=attempts)


def T(description: str, role: str | None = None, name: str | None = None, text: str | None = None) -> TargetDescription:
    return TargetDescription(description=description, role_hint=role, accessible_name=name, text_hint=text)


async def test_role_and_exact_name(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    found = await resolver().resolve(session.page, T("Search button", "button", "Search"))
    assert found.strategy == "role+name" and found.element.accessible_name == "Search"


async def test_label_and_placeholder(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    by_label = await resolver().resolve(session.page, T("Search field", "textbox", "Search products"), "type")
    assert by_label.element.role == "searchbox"
    by_placeholder = await resolver().resolve(session.page, T("Search field", None, None, "Search for products"), "type")
    assert by_placeholder.strategy == "placeholder"


async def test_exact_visible_text(session: BrowserSession) -> None:
    await session.page.set_content("<div role='button' tabindex=0>Continue shopping</div><button>Other</button>")
    found = await resolver().resolve(session.page, T("Continue shopping control", None, None, "Continue shopping"))
    assert found.element.accessible_name == "Continue shopping"


async def test_semantic_fallback_without_names(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    found = await resolver().resolve(session.page, T("Product search box", "textbox"), "type")
    assert found.strategy == "semantic" and found.confidence >= 0.82


async def test_context_picks_the_right_card_among_same_named_buttons(session: BrowserSession, fixture_origin: str) -> None:
    await session.page.goto(f"{fixture_origin}/api/v1/dev/fixtures/shop/search.html?q=milk")
    await session.page.wait_for_selector("[data-product]")
    found = await resolver().resolve(session.page, T("Add button for Amul milk 1 litre", "button", "Add", "ADD"))
    assert "Amul Taaza" in (found.element.context_text or "")


async def test_no_match_raises(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    with pytest.raises(SelectorResolutionError):
        await resolver(attempts=1).resolve(session.page, T("Wishlist heart icon", "button", "Wishlist"))


async def test_ambiguous_targets_are_refused_and_nothing_is_clicked(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "ambiguous.html")
    with pytest.raises(SelectorAmbiguousError):
        await resolver().resolve(session.page, T("Add button for Amul Taaza Toned Milk 1 litre", "button", "Add"))
    assert await session.page.locator("[data-clicked]").count() == 0


async def test_disabled_target_is_rejected(session: BrowserSession) -> None:
    await session.page.set_content("<p>Nandini Milk</p><button disabled>Add Nandini Milk</button>")
    with pytest.raises(SelectorResolutionError) as info:
        await resolver(attempts=1).resolve(session.page, T("Add Nandini Milk button", "button", "Add Nandini Milk"))
    assert info.value.code == "ELEMENT_DISABLED"


async def test_bounded_healing_finds_late_element_after_label_change(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "dynamic.html")
    # The planned name ("Search products") no longer exists once the page relabels the box;
    # a fresh inspection + semantic scoring finds the unique search box anyway.
    found = await resolver(attempts=3).resolve(session.page, T("Search box", "textbox", "Search products"), "type")
    assert found.attempts >= 2 and found.element.aria_label == "Find items in the shop"


async def test_retry_limit_is_respected(session: BrowserSession) -> None:
    await session.page.set_content("<p>nothing</p>")
    import time

    start = time.monotonic()
    with pytest.raises(SelectorResolutionError):
        await resolver(attempts=2).resolve(session.page, T("Checkout button", "button", "Checkout"))
    assert time.monotonic() - start < 3


async def test_cached_selector_is_revalidated(session: BrowserSession, fixture_origin: str) -> None:
    r = resolver()
    await open_fixture(session, fixture_origin, "index.html")
    target = T("Product search box", "textbox")
    await r.resolve(session.page, target, "type")
    again = await r.resolve(session.page, target, "type")
    assert again.strategy == "cache"
    await session.page.set_content("<p>no search box any more</p>")
    with pytest.raises(SelectorResolutionError):
        await r.resolve(session.page, target, "type")  # stale cache never used blindly


async def test_css_in_model_text_is_never_executed_as_a_selector(session: BrowserSession) -> None:
    await session.page.set_content("<button id='pay'>Pay</button><button>Safe</button>")
    with pytest.raises(SelectorResolutionError):
        await resolver(attempts=1).resolve(session.page, T("#pay, button:first-child", None, "#pay"))


def test_scoring_requires_role_compatibility() -> None:
    el = DOMElementInfo(tag_name="a", role="link", accessible_name="Cart (2)", is_visible=True, is_enabled=True, is_interactive=True)
    assert score_candidate(T("Cart button", "button", "Cart"), el) >= 0.82  # link-styled "button" tolerated
    assert score_candidate(T("Cart field", "textbox", "Cart"), el) == 0.0
