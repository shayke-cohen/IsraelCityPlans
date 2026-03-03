"""SearchOrchestrator -- shared core logic used by both CLI and Web.

Pipeline:
  1. Check cache
  2. Geocode address (Nominatim)
  3. In parallel: find plans (source registry) + fetch street images
  4. Assemble SearchResult, cache it, return
"""
from __future__ import annotations

import asyncio
import logging

import app.services.adapters  # noqa: F401  — trigger adapter registration

from app.config import settings
from app.db import CacheDB
from app.models.schemas import BuildingPlan, SearchResult
from app.services import geocoder, street_imagery
from app.services.source_registry import CitySourceRegistry

logger = logging.getLogger(__name__)


_STREET_PREFIXES = {"רחוב", "שדרות", "דרך", "סמטת", "שד'"}


def _filter_plans_by_address(
    plans: list[BuildingPlan],
    street: str,
    house_number: str,
) -> list[BuildingPlan]:
    """Keep only plans whose name mentions the searched street."""
    if not street:
        return plans

    words = [w for w in street.split() if w not in _STREET_PREFIXES and len(w) > 1]
    if not words:
        return plans

    matched = [p for p in plans if any(w in p.name for w in words)]

    # Fallback: if no plan name mentions the street, return all
    # so the user still sees something rather than empty results.
    return matched if matched else plans


class SearchOrchestrator:
    def __init__(self) -> None:
        self.registry = CitySourceRegistry(settings.sources_json_path)
        self.cache = CacheDB()

    async def startup(self) -> None:
        await self.cache.connect()

    async def shutdown(self) -> None:
        await self.cache.close()

    async def search(
        self,
        address: str,
        *,
        plans_only: bool = False,
        images_only: bool = False,
    ) -> SearchResult:
        # 1. Cache check
        cached = await self.cache.get_search(address)
        if cached is not None:
            logger.info("Cache hit for %r", address)
            return cached

        # 2. Geocode
        geo = await geocoder.geocode(address)
        if geo is None:
            return SearchResult(address=address, error="הכתובת לא נמצאה")

        # 3. Parallel: plans + images
        plans_task = None
        images_task = None

        if not images_only:
            plans_task = asyncio.create_task(
                self.registry.find_plans(
                    geo.city,
                    address,
                    geo.lat,
                    geo.lon,
                    street=geo.street,
                    house_number=geo.house_number,
                )
            )
        if not plans_only:
            images_task = asyncio.create_task(
                street_imagery.get_street_images(geo.lat, geo.lon)
            )

        plans, sources_tried = [], []
        if plans_task:
            plans, sources_tried = await plans_task

        if plans and geo.street:
            plans = _filter_plans_by_address(plans, geo.street, geo.house_number)

        images = []
        if images_task:
            images = await images_task

        # 4. Assemble
        result = SearchResult(
            address=address,
            geocode=geo,
            plans=plans,
            images=images,
            sources_tried=sources_tried,
        )

        # 5. Cache
        await self.cache.set_search(address, result)
        return result
