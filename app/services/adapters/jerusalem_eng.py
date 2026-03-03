"""Jerusalem engineering / building-plan adapter.

Queries the Jerusalem municipality ArcGIS services at
``gisviewer.jerusalem.muni.il`` for:

- Layer 161 (BaseLayers): תב"ע ממשרד הפנים — plan polygons with TABA
  numbers and status codes
- Layer 1 (Indexer): DIPARCELREG — parcel data (gush/helka)
- Layer 50 (BaseLayers): land-use designations

Returns actual plan numbers that can be linked to MAVAT.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_BASE = "https://gisviewer.jerusalem.muni.il/arcgis/rest/services"
_TABA_URL = f"{_BASE}/BaseLayers/MapServer/161/query"
_LAND_USE_URL = f"{_BASE}/BaseLayers/MapServer/50/query"
_PARCEL_URL = f"{_BASE}/Indexer/MapServer/1/query"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko)"
    ),
}

_STATUS_MAP = {
    "8400010": "הוגשה",
    "8400020": "בדיון",
    "8400030": "מופקדת",
    "8400040": "אושרה",
    "8400050": "בתוקף",
    "8400052": "בתוקף",
    "8400060": "סורבה",
    "8400070": "בוטלה",
    "8400112": "החלטה בדיון בהפקדה",
}


def _status_label(code: str) -> str:
    return _STATUS_MAP.get(code, code or "")


def _mavat_url(taba: str) -> str:
    if not taba:
        return ""
    return f"https://mavat.iplan.gov.il/SV4/1/{taba}"


async def _query(
    client: httpx.AsyncClient, url: str, params: dict, label: str,
) -> list[dict]:
    try:
        resp = await client.get(url, params=params, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        return data.get("features", [])
    except Exception:
        logger.exception("Jerusalem GIS %s query failed", label)
        return []


@register_adapter
class JerusalemEngAdapter(SourceAdapter):
    """Jerusalem municipality building plans via ArcGIS."""

    @property
    def name(self) -> str:
        return "jerusalem_eng"

    @property
    def display_name(self) -> str:
        return "ירושלים (תוכניות בנייה)"

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
        point_params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }

        async with httpx.AsyncClient(
            timeout=20, headers=_HEADERS,
        ) as client:
            taba_task = asyncio.create_task(
                _query(client, _TABA_URL, point_params, "taba")
            )
            parcel_task = asyncio.create_task(
                _query(client, _PARCEL_URL, point_params, "parcels")
            )
            land_use_task = asyncio.create_task(
                _query(client, _LAND_USE_URL, point_params, "land_use")
            )
            taba_features, parcel_features, land_use_features = (
                await asyncio.gather(taba_task, parcel_task, land_use_task)
            )

        gush = ""
        helka = ""
        if parcel_features:
            p = parcel_features[0].get("attributes", {})
            gush = p.get("GUSH_NO", "")
            helka = p.get("PARCEL_NO", "")

        land_use_desc = ""
        if land_use_features:
            lu = land_use_features[0].get("attributes", {})
            land_use_desc = lu.get("Descr", "")

        plans: list[BuildingPlan] = []
        seen: set[str] = set()
        for feature in taba_features:
            attrs = feature.get("attributes", {})
            taba = (attrs.get("TABA") or "").strip()
            if not taba or taba in seen:
                continue
            seen.add(taba)

            status_code = (attrs.get("STATUS") or "").strip()
            status = _status_label(status_code)
            mavat_link = _mavat_url(taba)

            plans.append(
                BuildingPlan(
                    name=f"תוכנית {taba} – ירושלים",
                    plan_type=PlanType.PLAN,
                    status=status,
                    source=self.display_name,
                    source_url=mavat_link,
                    document_url=mavat_link,
                    embed_type="link",
                    details={
                        "plan_number": taba,
                        "taba": taba,
                        "status_code": status_code,
                        "gush": gush,
                        "helka": helka,
                        "land_use": land_use_desc,
                    },
                )
            )

        active_statuses = {"8400040", "8400050", "8400052"}
        plans.sort(
            key=lambda p: (
                0 if p.details.get("status_code") in active_statuses else 1,
                p.details.get("taba", ""),
            )
        )

        logger.info(
            "Jerusalem GIS returned %d plans (gush=%s, helka=%s) for %s",
            len(plans), gush, helka, address,
        )
        return plans
