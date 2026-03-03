"""Street-level imagery service.

Uses Playwright to capture Google Maps Street View screenshots.
Falls back to a clickable Google Maps link if capture fails or
there is no coverage.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.models.schemas import StreetImage
from app.services.playwright_capture import capture_streetview

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Playwright Street View capture (headless browser — no API key)
# ---------------------------------------------------------------------------


async def _playwright_streetview_images(lat: float, lon: float) -> list[StreetImage]:
    """Capture Street View screenshots via headless Chromium."""
    try:
        captures = await capture_streetview(lat, lon)
    except Exception:
        logger.exception("Playwright Street View capture failed")
        return []

    images: list[StreetImage] = []
    for cap in captures:
        if not cap.get("available") or not cap.get("url_path"):
            continue
        images.append(
            StreetImage(
                url=cap["url_path"],
                thumbnail_url=cap["url_path"],
                source="Google Street View",
                date="",
                heading=cap.get("heading"),
                lat=lat,
                lon=lon,
            )
        )
    return images


# ---------------------------------------------------------------------------
# Google Street View Static API (needs GOOGLE_STREETVIEW_API_KEY)
# ---------------------------------------------------------------------------

_GSV_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
_GSV_HEADINGS = [0, 90, 180, 270]


async def _check_streetview_coverage(lat: float, lon: float) -> bool:
    key = settings.google_streetview_api_key
    if not key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _GSV_METADATA_URL,
                params={"location": f"{lat},{lon}", "key": key},
            )
            if resp.status_code != 200:
                return False
            return resp.json().get("status") == "OK"
    except Exception:
        logger.exception("Street View metadata check failed")
        return False


async def _google_streetview_images(lat: float, lon: float) -> list[StreetImage]:
    """Generate Street View image entries via the proxy endpoint (API key hidden server-side)."""
    key = settings.google_streetview_api_key
    if not key:
        return []

    has_coverage = await _check_streetview_coverage(lat, lon)
    if not has_coverage:
        return []

    images: list[StreetImage] = []
    for heading in _GSV_HEADINGS:
        proxy_url = f"/api/streetview/image?lat={lat}&lon={lon}&heading={heading}"
        images.append(
            StreetImage(
                url=proxy_url,
                thumbnail_url=proxy_url,
                source="Google Street View",
                date="",
                heading=heading,
                lat=lat,
                lon=lon,
            )
        )
    return images


async def fetch_streetview_bytes(lat: float, lon: float, heading: int = 0, size: str = "640x480") -> bytes | None:
    """Fetch raw Street View image bytes from Google (called by the proxy endpoint)."""
    key = settings.google_streetview_api_key
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/streetview",
                params={
                    "size": size,
                    "location": f"{lat},{lon}",
                    "heading": heading,
                    "pitch": 0,
                    "fov": 90,
                    "key": key,
                },
            )
            if resp.status_code == 200:
                return resp.content
    except Exception:
        logger.exception("Street View image fetch failed")
    return None


# ---------------------------------------------------------------------------
# Google Maps Street View link (always free — opens in browser)
# ---------------------------------------------------------------------------


def _google_maps_sv_link(lat: float, lon: float) -> StreetImage:
    """Generate a clickable Google Maps Street View link (no API key needed)."""
    return StreetImage(
        url=f"https://www.google.com/maps?layer=c&cbll={lat},{lon}",
        thumbnail_url="",
        source="Google Maps Street View",
        date="",
        lat=lat,
        lon=lon,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_street_images(lat: float, lon: float) -> list[StreetImage]:
    """Get street-level images for coordinates.

    Priority:
      1. Playwright capture (actual screenshots, no key needed)
      2. Google Street View Static API (if API key configured)
      3. Clickable Google Maps link fallback
    """
    all_images: list[StreetImage] = []

    pw_images = await _playwright_streetview_images(lat, lon)
    all_images.extend(pw_images)

    if not pw_images:
        gsv = await _google_streetview_images(lat, lon)
        all_images.extend(gsv)

    if not all_images:
        all_images.append(_google_maps_sv_link(lat, lon))

    return all_images
