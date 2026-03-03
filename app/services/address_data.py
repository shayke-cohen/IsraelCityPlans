"""Israeli cities and streets data from data.gov.il.

Fetches from the official CKAN open-data API and caches in memory.
Cities (~1,300 records) are cached as a full list.
Streets (~150K total) are cached per city_code on first access.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.gov.il/api/action/datastore_search"
_CITIES_RESOURCE = "b7cf8f14-64a2-4b33-8d4b-edb286fdbd37"
_STREETS_RESOURCE = "bf185c7f-1a4e-4662-88c5-fa118a244bda"
_HEADERS = {"User-Agent": "AmitAddress-POC/0.1"}
_CACHE_TTL = 86_400  # 24 hours


@dataclass
class CityRecord:
    code: int
    name: str
    name_en: str


@dataclass
class StreetRecord:
    code: str
    name: str
    city_code: int


@dataclass
class _CacheEntry:
    data: list
    ts: float = field(default_factory=time.monotonic)

    def expired(self) -> bool:
        return (time.monotonic() - self.ts) > _CACHE_TTL


class AddressDataService:
    """Provides city and street lookups backed by data.gov.il."""

    def __init__(self) -> None:
        self._cities_cache: _CacheEntry | None = None
        self._streets_cache: dict[int, _CacheEntry] = {}

    async def get_cities(self, query: str = "") -> list[CityRecord]:
        cities = await self._fetch_cities()
        if not query:
            return cities
        q = query.strip()
        return [c for c in cities if q in c.name or q.lower() in c.name_en.lower()]

    async def get_streets(self, city_code: int, query: str = "") -> list[StreetRecord]:
        streets = await self._fetch_streets(city_code)
        if not query:
            return streets
        q = query.strip()
        return [s for s in streets if q in s.name]

    async def _fetch_cities(self) -> list[CityRecord]:
        if self._cities_cache and not self._cities_cache.expired():
            return self._cities_cache.data

        logger.info("Fetching cities from data.gov.il")
        records = await self._ckan_fetch_all(_CITIES_RESOURCE, limit=1500)

        cities: list[CityRecord] = []
        for r in records:
            code = r.get("סמל_ישוב")
            name = (r.get("שם_ישוב") or "").strip()
            name_en = (r.get("שם_ישוב_לועזי") or "").strip()
            if code and name:
                cities.append(CityRecord(code=int(code), name=name, name_en=name_en))

        cities.sort(key=lambda c: c.name)
        self._cities_cache = _CacheEntry(data=cities)
        logger.info("Cached %d cities", len(cities))
        return cities

    async def _fetch_streets(self, city_code: int) -> list[StreetRecord]:
        cached = self._streets_cache.get(city_code)
        if cached and not cached.expired():
            return cached.data

        logger.info("Fetching streets for city_code=%d from data.gov.il", city_code)
        records = await self._ckan_fetch_all(
            _STREETS_RESOURCE,
            filters={"city_code": city_code},
            limit=5000,
        )

        streets: list[StreetRecord] = []
        seen: set[str] = set()
        for r in records:
            name = (r.get("street_name") or "").strip()
            code = str(r.get("street_code", "")).strip()
            if name and name not in seen:
                seen.add(name)
                streets.append(StreetRecord(code=code, name=name, city_code=city_code))

        streets.sort(key=lambda s: s.name)
        self._streets_cache[city_code] = _CacheEntry(data=streets)
        logger.info("Cached %d streets for city_code=%d", len(streets), city_code)
        return streets

    @staticmethod
    async def _ckan_fetch_all(
        resource_id: str,
        *,
        filters: dict | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        """Page through the CKAN datastore_search endpoint."""
        all_records: list[dict] = []
        offset = 0

        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            while True:
                params: dict = {
                    "resource_id": resource_id,
                    "limit": limit,
                    "offset": offset,
                }
                if filters:
                    import json
                    params["filters"] = json.dumps(filters)

                resp = await client.get(_BASE_URL, params=params)
                resp.raise_for_status()
                body = resp.json()
                records = body.get("result", {}).get("records", [])
                if not records:
                    break
                all_records.extend(records)
                if len(records) < limit:
                    break
                offset += limit

        return all_records
