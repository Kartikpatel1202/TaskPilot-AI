"""DEVELOPMENT/TEST ONLY: serves the local demo-shop fixture for real browser runs.

Enabled only when BROWSER_DEV_FIXTURES_ENABLED=true AND APP_ENV is development or
test (settings validation refuses it elsewhere). Only a fixed set of file names is
served — no directory listing, no path parameters reach the filesystem.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "browser_site"
ALLOWED = {
    "index.html": "text/html", "search.html": "text/html", "cart.html": "text/html", "ambiguous.html": "text/html",
    "dynamic.html": "text/html", "login.html": "text/html", "approval.html": "text/html", "relabel.html": "text/html", "challenge.html": "text/html",
    "shop.js": "text/javascript", "shop.css": "text/css",
}

router = APIRouter(prefix="/dev/fixtures/shop", tags=["development (fixtures only)"], include_in_schema=False)


def _enabled(request: Request) -> None:
    if not request.app.state.container.settings.browser_dev_fixtures_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/{name}")
async def fixture_file(name: str, request: Request) -> FileResponse:
    _enabled(request)
    media = ALLOWED.get(name)
    if media is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(FIXTURE_DIR / name, media_type=media, headers={"Cache-Control": "no-store"})


@router.get("/redirect/{target}")
async def fixture_redirect(target: str, request: Request) -> RedirectResponse:
    """Redirect test: `index` stays in the fixture; `outside` goes to a disallowed private address."""
    _enabled(request)
    if target == "index":
        return RedirectResponse("../index.html", status_code=302)
    if target == "script":
        return RedirectResponse("../shop.js", status_code=302)
    if target == "outside":
        return RedirectResponse("http://10.0.0.1/admin", status_code=302)
    raise HTTPException(status_code=404, detail="Not Found")


# ---------------------------------------------------------------------- Phase 4: commerce fixtures

COMMERCE_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "commerce"
COMMERCE_FILES: dict[str, dict[str, str]] = {
    "blinkit": {
        "index.html": "text/html", "search.html": "text/html", "products.html": "text/html", "cart.html": "text/html",
        "checkout.html": "text/html", "blinkit.js": "text/javascript", "blinkit.css": "text/css",
    },
    "amazon": {
        "index.html": "text/html", "search.html": "text/html", "product.html": "text/html", "cart.html": "text/html",
        "checkout.html": "text/html", "amazon.js": "text/javascript", "amazon.css": "text/css",
    },
}

commerce_router = APIRouter(prefix="/dev/fixtures/commerce", tags=["development (fixtures only)"], include_in_schema=False)


@commerce_router.get("/{site}/{name}")
async def commerce_fixture_file(site: str, name: str, request: Request) -> FileResponse:
    """Blinkit-like / Amazon-like LOCAL test shops (COMMERCE_ENABLE_FIXTURES, dev/test only)."""
    if not request.app.state.container.settings.commerce_enable_fixtures:
        raise HTTPException(status_code=404, detail="Not Found")
    media = COMMERCE_FILES.get(site, {}).get(name)
    if media is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(COMMERCE_FIXTURE_DIR / site / name, media_type=media, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------- Phase 5: integration fixtures

INTEGRATION_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "integrations"
INTEGRATION_FILES: dict[str, dict[str, str]] = {
    "youtube": {"index.html": "text/html", "results.html": "text/html", "watch.html": "text/html",
                "youtube.js": "text/javascript", "youtube.css": "text/css"},
    "gmail": {"index.html": "text/html", "signin.html": "text/html", "gmail.js": "text/javascript", "gmail.css": "text/css"},
    "calendar": {"index.html": "text/html", "day.html": "text/html", "eventedit.html": "text/html", "signin.html": "text/html",
                 "calendar.js": "text/javascript", "calendar.css": "text/css"},
    "files": {"index.html": "text/html", "report.pdf": "application/pdf", "data.csv": "text/csv", "sample.txt": "text/plain",
              "image.png": "image/png", "invalid_extension.txt": "text/plain", "fake_executable.bin": "application/octet-stream",
              "disguised.pdf": "application/pdf"},
}
OVERSIZED_BYTES = 26 * 1024 * 1024

integrations_router = APIRouter(prefix="/dev/fixtures/integrations", tags=["development (fixtures only)"], include_in_schema=False)


def _integrations_enabled(request: Request) -> None:
    if not request.app.state.container.settings.integration_enable_fixtures:
        raise HTTPException(status_code=404, detail="Not Found")


@integrations_router.get("/files/redirect/{target}")
async def integration_file_redirect(target: str, request: Request) -> RedirectResponse:
    """Download redirect tests: `inside` stays on the fixture; `outside` points at a private address."""
    _integrations_enabled(request)
    location = {"inside": "../report.pdf", "outside": "http://10.0.0.1/report.pdf"}.get(target)
    if location is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return RedirectResponse(location, status_code=302)


@integrations_router.get("/{site}/{name}")
async def integration_fixture_file(site: str, name: str, request: Request) -> Response:
    """YouTube-like / Gmail-like / Calendar-like LOCAL test pages and download test files (dev/test only)."""
    _integrations_enabled(request)
    if site == "files" and name == "oversized_file.pdf":
        def chunks() -> Iterator[bytes]:
            yield b"%PDF-1.4\n"
            block = b"0" * 65536
            for _ in range(OVERSIZED_BYTES // len(block)):
                yield block

        return StreamingResponse(chunks(), media_type="application/pdf", headers={"Cache-Control": "no-store"})
    media = INTEGRATION_FILES.get(site, {}).get(name)
    if media is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(INTEGRATION_FIXTURE_DIR / site / name, media_type=media, headers={"Cache-Control": "no-store"})
