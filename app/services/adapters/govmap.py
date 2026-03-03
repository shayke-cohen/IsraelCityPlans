"""GovMap national parcel & cadastral data adapter.

Queries the Israel Survey's open WFS endpoint at
``open.govmap.gov.il/geoserver/opendata/wfs`` for cadastral parcel
boundaries (PARCEL_ALL layer).  Works for **every** Israeli address.

Returns parcel identification data (gush/helka, legal area, status)
which links directly to MAVAT plan documents for that parcel.
"""
from __future__ import annotations

import logging

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.coord_utils import wgs84_bbox
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_WFS_URL = "https://open.govmap.gov.il/geoserver/opendata/wfs"
_LAYER = "opendata:PARCEL_ALL"
_MAX_FEATURES = 20
_SEARCH_RADIUS_M = 50


def _mavat_parcel_url(gush: int, parcel: int) -> str:
    """Link to MAVAT plans-by-parcel search."""
    if not gush or not parcel:
        return ""
    return (
        f"https://mavat.iplan.gov.il/SV4/1?gush={gush}&parcel={parcel}"
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
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": _LAYER,
            "outputFormat": "application/json",
            "count": str(_MAX_FEATURES),
            "BBOX": f"{bbox},EPSG:4326",
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(_WFS_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("GovMap WFS query failed")
            return []

        plans: list[BuildingPlan] = []
        seen: set[str] = set()
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            gush = props.get("GUSH_NUM", 0)
            parcel = props.get("PARCEL", 0)
            pid = f"{gush}-{parcel}"
            if pid in seen:
                continue
            seen.add(pid)

            locality = (props.get("LOCALITY_N") or "").strip()
            area = props.get("LEGAL_AREA", 0)
            status = _status_label(props.get("STATUS", 0), (props.get("STATUS_TEX") or "").strip())
            mavat_url = _mavat_parcel_url(gush, parcel)

            plans.append(
                BuildingPlan(
                    name=f"גוש {gush} חלקה {parcel}" + (f" – {locality}" if locality else ""),
                    plan_type=PlanType.OTHER,
                    status=status,
                    source=self.display_name,
                    source_url=mavat_url,
                    document_url=mavat_url,
                    embed_type="iframe" if mavat_url else "link",
                    details={
                        "gush": gush,
                        "parcel": parcel,
                        "locality": locality,
                        "legal_area_sqm": area,
                        "county": (props.get("COUNTY_NAM") or "").strip(),
                        "region": (props.get("REGION_NAM") or "").strip(),
                    },
                )
            )

        logger.info("GovMap returned %d parcels for %s", len(plans), address)
        return plans
