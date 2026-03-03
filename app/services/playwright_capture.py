"""Capture Google Maps Street View screenshots using Playwright.

Uses the ``map_action=pano`` URL format which reliably enters Street View
mode in headless Chromium (unlike the ``@lat,lon,3a`` format which Google
redirects away from).  WebGL flags are required for tile rendering.

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

_HEADINGS = [0, 120, 240]
_VIEWPORT = {"width": 1200, "height": 800}
_CLIP = {"x": 0, "y": 70, "width": 1200, "height": 640}
_TIMEOUT_MS = 25_000
_TILE_WAIT_MS = 8_000

_browser: Browser | None = None
_context: BrowserContext | None = None
_pw = None
_lock = asyncio.Lock()


async def _ensure_browser() -> BrowserContext:
    """Launch (or reuse) a headless Chromium with WebGL enabled."""
    global _browser, _context, _pw
    if _context is not None:
        return _context

    async with _lock:
        if _context is not None:
            return _context
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(
            headless=True,
            args=[
                "--use-gl=angle",
                "--use-angle=swiftshader-webgl",
                "--enable-webgl",
                "--ignore-gpu-blocklist",
            ],
        )
        _context = await _browser.new_context(
            viewport=_VIEWPORT,
            locale="en-US",
            timezone_id="Asia/Jerusalem",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
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
    """Click through Google's cookie/consent dialog if present."""
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
                await page.wait_for_timeout(800)
                return
        except Exception:
            continue


def _sv_url(lat: float, lon: float, heading: int) -> str:
    """Build a Google Maps URL that reliably opens Street View."""
    return (
        f"https://www.google.com/maps/@?api=1"
        f"&map_action=pano&viewpoint={lat},{lon}&heading={heading}"
    )


async def _is_streetview_loaded(page) -> bool:
    """Check that we actually entered Street View (URL contains '3a')."""
    url = page.url
    return "3a" in url


async def capture_streetview(
    lat: float,
    lon: float,
    headings: list[int] | None = None,
) -> list[dict]:
    """Capture Street View screenshots for given coordinates.

    Returns a list of dicts with keys: ``path``, ``heading``, ``url_path``,
    ``available`` (False if no coverage).
    """
    if headings is None:
        headings = _HEADINGS

    # Check cache
    results: list[dict] = []
    all_cached = True
    for h in headings:
        p = _cache_path(lat, lon, h)
        if p.exists() and p.stat().st_size > 5000:
            results.append({
                "path": p, "heading": h,
                "url_path": f"/captures/{p.name}", "available": True,
            })
        else:
            all_cached = False
            break

    if all_cached and results:
        logger.info("All %d captures cached for %.5f,%.5f", len(results), lat, lon)
        return results

    results.clear()
    try:
        ctx = await _ensure_browser()
    except Exception:
        logger.exception("Failed to launch browser for street view capture")
        return []

    page = await ctx.new_page()
    consent_handled = False
    try:
        for heading in headings:
            out = _cache_path(lat, lon, heading)
            if out.exists() and out.stat().st_size > 5000:
                results.append({
                    "path": out, "heading": heading,
                    "url_path": f"/captures/{out.name}", "available": True,
                })
                continue

            try:
                await page.goto(
                    _sv_url(lat, lon, heading),
                    wait_until="domcontentloaded",
                    timeout=_TIMEOUT_MS,
                )

                if not consent_handled:
                    await _dismiss_consent(page)
                    consent_handled = True

                await page.wait_for_timeout(_TILE_WAIT_MS)

                if not await _is_streetview_loaded(page):
                    logger.info("No Street View at %.5f,%.5f", lat, lon)
                    results.append({
                        "path": None, "heading": heading,
                        "url_path": "", "available": False,
                    })
                    break

                await page.screenshot(
                    path=str(out), type="jpeg", quality=88,
                    clip=_CLIP,
                )
                logger.info(
                    "Captured street view: %s (%d bytes)",
                    out.name, out.stat().st_size,
                )
                results.append({
                    "path": out, "heading": heading,
                    "url_path": f"/captures/{out.name}", "available": True,
                })
            except Exception:
                logger.exception(
                    "Failed to capture heading=%d at %.5f,%.5f",
                    heading, lat, lon,
                )
                results.append({
                    "path": None, "heading": heading,
                    "url_path": "", "available": False,
                })
    finally:
        await page.close()

    return results
