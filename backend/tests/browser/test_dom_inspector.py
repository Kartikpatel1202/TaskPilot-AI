"""DOMInspector on real pages: roles, labels, visibility, privacy, bounds, dynamic DOM."""

from __future__ import annotations

from app.browser.dom_inspector import DOMInspector
from app.browser.session import BrowserSession

from .conftest import open_fixture

inspector = DOMInspector()


async def test_search_input_and_buttons_are_detected(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    elements = await inspector.inspect_interactables(session.page)
    search = next(e for e in elements if e.role == "searchbox")
    assert search.placeholder == "Search for products"
    assert search.label == "Search products" and search.accessible_name == "Search products"
    assert search.is_editable and not search.is_sensitive
    roles = {(e.role, e.accessible_name) for e in elements}
    assert ("button", "Search") in roles and ("link", "Home") in roles
    assert all(e.element_id and e.element_id.startswith("tp-") for e in elements)


async def test_hidden_elements_excluded_and_disabled_marked(session: BrowserSession) -> None:
    await session.page.set_content(
        "<button>Visible</button><button style='display:none'>Hidden</button>"
        "<div hidden><button>Also hidden</button></div><button disabled>Off</button>"
    )
    elements = {e.accessible_name: e for e in await inspector.inspect_interactables(session.page)}
    assert "Hidden" not in elements and "Also hidden" not in elements
    assert elements["Off"].is_enabled is False and elements["Visible"].is_enabled is True


async def test_password_and_otp_fields_are_marked_sensitive_without_values(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "login.html")
    await session.page.fill("#pw", "hunter2-secret")
    await session.page.fill("#otp", "482913")
    elements = await inspector.inspect_interactables(session.page)
    dump = str([e.model_dump() for e in elements])
    assert "hunter2-secret" not in dump and "482913" not in dump
    sensitive = {e.label for e in elements if e.is_sensitive}
    assert {"Password", "One-time code (OTP)"} <= sensitive
    snapshot = await inspector.get_accessible_snapshot(session.page)
    assert "hunter2-secret" not in snapshot["snapshot"] and snapshot["format"] == "aria-yaml"


async def test_output_is_bounded(session: BrowserSession) -> None:
    await session.page.set_content("".join(f"<button>B{i}</button>" for i in range(400)))
    assert len(await inspector.inspect_interactables(session.page, max_elements=25)) == 25


async def test_dynamic_dom_updates_are_seen_on_fresh_inspection(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "dynamic.html")
    assert not [e for e in await inspector.inspect_interactables(session.page) if e.role == "searchbox"]
    await session.page.wait_for_selector("#dq")
    await session.page.wait_for_timeout(250)
    box = next(e for e in await inspector.inspect_interactables(session.page) if e.role == "searchbox")
    assert box.aria_label == "Find items in the shop"


async def test_page_summary_detects_authentication(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    home = await inspector.inspect_page_summary(session.page)
    assert home.auth_required is False and "TaskPilot Demo Shop" in home.headings
    await open_fixture(session, fixture_origin, "login.html")
    login = await inspector.inspect_page_summary(session.page)
    assert login.auth_required is True and login.has_password_field is True


async def test_region_extraction_reads_visible_cards_and_redacts(session: BrowserSession) -> None:
    await session.page.set_content(
        "<ul aria-label='Offers'><li><h3>Tea</h3><p>₹10</p><p>Your OTP is 123456</p></li>"
        "<li style='display:none'><h3>Secret hidden</h3></li></ul>"
    )
    region = await inspector.extract_region(session.page, ["offer"])
    assert [i["heading"] for i in region["items"]] == ["Tea"]
    assert "123456" not in str(region)
