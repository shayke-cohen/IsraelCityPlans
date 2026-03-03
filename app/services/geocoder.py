"""Geocoding service.

Primary:  Nominatim (OpenStreetMap) -- free, no API key, supports Hebrew.
Results are cached in the SQLite layer so repeated lookups are instant.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.models.schemas import GeocodeResult

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_HEADERS = {"User-Agent": "AmitAddress-POC/0.1 (building-plans-finder)"}


async def geocode(address: str) -> GeocodeResult | None:
    """Geocode a Hebrew Israeli address string.

    Returns *None* when the address cannot be resolved.
    """
    params = {
        "q": address,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 1,
        "countrycodes": "il",
        "accept-language": "he",
    }

    async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
        resp = await client.get(_NOMINATIM_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    if not data:
        logger.warning("Geocode returned no results for %r", address)
        return None

    hit = data[0]
    addr = hit.get("address", {})

    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or ""
    )
    street = addr.get("road", "")
    house_number = addr.get("house_number", "")

    display = hit.get("display_name", address)

    return GeocodeResult(
        lat=float(hit["lat"]),
        lon=float(hit["lon"]),
        city=city,
        street=street,
        house_number=house_number,
        display_name=display,
    )
