"""Tel Aviv building plans adapter.

Uses the free Tel Aviv GIS open-data SOAP/REST service at
``gisn.tel-aviv.gov.il/gisopendata/service.asmx``.

Layer 527 = גושים וחלקות (parcels — gush / helka).
Layer 528 = תוכניות בניין עיר (City Building Plans / TBW).

Plans are filtered by ``ms_shetach_graphi`` (actual polygon area in m²)
to exclude massive city-wide / regional plans that aren't specific to the
queried address.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_GIS_URL = "https://gisn.tel-aviv.gov.il/gisopendata/service.asmx/GetLayersFromGeo"
_LAYER_PARCELS = "527"
_LAYER_PLANS = "528"
_SEARCH_RADIUS = "50"
_MAX_GRAPHIC_AREA_M2 = 50_000  # 5 hectares — anything bigger is area/city-wide

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

    async def _resolve_parcel(
        self, lat: float, lon: float, client: httpx.AsyncClient,
    ) -> tuple[str, str]:
        """Return (gush, helka) from TLV GIS layer 527 for the given point."""
        params = {
            "layerCodes": _LAYER_PARCELS,
            "radiuses": "10",
            "longitude": str(lon),
            "latitude": str(lat),
        }
        try:
            resp = await client.get(_GIS_URL, params=params)
            resp.raise_for_status()
            layers = resp.json()
        except Exception:
            logger.debug("TLV parcel lookup failed", exc_info=True)
            return ("", "")

        for layer in layers:
            if layer.get("layer") != _LAYER_PARCELS:
                continue
            for entry in layer.get("data", []):
                attrs = entry.get("attributes", {})
                gush = str(attrs.get("ms_gush") or "").strip()
                helka = str(attrs.get("ms_chelka") or "").strip()
                if gush:
                    return (gush, helka)
        return ("", "")

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
        async with httpx.AsyncClient(timeout=20) as client:
            gush, helka = await self._resolve_parcel(lat, lon, client)
            if gush:
                logger.info("TLV parcel resolved: gush=%s helka=%s", gush, helka)

            params = {
                "layerCodes": _LAYER_PLANS,
                "radiuses": _SEARCH_RADIUS,
                "longitude": str(lon),
                "latitude": str(lat),
            }

            try:
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

                graphic_area = attrs.get("ms_shetach_graphi") or 0
                try:
                    graphic_area = float(graphic_area)
                except (TypeError, ValueError):
                    graphic_area = 0.0

                if graphic_area <= 0 or graphic_area > _MAX_GRAPHIC_AREA_M2:
                    continue

                area_dunam = graphic_area / 1000.0

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
                        "scope": (attrs.get("t_hekef") or "").strip(),
                        "classification": attrs.get("t_sivug", ""),
                        "mavat_number": attrs.get("mispar_tochnit_mavat", ""),
                        "area_dunam": round(area_dunam, 1),
                        "gush": gush,
                        "helka": helka,
                    },
                )
                plans.append(plan)

        plans.sort(key=lambda p: (
            p.details.get("area_dunam", 9999),
            _STATUS_PRIORITY.get(p.status, 99),
        ))
        logger.info(
            "TLV archive returned %d plans (area < %d m²) for %s",
            len(plans), _MAX_GRAPHIC_AREA_M2, address,
        )
        return plans
