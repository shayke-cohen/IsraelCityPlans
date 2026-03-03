"""Street-level imagery service.

Layered free sources:
  1. Mapillary (primary, completely free, needs client token)
  2. Google Street View Static API (fallback, 10K free/month, needs API key)
     - metadata check is unlimited & free
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
# Mapillary
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

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.warning("Mapillary returned %s: %s", resp.status_code, resp.text[:200])
            return []
        data = resp.json().get("data", [])

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
# Google Street View Static API
# ---------------------------------------------------------------------------

_GSV_META_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
_GSV_IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"


async def _google_sv_metadata(lat: float, lon: float) -> dict | None:
    """Check whether Google has Street View imagery (free & unlimited)."""
    key = settings.google_streetview_api_key
    if not key:
        return None

    params = {"location": f"{lat},{lon}", "key": key}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_GSV_META_URL, params=params)
        if resp.status_code != 200:
            return None
        meta = resp.json()
    if meta.get("status") != "OK":
        return None
    return meta


async def _google_sv_images(lat: float, lon: float) -> list[StreetImage]:
    key = settings.google_streetview_api_key
    if not key:
        return []

    meta = await _google_sv_metadata(lat, lon)
    if meta is None:
        return []

    date_str = meta.get("date", "")
    images: list[StreetImage] = []
    for heading in (0, 90, 180, 270):
        params = {
            "location": f"{lat},{lon}",
            "size": "640x640",
            "heading": heading,
            "key": key,
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        img_url = f"{_GSV_IMAGE_URL}?{qs}"
        images.append(
            StreetImage(
                url=img_url,
                thumbnail_url=img_url,
                source="Google Street View",
                date=date_str,
                heading=float(heading),
                lat=lat,
                lon=lon,
            )
        )
    return images


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_street_images(lat: float, lon: float) -> list[StreetImage]:
    """Try each imagery source in order, return first non-empty result set."""
    images = await _mapillary_images(lat, lon)
    if images:
        return images

    images = await _google_sv_images(lat, lon)
    if images:
        return images

    logger.info("No street imagery found for %.5f, %.5f", lat, lon)
    return []
