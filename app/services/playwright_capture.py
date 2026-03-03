"""Capture Google Maps Street View screenshots using Playwright.

Provides actual street-level photos for any coordinate without needing
a Google API key.  Uses a persistent browser instance to avoid cold-start
overhead on every request.

Screenshots are saved to ``app/captures/`` and served as static files.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext

logger = logging.getLogger(__name__)

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"
CAPTURES_DIR.mkdir(exist_ok=True)

_HEADINGS = [0, 90, 180, 270]
_VIEWPORT = {"width": 1000, "height": 700}
_TIMEOUT_MS = 25_000

_browser: Browser | None = None
_context: BrowserContext | None = None
_pw = None
_lock = asyncio.Lock()

_HIDE_UI_CSS = """
/* Hide all Google Maps UI overlays, keep only the panorama canvas */
.app-viewcard-strip,
.scene-footer,
.widget-minimap,
#omnibox,
#watermark,
.app-horizontal-widget-holder,
.scene-header,
#titlecard,
.widget-scene-cardless,
.noprint,
.app-bottom-content-anchor,
.widget-scene,
.scene-action-bar,
.scene-description,
.widget-pane,
.id-content-container,
div[class*="watermark"],
div[class*="controls"],
div[class*="titlecard"],
a[href*="maps.google.com/maps"],
.scene-overlay,
button[jsaction],
div.widget-zoom,
div.widget-compass,
div.gm-iv-address,
div.gm-iv-container > div:not(canvas),
div[class*="report"],
.widget-imagery-attribution,
div[role="dialog"],
div.consent-bump,
div.gm-style > div > div:not(:first-child),
div.app-bottom-content-anchor,
div.scene-footer-container {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
}

/* Make the panorama canvas fill the viewport */
#scene_canvas,
canvas.widget-scene-canvas {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    z-index: 99999 !important;
}
"""


async def _ensure_browser() -> BrowserContext:
    """Launch (or reuse) a headless Chromium browser."""
    global _browser, _context, _pw
    if _context is not None:
        return _context

    async with _lock:
        if _context is not None:
            return _context
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(headless=True)
        _context = await _browser.new_context(
            viewport=_VIEWPORT,
            locale="en-US",
            timezone_id="Asia/Jerusalem",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        return _context


async def shutdown_browser() -> None:
    """Cleanly close the browser (call during app shutdown)."""
    global _browser, _context, _pw
    if _context:
        await _context.close()
        _context = None
    if _browser:
        await _browser.close()
        _browser = None
    if _pw:
        await _pw.stop()
        _pw = None


def _cache_path(lat: float, lon: float, heading: int) -> Path:
    key = f"{lat:.6f}_{lon:.6f}_{heading}"
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return CAPTURES_DIR / f"sv_{h}.jpg"


async def _dismiss_consent(page) -> None:
    """Click through Google's cookie/consent dialog if it appears."""
    for selector in [
        'button:has-text("Accept all")',
        'button:has-text("Reject all")',
        'form[action*="consent"] button:first-of-type',
        '[aria-label="Accept all"]',
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await page.wait_for_timeout(1000)
                return
        except Exception:
            continue


async def _inject_hide_css(page) -> None:
    """Inject CSS to hide all Maps UI and maximize the panorama canvas."""
    await page.add_style_tag(content=_HIDE_UI_CSS)


async def _has_streetview_coverage(page) -> bool:
    """Return False if Google shows a 'no imagery' message."""
    for text in [
        "Sorry, we have no imagery here",
        "no imagery here",
        "אין לנו תמונות במיקום הזה",
    ]:
        try:
            loc = page.get_by_text(text, exact=False)
            if await loc.count() > 0:
                return False
        except Exception:
            continue

    try:
        canvas = page.locator("canvas")
        if await canvas.count() == 0:
            return False
    except Exception:
        return False

    return True


async def capture_streetview(
    lat: float,
    lon: float,
    headings: list[int] | None = None,
) -> list[dict]:
    """Capture Street View screenshots for given coordinates.

    Returns a list of dicts with keys: ``path``, ``heading``, ``url_path``,
    ``available`` (False if Street View had no coverage).
    """
    if headings is None:
        headings = _HEADINGS

    results: list[dict] = []
    cached_all = True
    for h in headings:
        p = _cache_path(lat, lon, h)
        if p.exists() and p.stat().st_size > 5000:
            results.append({
                "path": p,
                "heading": h,
                "url_path": f"/captures/{p.name}",
                "available": True,
            })
        else:
            cached_all = False
            break

    if cached_all and results:
        logger.info("All %d street view captures cached for %.5f,%.5f", len(results), lat, lon)
        return results

    results.clear()
    try:
        ctx = await _ensure_browser()
    except Exception:
        logger.exception("Failed to launch browser for street view capture")
        return []

    page = await ctx.new_page()
    try:
        first_nav = True
        for heading in headings:
            out = _cache_path(lat, lon, heading)
            if out.exists() and out.stat().st_size > 5000:
                results.append({
                    "path": out,
                    "heading": heading,
                    "url_path": f"/captures/{out.name}",
                    "available": True,
                })
                continue

            sv_url = (
                f"https://www.google.com/maps/@{lat},{lon},3a,90y,"
                f"{heading}h,90t/data=!3m1!1e3"
            )

            try:
                await page.goto(sv_url, wait_until="domcontentloaded", timeout=_TIMEOUT_MS)

                if first_nav:
                    await _dismiss_consent(page)
                    first_nav = False

                await _inject_hide_css(page)

                # Wait for the panorama canvas to render
                try:
                    await page.locator("canvas").first.wait_for(state="visible", timeout=10_000)
                except Exception:
                    pass

                # Let the panorama tiles finish loading
                await page.wait_for_timeout(3500)

                # Re-inject CSS (Google may re-render UI after tiles load)
                await _inject_hide_css(page)
                await page.wait_for_timeout(500)

                if not await _has_streetview_coverage(page):
                    logger.info("No Street View coverage at %.5f,%.5f", lat, lon)
                    results.append({
                        "path": None, "heading": heading,
                        "url_path": "", "available": False,
                    })
                    break

                await page.screenshot(path=str(out), type="jpeg", quality=85)
                logger.info("Captured street view: %s (%d bytes)", out.name, out.stat().st_size)

                results.append({
                    "path": out,
                    "heading": heading,
                    "url_path": f"/captures/{out.name}",
                    "available": True,
                })
            except Exception:
                logger.exception("Failed to capture heading=%d at %.5f,%.5f", heading, lat, lon)
                results.append({
                    "path": None, "heading": heading,
                    "url_path": "", "available": False,
                })
    finally:
        await page.close()

    return results
