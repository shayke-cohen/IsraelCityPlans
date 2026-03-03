"""XPLAN national building plans adapter.

Queries the Israel Planning Administration's ArcGIS endpoint at
``ags.iplan.gov.il`` for approved building plans (Layer 1 = "קוים כחולים").
Works for any address in Israel, not just Tel Aviv.
"""
from __future__ import annotations

import logging
import ssl
from datetime import datetime, timezone

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_XPLAN_QUERY_URL = (
    "https://ags.iplan.gov.il/arcgisiplan/rest/services/"
    "PlanningPublic/Xplan/MapServer/{layer}/query"
)
_PLAN_LAYERS = [1, 0]

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


def _mavat_url(pl_number: str) -> str:
    if not pl_number:
        return ""
    return f"https://mavat.iplan.gov.il/SV4/1/{pl_number}"


def _mavat_docs_url(pl_number: str) -> str:
    """Link to the MAVAT documents tab for this plan."""
    if not pl_number:
        return ""
    return f"https://mavat.iplan.gov.il/SV4/1/{pl_number}#documents"


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

        for layer_id in _PLAN_LAYERS:
            url = _XPLAN_QUERY_URL.format(layer=layer_id)
            params = {
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "false",
                "f": "json",
            }

            try:
                async with httpx.AsyncClient(timeout=20, verify=_SSL_CTX) as client:
                    resp = await client.get(url, params=params, follow_redirects=True)
                    resp.raise_for_status()
                    data = resp.json()
            except Exception:
                logger.exception("XPLAN layer %d query failed", layer_id)
                continue

            for feature in data.get("features", []):
                attrs = feature.get("attributes", {})
                plan_name = (attrs.get("pl_name") or "").strip()
                plan_number = (attrs.get("pl_number") or "").strip()
                if not plan_name or plan_number in seen_numbers:
                    continue
                seen_numbers.add(plan_number)

                status = (attrs.get("station_desc") or "").strip()
                mavat_link = _mavat_url(plan_number)

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
                        },
                    )
                )

        logger.info("XPLAN returned %d plans for %s", len(all_plans), address)
        return all_plans
