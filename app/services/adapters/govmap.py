"""GovMap national parcel & cadastral data adapter.

Queries the Israel Survey's open WFS endpoint at
``open.govmap.gov.il/geoserver/opendata/wfs`` for cadastral parcel
boundaries (PARCEL_ALL layer).  Works for **every** Israeli address.

Returns parcel identification data (gush/helka, legal area, status)
which links directly to MAVAT plan documents for that parcel.

The adapter queries both PARCEL_ALL (parcels) and SUB_GUSH_ALL (gush
boundaries) to provide complete cadastral context.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.coord_utils import wgs84_bbox
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_WFS_URL = "https://open.govmap.gov.il/geoserver/opendata/wfs"
_PARCEL_LAYER = "opendata:PARCEL_ALL"
_GUSH_LAYER = "opendata:SUB_GUSH_ALL"
_MAX_PARCELS = 8
_SEARCH_RADIUS_M = 30


def _govmap_parcel_url(gush: int, parcel: int) -> str:
    """Link to GovMap parcel viewer with the parcel highlighted."""
    if not gush or not parcel:
        return ""
    return (
        f"https://www.govmap.gov.il/?lay=PARCEL_ALL&q=%D7%92%D7%95%D7%A9+{gush}+%D7%97%D7%9C%D7%A7%D7%94+{parcel}"
    )


def _status_label(code: int, text: str) -> str:
    if text:
        return text
    return {0: "", 6: "מוסדר", 7: "לא מוסדר"}.get(code, str(code))


@register_adapter
class GovMapAdapter(SourceAdapter):
    """National cadastral parcels via GovMap open WFS."""

    @property
    def name(self) -> str:
        return "govmap"

    @property
    def display_name(self) -> str:
        return "GovMap (חלקות קדסטר)"

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
        bbox = wgs84_bbox(lat, lon, radius_m=_SEARCH_RADIUS_M)
        parcel_params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": _PARCEL_LAYER,
            "outputFormat": "application/json",
            "count": str(_MAX_PARCELS),
            "BBOX": f"{bbox},EPSG:4326",
        }
        gush_params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": _GUSH_LAYER,
            "outputFormat": "application/json",
            "count": "3",
            "BBOX": f"{bbox},EPSG:4326",
        }

        async with httpx.AsyncClient(timeout=20) as client:
            parcel_task = asyncio.create_task(
                self._fetch_wfs(client, parcel_params, "parcels")
            )
            gush_task = asyncio.create_task(
                self._fetch_wfs(client, gush_params, "gushim")
            )
            parcel_data, gush_data = await asyncio.gather(parcel_task, gush_task)

        gush_info: dict[int, dict] = {}
        for feature in gush_data.get("features", []):
            props = feature.get("properties", {})
            gnum = props.get("GUSH_NUM", 0)
            if gnum:
                gush_info[gnum] = {
                    "locality": (props.get("LOCALITY_N") or "").strip(),
                    "county": (props.get("COUNTY_NAM") or "").strip(),
                    "region": (props.get("REGION_NAM") or "").strip(),
                }

        plans: list[BuildingPlan] = []
        seen: set[str] = set()
        for feature in parcel_data.get("features", []):
            props = feature.get("properties", {})
            gush = props.get("GUSH_NUM", 0)
            parcel = props.get("PARCEL", 0)
            pid = f"{gush}-{parcel}"
            if pid in seen:
                continue
            seen.add(pid)

            g_info = gush_info.get(gush, {})
            locality = (props.get("LOCALITY_N") or "").strip() or g_info.get("locality", "")
            area = props.get("LEGAL_AREA", 0)
            status = _status_label(props.get("STATUS", 0), (props.get("STATUS_TEX") or "").strip())
            govmap_url = _govmap_parcel_url(gush, parcel)

            plans.append(
                BuildingPlan(
                    name=f"גוש {gush} חלקה {parcel}" + (f" – {locality}" if locality else ""),
                    plan_type=PlanType.OTHER,
                    status=status,
                    source=self.display_name,
                    source_url=govmap_url,
                    document_url=govmap_url,
                    embed_type="link",
                    details={
                        "gush": gush,
                        "parcel": parcel,
                        "locality": locality,
                        "legal_area_sqm": area,
                        "county": (props.get("COUNTY_NAM") or g_info.get("county", "")).strip(),
                        "region": (props.get("REGION_NAM") or g_info.get("region", "")).strip(),
                    },
                )
            )

        logger.info("GovMap returned %d parcels for %s", len(plans), address)
        return plans

    @staticmethod
    async def _fetch_wfs(
        client: httpx.AsyncClient, params: dict, label: str,
    ) -> dict:
        try:
            resp = await client.get(_WFS_URL, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception("GovMap WFS %s query failed", label)
            return {"features": []}
