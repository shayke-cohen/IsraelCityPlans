"""Street-level imagery service.

Layered free sources:
  1. Google Street View Static API (if GOOGLE_STREETVIEW_API_KEY is set — actual images)
  2. Wikimedia Commons geosearch (completely free, no key needed)
  3. Mapillary (optional — free token from mapillary.com/developer)
  4. Google Maps Street View link fallback (no API key — opens in browser)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.models.schemas import StreetImage

logger = logging.getLogger(__name__)

_BBOX_OFFSET = 0.0005  # ~55m at Israel's latitude


# ---------------------------------------------------------------------------
# Wikimedia Commons — completely free, no API key needed
# ---------------------------------------------------------------------------

_WIKI_API = "https://commons.wikimedia.org/w/api.php"
_WIKI_HEADERS = {
    "User-Agent": "AmitAddress/0.2 (https://github.com/shayke-cohen/IsraelCityPlans; building-plans-finder) httpx/0.27",
}


async def _wikimedia_images(lat: float, lon: float, limit: int = 8) -> list[StreetImage]:
    """Fetch geotagged photos from Wikimedia Commons near the coordinates."""
    geo_params = {
        "action": "query",
        "list": "geosearch",
        "gscoord": f"{lat}|{lon}",
        "gsradius": 500,
        "gsnamespace": 6,
        "gsprimary": "all",
        "gslimit": limit,
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=15, headers=_WIKI_HEADERS) as client:
            resp = await client.get(_WIKI_API, params=geo_params)
            resp.raise_for_status()
            geo_data = resp.json()

            pages = geo_data.get("query", {}).get("geosearch", [])
            if not pages:
                return []

            page_ids = "|".join(str(p["pageid"]) for p in pages)
            info_params = {
                "action": "query",
                "pageids": page_ids,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|timestamp|size",
                "iiurlwidth": 800,
                "format": "json",
            }

            resp2 = await client.get(_WIKI_API, params=info_params)
            resp2.raise_for_status()
            info_data = resp2.json()
    except Exception:
        logger.exception("Wikimedia Commons query failed")
        return []

    images: list[StreetImage] = []
    page_map = {p["pageid"]: p for p in pages}
    for pid_str, page in info_data.get("query", {}).get("pages", {}).items():
        ii_list = page.get("imageinfo", [])
        if not ii_list:
            continue
        ii = ii_list[0]

        thumb = ii.get("thumburl", "")
        full = ii.get("url", "")
        if not thumb and not full:
            continue

        # Skip SVG/icon files that are not photos
        mime = ii.get("mime", "")
        if mime and "svg" in mime:
            continue

        pid = int(pid_str)
        geo_info = page_map.get(pid, {})

        date_str = ""
        ts = ii.get("timestamp", "")
        if ts:
            date_str = ts[:10]

        images.append(
            StreetImage(
                url=full,
                thumbnail_url=thumb or full,
                source="Wikimedia Commons",
                date=date_str,
                lat=geo_info.get("lat", lat),
                lon=geo_info.get("lon", lon),
            )
        )

    return images


# ---------------------------------------------------------------------------
# Mapillary (optional — needs free token from mapillary.com/developer)
# ---------------------------------------------------------------------------

_MAPILLARY_GRAPH = "https://graph.mapillary.com"
_MAPILLARY_FIELDS = "id,captured_at,compass_angle,thumb_1024_url,thumb_original_url,geometry"


async def _mapillary_images(lat: float, lon: float, limit: int = 5) -> list[StreetImage]:
    token = settings.mapillary_client_token
    if not token:
        logger.debug("Mapillary token not configured, skipping")
        return []

    bbox = f"{lon - _BBOX_OFFSET},{lat - _BBOX_OFFSET},{lon + _BBOX_OFFSET},{lat + _BBOX_OFFSET}"
    url = f"{_MAPILLARY_GRAPH}/images"
    params = {
        "access_token": token,
        "fields": _MAPILLARY_FIELDS,
        "bbox": bbox,
        "limit": limit,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning("Mapillary returned %s: %s", resp.status_code, resp.text[:200])
                return []
            data = resp.json().get("data", [])
    except Exception:
        logger.exception("Mapillary query failed")
        return []

    images: list[StreetImage] = []
    for item in data:
        captured_ms = item.get("captured_at", 0)
        date_str = ""
        if captured_ms:
            date_str = datetime.fromtimestamp(captured_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        geom = item.get("geometry", {}).get("coordinates", [None, None])
        thumb = item.get("thumb_1024_url") or item.get("thumb_original_url", "")
        image_id = item.get("id", "")
        viewer_url = f"https://www.mapillary.com/app/?pKey={image_id}" if image_id else thumb

        images.append(
            StreetImage(
                url=viewer_url,
                thumbnail_url=thumb,
                source="Mapillary",
                date=date_str,
                heading=item.get("compass_angle"),
                lon=geom[0] if geom else None,
                lat=geom[1] if len(geom) > 1 else None,
            )
        )
    return images


# ---------------------------------------------------------------------------
# Google Street View Static API (needs GOOGLE_STREETVIEW_API_KEY)
# ---------------------------------------------------------------------------

_GSV_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
_GSV_HEADINGS = [0, 90, 180, 270]


async def _check_streetview_coverage(lat: float, lon: float) -> bool:
    """Check if Google Street View has coverage at the given coordinates."""
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
            data = resp.json()
            return data.get("status") == "OK"
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
        logger.debug("No Street View coverage at %.5f, %.5f", lat, lon)
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
    sv_url = f"https://www.google.com/maps?layer=c&cbll={lat},{lon}"
    return StreetImage(
        url=sv_url,
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
    """Try each imagery source in order of preference.

    When a Google Street View API key is configured, actual Street View images
    are fetched (served via proxy to hide the key). Otherwise falls back to a
    clickable link.
    """
    all_images: list[StreetImage] = []

    gsv = await _google_streetview_images(lat, lon)
    all_images.extend(gsv)

    mapillary = await _mapillary_images(lat, lon)
    all_images.extend(mapillary)

    wiki = await _wikimedia_images(lat, lon)
    all_images.extend(wiki)

    if not gsv:
        all_images.append(_google_maps_sv_link(lat, lon))

    if not all_images:
        logger.info("No street images found for %.5f, %.5f", lat, lon)

    return all_images
