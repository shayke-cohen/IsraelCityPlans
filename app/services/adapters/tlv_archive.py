"""Tel Aviv building plans adapter.

Uses the free Tel Aviv GIS open-data SOAP/REST service at
``gisn.tel-aviv.gov.il/gisopendata/service.asmx``.

Layer 528 = תוכניות בניין עיר (City Building Plans / TBW).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_GIS_URL = "https://gisn.tel-aviv.gov.il/gisopendata/service.asmx/GetLayersFromGeo"
_LAYER_PLANS = "528"
_SEARCH_RADIUS = "50"

_STATUS_PRIORITY = {
    "בתוקף": 0,
    "הפקדה": 1,
    "אישור תוכנית מתאר ארצית": 2,
    "אישור תוכנית עיצוב בינוי מקומית": 3,
    "הערות והשגות": 4,
    'החלטה על הכנת תוכנית תמ"א': 5,
}


def _classify_plan(name: str, attrs: dict) -> PlanType:
    sug = attrs.get("sug_nose", "")
    name_lower = name
    if "היתר" in name_lower or "היתר" in sug:
        return PlanType.PERMIT
    if "תעודת גמר" in name_lower or "גמר" in name_lower:
        return PlanType.COMPLETION
    if 'תב"ע' in sug or 'תב"ע' in name_lower or "תכנית" in name_lower:
        return PlanType.PLAN
    return PlanType.OTHER


def _epoch_to_date(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d/%m/%Y")
    except (OSError, ValueError):
        return ""


def _detect_embed_type(url: str) -> str:
    if not url:
        return "link"
    low = url.lower()
    if low.endswith(".pdf"):
        return "pdf"
    if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff")):
        return "image"
    if "gisn.tel-aviv.gov.il" in low or "handasa.tel-aviv.gov.il" in low:
        return "iframe"
    return "iframe"


@register_adapter
class TLVArchiveAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "tlv_archive"

    @property
    def display_name(self) -> str:
        return 'ארכיון הנדסה ת"א'

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
        params = {
            "layerCodes": _LAYER_PLANS,
            "radiuses": _SEARCH_RADIUS,
            "longitude": str(lon),
            "latitude": str(lat),
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(_GIS_URL, params=params)
                resp.raise_for_status()
                layers = resp.json()
        except Exception:
            logger.exception("TLV GIS query failed")
            return []

        plans: list[BuildingPlan] = []
        for layer in layers:
            if layer.get("layer") != _LAYER_PLANS:
                continue
            for entry in layer.get("data", []):
                attrs = entry.get("attributes", {})
                name = (attrs.get("shem_taba") or "").strip()
                if not name:
                    continue

                status = (attrs.get("t_status") or "").strip()
                if status in ("תכנית מבוטלת", "תכנית גנוזה", "תכנית הסטורית/ללא זכויות נוכחיות"):
                    continue

                doc_url = attrs.get("url_documents", "")
                plan = BuildingPlan(
                    name=name,
                    plan_type=_classify_plan(name, attrs),
                    date=_epoch_to_date(attrs.get("tr_matan_tokef")),
                    status=status,
                    source=self.display_name,
                    source_url=doc_url,
                    document_url=doc_url,
                    embed_type=_detect_embed_type(doc_url),
                    details={
                        "taba_id": attrs.get("id_taba"),
                        "taba_number": (attrs.get("taba") or "").strip(),
                        "scope": attrs.get("t_hekef", ""),
                        "classification": attrs.get("t_sivug", ""),
                        "mavat_number": attrs.get("mispar_tochnit_mavat", ""),
                    },
                )
                plans.append(plan)

        plans.sort(key=lambda p: _STATUS_PRIORITY.get(p.status, 99))
        logger.info("TLV archive returned %d plans (filtered) for %s", len(plans), address)
        return plans
