"""Meirim open-data building plans adapter.

Queries the Meirim (meirim.org) REST API which indexes Israeli building
plans by **centroid**, returning them sorted by distance from a given point.
This gives much better address-level relevance than polygon-intersection
approaches used by GovMap / TLV GIS.

Plans that mention the searched street + house number in their name,
goals, or details are tagged ``address_match: true`` and allowed a
wider distance radius.  Plans without an address match are capped at a
tighter radius.

API: ``GET https://api.meirim.org/api/plan?distancePoint={lon},{lat}``
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_API_URL = "https://api.meirim.org/api/plan"
_MAX_DISTANCE_MATCH = 200
_MAX_DISTANCE_NO_MATCH = 150
_MAX_AREA_DUNAM = 50
_PAGE_SIZE = 25

_STREET_PREFIXES = ("רחוב ", "שדרות ", "דרך ", "סמטת ", "שד' ")


def _classify(name: str) -> PlanType:
    if "היתר" in name:
        return PlanType.PERMIT
    if "תעודת גמר" in name or "גמר" in name:
        return PlanType.COMPLETION
    return PlanType.PLAN


def _text_mentions_address(text: str, street: str, house_number: str) -> bool:
    """Check whether *text* mentions the street (and optionally house number)."""
    if not text or not street:
        return False
    street_clean = street.strip()
    for prefix in _STREET_PREFIXES:
        street_clean = street_clean.removeprefix(prefix)
    if len(street_clean) < 2:
        return False
    if street_clean not in text:
        return False
    if house_number:
        num = re.sub(r"[^\d]", "", house_number)
        if num and re.search(rf"(?<!\d){re.escape(num)}(?!\d)", text):
            return True
        return bool(not num)
    return True


def _format_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return ""


def _extract_mavat_url(plan: dict) -> str:
    data = plan.get("data") or {}
    url = (
        data.get("plan_new_mavat_url")
        or data.get("PL_URL")
        or ""
    )
    if url and isinstance(url, str):
        return url
    plan_id = plan.get("id")
    if plan_id:
        return f"https://www.meirim.org/plan/{plan_id}"
    return ""


def _extract_area(plan: dict) -> float:
    data = plan.get("data") or {}
    for key in ("PL_AREA_DUNAM", "SHAPE_AREA"):
        val = data.get(key)
        if val is not None:
            try:
                area = float(val)
                if key == "SHAPE_AREA":
                    area /= 1000.0
                return area
            except (TypeError, ValueError):
                continue
    return 0.0


@register_adapter
class MeirimAdapter(SourceAdapter):
    """National plan search via Meirim open-data API, sorted by proximity."""

    @property
    def name(self) -> str:
        return "meirim"

    @property
    def display_name(self) -> str:
        return "מעירים (תוכניות קרובות)"

    async def search(
        self,
        address: str,
        lat: float,
        lon: float,
        *,
        city: str = "",
        street: str = "",
        house_number: str = "",
    ) -> list[BuildingPlan]:
        params = {"distancePoint": f"{lon},{lat}"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(_API_URL, params=params)
                resp.raise_for_status()
                body = resp.json()
        except Exception:
            logger.exception("Meirim API query failed")
            return []

        raw_plans = body.get("data", [])
        if not raw_plans:
            return []

        plans: list[BuildingPlan] = []
        for entry in raw_plans[:_PAGE_SIZE]:
            distance = entry.get("distance", 9999)
            if distance > _MAX_DISTANCE_MATCH:
                break

            area_dunam = _extract_area(entry)
            if area_dunam > _MAX_AREA_DUNAM and area_dunam > 0:
                continue

            display_name = (
                entry.get("plan_display_name")
                or entry.get("PL_NAME")
                or ""
            ).strip()
            if not display_name:
                continue

            pl_number = entry.get("PL_NUMBER", "")
            mavat_url = _extract_mavat_url(entry)
            status = entry.get("status") or ""
            goals = entry.get("goals_from_mavat") or ""
            main_details = entry.get("main_details_from_mavat") or ""

            searchable = f"{display_name} {goals} {main_details}"
            addr_match = _text_mentions_address(searchable, street, house_number)

            if not addr_match and distance > _MAX_DISTANCE_NO_MATCH:
                continue

            goals_clean = goals.replace("<br>", "\n").replace("\r\n", "\n").strip()
            if len(goals_clean) > 300:
                goals_clean = goals_clean[:297] + "..."

            data = entry.get("data") or {}
            updated = _format_date(
                entry.get("updated_at")
                or data.get("PL_DATE_8")
            )

            plans.append(
                BuildingPlan(
                    name=display_name,
                    plan_type=_classify(display_name),
                    date=updated,
                    status=status,
                    source=self.display_name,
                    source_url=mavat_url,
                    document_url=mavat_url,
                    embed_type="link",
                    details={
                        "plan_number": pl_number,
                        "area_dunam": round(area_dunam, 1) if area_dunam else 0,
                        "distance_m": round(distance),
                        "address_match": addr_match,
                        "goals": goals_clean,
                        "land_use": data.get("PL_LANDUSE_STRING", ""),
                        "entity_type": data.get("ENTITY_SUBTYPE_DESC", ""),
                        "housing_units_delta": data.get("QUANTITY_DELTA_120", 0),
                    },
                )
            )

        logger.info(
            "Meirim returned %d plans (addr_match=%d) within %d/%dm for %s",
            len(plans),
            sum(1 for p in plans if p.details.get("address_match")),
            _MAX_DISTANCE_NO_MATCH, _MAX_DISTANCE_MATCH, address,
        )
        return plans
