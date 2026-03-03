"""MAVAT parcel-plan adapter.

Resolves parcels (gush/helka) from GovMap WFS, then fetches actual
building-plan data for those parcels from the iplan XPLAN ArcGIS
endpoint using a spatial query scoped to a tight bounding box.

Unlike the original MAVAT fallback adapter (which only returns a link),
this adapter returns real plan names, numbers, statuses, and document
links for any address in Israel.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
from datetime import datetime, timezone

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.coord_utils import wgs84_bbox
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_GOVMAP_WFS = "https://open.govmap.gov.il/geoserver/opendata/wfs"
_XPLAN_QUERY_URL = (
    "https://ags.iplan.gov.il/arcgisiplan/rest/services/"
    "PlanningPublic/Xplan/MapServer/{layer}/query"
)
_PLAN_LAYERS = [1, 0]
_MAX_AREA_DUNAM = 50
_PARCEL_RADIUS_M = 30
_XPLAN_RADIUS_M = 80

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.set_ciphers("DEFAULT@SECLEVEL=1")
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


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


async def _resolve_parcels(
    client: httpx.AsyncClient, lat: float, lon: float,
) -> list[tuple[int, int]]:
    """Get parcel (gush, helka) pairs near the coordinates via GovMap."""
    bbox = wgs84_bbox(lat, lon, radius_m=_PARCEL_RADIUS_M)
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "opendata:PARCEL_ALL",
        "outputFormat": "application/json",
        "count": "5",
        "BBOX": f"{bbox},EPSG:4326",
    }
    try:
        resp = await client.get(_GOVMAP_WFS, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("GovMap parcel lookup failed for mavat_plans adapter")
        return []

    parcels: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        gush = props.get("GUSH_NUM", 0)
        helka = props.get("PARCEL", 0)
        if gush and helka and (gush, helka) not in seen:
            seen.add((gush, helka))
            parcels.append((gush, helka))
    return parcels


async def _query_xplan_layer(
    client: httpx.AsyncClient,
    layer_id: int,
    lat: float,
    lon: float,
) -> list[dict]:
    """Query a single XPLAN layer for features near the point."""
    url = _XPLAN_QUERY_URL.format(layer=layer_id)
    bbox = wgs84_bbox(lat, lon, radius_m=_XPLAN_RADIUS_M)
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
        logger.debug("XPLAN layer %d query failed in mavat_plans", layer_id, exc_info=True)
        return []


@register_adapter
class MAVATPlansAdapter(SourceAdapter):
    """Parcel-aware plan lookup via GovMap parcels + iplan XPLAN."""

    @property
    def name(self) -> str:
        return "mavat_plans"

    @property
    def display_name(self) -> str:
        return 'מבא"ת (תוכניות לפי חלקה)'

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
        plans: list[BuildingPlan] = []
        seen_numbers: set[str] = set()

        async with httpx.AsyncClient(timeout=25, verify=_SSL_CTX) as client:
            parcels_task = asyncio.create_task(
                _resolve_parcels(client, lat, lon)
            )
            xplan_tasks = [
                asyncio.create_task(_query_xplan_layer(client, lid, lat, lon))
                for lid in _PLAN_LAYERS
            ]

            parcels = await parcels_task
            gush_set = {g for g, _ in parcels}

            for task in xplan_tasks:
                features = await task
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

                    plans.append(
                        BuildingPlan(
                            name=plan_name,
                            plan_type=_classify(plan_name),
                            date=_epoch_to_date(attrs.get("last_update_date")),
                            status=status,
                            source=self.display_name,
                            source_url=mavat_link,
                            document_url=mavat_link,
                            embed_type="link",
                            details={
                                "plan_number": plan_number,
                                "mavat_code": attrs.get("mavat_code", ""),
                                "area_dunam": round(area_dunam, 1),
                            },
                        )
                    )

        if parcels and not plans:
            gush, helka = parcels[0]
            fallback_url = (
                f"https://www.govmap.gov.il/?lay=XPLAN"
                f"&q=%D7%92%D7%95%D7%A9+{gush}+%D7%97%D7%9C%D7%A7%D7%94+{helka}"
            )
            plans.append(
                BuildingPlan(
                    name=f'חיפוש תוכניות – גוש {gush} חלקה {helka}',
                    plan_type=PlanType.OTHER,
                    status="קישור לחיפוש ידני",
                    source=self.display_name,
                    source_url=fallback_url,
                    document_url=fallback_url,
                    embed_type="link",
                    details={
                        "gush": gush,
                        "parcel": helka,
                        "is_fallback": True,
                    },
                )
            )
        elif not parcels:
            fallback_url = (
                f"https://www.govmap.gov.il/?c={lon},{lat}&z=17&lay=XPLAN"
            )
            plans.append(
                BuildingPlan(
                    name='חיפוש תוכניות (GovMap)',
                    plan_type=PlanType.OTHER,
                    status="קישור לחיפוש ידני",
                    source=self.display_name,
                    source_url=fallback_url,
                    document_url=fallback_url,
                    embed_type="link",
                    details={"is_fallback": True},
                )
            )

        plans.sort(key=lambda p: p.details.get("area_dunam", 0))
        logger.info(
            "mavat_plans returned %d results (%d parcels) for %s",
            len(plans), len(parcels), address,
        )
        return plans
