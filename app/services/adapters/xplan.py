"""XPLAN national building plans adapter.

Queries the Israel Planning Administration's ArcGIS endpoint at
``ags.iplan.gov.il`` for approved building plans (Layer 1 = "קוים כחולים",
Layer 0 = plans).

Improvements over the original:
- Queries layers in parallel for faster response
- Tighter area filter (50 dunam instead of 100)
- Street name matching on plan names boosts relevance
- Uses a tight bounding box envelope instead of point-in-polygon
  (more tolerant of EPSG issues and faster)
"""
from __future__ import annotations

import asyncio
import logging
import re
import ssl
from datetime import datetime, timezone

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.coord_utils import wgs84_bbox
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_XPLAN_QUERY_URL = (
    "https://ags.iplan.gov.il/arcgisiplan/rest/services/"
    "PlanningPublic/Xplan/MapServer/{layer}/query"
)
_PLAN_LAYERS = [1, 0]
_MAX_AREA_DUNAM = 50
_BBOX_RADIUS_M = 60

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.set_ciphers("DEFAULT@SECLEVEL=1")
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_STREET_PREFIXES = ("רחוב ", "שדרות ", "דרך ", "סמטת ", "שד' ")


def _epoch_to_date(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d/%m/%Y")
    except (OSError, ValueError):
        return ""


def _classify(name: str) -> PlanType:
    if "היתר" in name:
        return PlanType.PERMIT
    if "תעודת גמר" in name or "גמר" in name:
        return PlanType.COMPLETION
    return PlanType.PLAN


def _mavat_url(attrs: dict) -> str:
    """Build a working MAVAT URL from XPLAN attributes.

    Priority: pl_url (from API) > mp_id-based > pl_number fallback.
    """
    pl_url = (attrs.get("pl_url") or "").strip()
    if pl_url and pl_url.startswith("http"):
        return pl_url
    mp_id = attrs.get("mp_id")
    if mp_id and str(mp_id).replace(".", "").replace("0", ""):
        return f"https://mavat.iplan.gov.il/SV4/1/{int(float(mp_id))}/310"
    pl_number = (attrs.get("pl_number") or "").strip()
    if pl_number:
        return f"https://mavat.iplan.gov.il/SV4/1/{pl_number}"
    return ""


def _street_matches(plan_name: str, street: str) -> bool:
    """Check if the plan name contains the street name."""
    if not street or not plan_name:
        return False
    street_clean = street.strip()
    for prefix in _STREET_PREFIXES:
        street_clean = street_clean.removeprefix(prefix)
    return len(street_clean) >= 2 and street_clean in plan_name


async def _query_layer(
    client: httpx.AsyncClient,
    layer_id: int,
    lat: float,
    lon: float,
) -> list[dict]:
    url = _XPLAN_QUERY_URL.format(layer=layer_id)
    bbox = wgs84_bbox(lat, lon, radius_m=_BBOX_RADIUS_M)
    min_lon, min_lat, max_lon, max_lat = bbox.split(",")
    params = {
        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        resp = await client.get(url, params=params, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        return data.get("features", [])
    except Exception:
        logger.exception("XPLAN layer %d query failed", layer_id)
        return []


@register_adapter
class XPLANAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "xplan"

    @property
    def display_name(self) -> str:
        return "XPLAN (תכניות ארציות)"

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
        all_plans: list[BuildingPlan] = []
        seen_numbers: set[str] = set()

        async with httpx.AsyncClient(timeout=25, verify=_SSL_CTX) as client:
            tasks = [
                asyncio.create_task(_query_layer(client, lid, lat, lon))
                for lid in _PLAN_LAYERS
            ]
            results = await asyncio.gather(*tasks)

        for features in results:
            for feature in features:
                attrs = feature.get("attributes", {})
                plan_name = (attrs.get("pl_name") or "").strip()
                plan_number = (attrs.get("pl_number") or "").strip()
                if not plan_name or plan_number in seen_numbers:
                    continue

                area_dunam = 0.0
                try:
                    area_dunam = float(attrs.get("pl_area_dunam") or 0)
                except (TypeError, ValueError):
                    pass
                if area_dunam > _MAX_AREA_DUNAM:
                    continue

                seen_numbers.add(plan_number)
                status = (attrs.get("station_desc") or "").strip()
                mavat_link = _mavat_url(attrs)
                street_match = _street_matches(plan_name, street)

                all_plans.append(
                    BuildingPlan(
                        name=plan_name,
                        plan_type=_classify(plan_name),
                        date=_epoch_to_date(attrs.get("last_update_date")),
                        status=status,
                        source=self.display_name,
                        source_url=mavat_link,
                        document_url=mavat_link,
                        embed_type="iframe",
                        details={
                            "plan_number": plan_number,
                            "mavat_code": attrs.get("mavat_code", ""),
                            "area_dunam": round(area_dunam, 1),
                            "address_match": street_match,
                        },
                    )
                )

        all_plans.sort(
            key=lambda p: (
                0 if p.details.get("address_match") else 1,
                p.details.get("area_dunam", 0),
            )
        )
        logger.info(
            "XPLAN returned %d plans (street_match=%d, area < %d dunam) for %s",
            len(all_plans),
            sum(1 for p in all_plans if p.details.get("address_match")),
            _MAX_AREA_DUNAM,
            address,
        )
        return all_plans
