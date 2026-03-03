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
_MAX_RESULTS = 15


def _relevance_score(
    plan: BuildingPlan,
    street_words: list[str],
    house_number: str,
) -> float:
    """Score a plan's relevance to a specific address (higher = better)."""
    if plan.details.get("is_fallback"):
        return -10.0

    score = 0.0

    if plan.details.get("tik_binyan"):
        score += 5
    if plan.details.get("pdf_count", 0) > 0:
        score += 5
    if plan.details.get("address_match"):
        score += 4

    name = plan.name

    if house_number and house_number in name:
        score += 3
    if street_words and any(w in name for w in street_words):
        score += 2

    distance = plan.details.get("distance_m")
    if isinstance(distance, (int, float)):
        if distance <= 50:
            score += 4
        elif distance <= 100:
            score += 3
        elif distance <= 200:
            score += 2

    area = plan.details.get("area_dunam", 0)
    if isinstance(area, (int, float)) and area > 0:
        if area <= 5:
            score += 3
        elif area <= 50:
            score += 2
        elif area <= 200:
            score += 1

    if plan.status == "בתוקף":
        score += 1
    elif plan.status in ("הפקדה", "אישור"):
        score += 0.5

    return score


def _rank_and_cap(
    plans: list[BuildingPlan],
    street: str,
    house_number: str,
) -> list[BuildingPlan]:
    """Score, sort, and cap plans to the most relevant ones."""
    words = [w for w in street.split() if w not in _STREET_PREFIXES and len(w) > 1] if street else []

    scored = [
        (_relevance_score(p, words, house_number), idx, p)
        for idx, p in enumerate(plans)
    ]
    scored.sort(key=lambda t: (-t[0], t[1]))

    result = [p for _, _, p in scored[:_MAX_RESULTS]]
    return result


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

        if plans:
            plans = _rank_and_cap(plans, geo.street, geo.house_number)

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
