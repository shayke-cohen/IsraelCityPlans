"""Tel Aviv engineering archive & building permits adapter.

Searches for the **exact address** in two ways:

1. **Engineering archive** (``handasa.tel-aviv.gov.il``):
   Resolves street name → street code via TLV GIS ``GetStreets``,
   constructs a building-file ID (``tik binyan``), then fetches the
   archive page to discover downloadable PDF construction documents.

2. **Building permits** (TLV GIS layer 772 = בקשות והיתרי בניה):
   Queries by coordinates and filters on the ``addresses`` attribute
   so only permits mentioning the searched street + house number are
   returned.

This adapter is Tel-Aviv-specific and should be placed **first** in the
Tel Aviv source chain.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_GIS_URL = "https://gisn.tel-aviv.gov.il/GisOpenData/service.asmx"
_STREETS_URL = f"{_GIS_URL}/GetStreets"
_LAYERS_GEO_URL = f"{_GIS_URL}/GetLayersFromGeo"
_ARCHIVE_URL = "https://handasa.tel-aviv.gov.il/Pages/searchResultsAnonPageNew.aspx"
_LAYER_PERMITS = "772"
_PERMIT_RADIUS = "150"
_MAX_ARCHIVE_PDFS = 5

_streets_cache: dict[str, str] | None = None


async def _get_street_codes(client: httpx.AsyncClient) -> dict[str, str]:
    """Return ``{street_name: street_code}`` from the TLV GIS streets API."""
    global _streets_cache
    if _streets_cache is not None:
        return _streets_cache

    try:
        resp = await client.get(_STREETS_URL, timeout=10)
        resp.raise_for_status()
        raw: dict = resp.json()
        _streets_cache = {v: k for k, v in raw.items()}
        logger.info("Cached %d TLV street codes", len(_streets_cache))
        return _streets_cache
    except Exception:
        logger.exception("Failed to fetch TLV street codes")
        return {}


def _build_tik(street_code: str, house_number: str) -> str:
    """Construct a building-file ID (tik binyan) from street code + house number.

    Pattern: ``{street_code}{house_num:03d}{entrance}``
    e.g. Kisufim (877) house 18 → ``8770180``  (877 + 018 + 0)
         Kisufim (877) house 32 → ``8770320``  (877 + 032 + 0)
    Entrance defaults to 0 (no entrance letter).
    """
    num = re.sub(r"[^\d]", "", house_number)
    if not num:
        return ""
    return f"{street_code}{int(num):03d}0"


def _epoch_to_date(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d/%m/%Y")
    except (OSError, ValueError):
        return ""


def _archive_page_url(tik: str) -> str:
    padded = tik.zfill(8)
    return f"{_ARCHIVE_URL}?folderId={padded}"


def _address_matches(addresses_field: str, street: str, house_number: str) -> bool:
    """Check if the permit addresses field contains the searched address.

    Uses word-boundary matching for the house number to avoid "1" matching "10".
    """
    if not addresses_field or not street:
        return False
    street_clean = street.strip()
    for prefix in ("רחוב ", "שדרות ", "דרך ", "סמטת ", "שד' "):
        street_clean = street_clean.removeprefix(prefix)
    if street_clean not in addresses_field:
        return False
    if house_number:
        num = re.sub(r"[^\d]", "", house_number)
        if not num:
            return True
        parts = [p.strip() for p in addresses_field.split(",")]
        for part in parts:
            if street_clean not in part:
                continue
            if re.search(rf"(?<!\d){re.escape(num)}(?!\d)", part):
                return True
        return False
    return True


async def _fetch_archive_pdfs(
    client: httpx.AsyncClient, tik: str,
) -> tuple[str, list[str]]:
    """Fetch the archive page and return (page_url, [pdf_urls])."""
    page_url = _archive_page_url(tik)
    try:
        resp = await client.get(page_url, follow_redirects=True, timeout=12)
        if resp.status_code != 200:
            return page_url, []
        pdf_urls = re.findall(
            r'href="(https://handasa\.tel-aviv\.gov\.il/sc9/[^"]+\.pdf)"',
            resp.text,
        )
        return page_url, pdf_urls
    except Exception:
        logger.debug("Archive fetch failed for tik=%s", tik, exc_info=True)
        return page_url, []


async def fetch_archive_documents(tik: str) -> dict:
    """Public helper: fetch archive document list for a given tik.

    Returns ``{"page_url": str, "tik": str, "documents": [{"id": str, "url": str}]}``.
    """
    padded = tik.zfill(8)
    page_url = _archive_page_url(padded)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        _, pdf_urls = await _fetch_archive_pdfs(client, padded)
    docs = []
    for url in pdf_urls:
        doc_id = url.rsplit("/", 1)[-1].replace(".pdf", "")
        docs.append({"id": doc_id, "url": url})
    return {"page_url": page_url, "tik": padded, "documents": docs}


@register_adapter
class TLVEngineeringAdapter(SourceAdapter):
    """Tel Aviv engineering archive + building permits by exact address."""

    @property
    def name(self) -> str:
        return "tlv_engineering"

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
        plans: list[BuildingPlan] = []

        async with httpx.AsyncClient(timeout=20) as client:
            # --- 1. Engineering archive by exact address ---
            tik = ""
            if street and house_number:
                streets = await _get_street_codes(client)
                street_clean = street.strip()
                for prefix in ("רחוב ", "שדרות ", "דרך ", "סמטת ", "שד' "):
                    street_clean = street_clean.removeprefix(prefix)

                code = streets.get(street_clean, "")
                if not code:
                    for name, c in streets.items():
                        if street_clean in name or name in street_clean:
                            code = c
                            break

                if code:
                    tik = _build_tik(code, house_number)
                    if tik:
                        page_url, pdf_urls = await _fetch_archive_pdfs(client, tik)
                        pdf_count = len(pdf_urls)
                        status = f"{pdf_count} מסמכים בארכיון" if pdf_count else "חיפוש בארכיון"
                        plans.append(
                            BuildingPlan(
                                name=f"תיק בניין – {street} {house_number}",
                                plan_type=PlanType.PLAN,
                                status=status,
                                source=self.display_name,
                                source_url=page_url,
                                document_url=page_url,
                                embed_type="archive",
                                details={
                                    "tik_binyan": tik,
                                    "pdf_count": pdf_count,
                                    "archive_url": page_url,
                                },
                            )
                        )
                        logger.info(
                            "TLV archive tik=%s: %d PDFs for %s %s",
                            tik, pdf_count, street, house_number,
                        )

            # --- 2. Building permits (layer 772) by address match ---
            try:
                resp = await client.get(
                    _LAYERS_GEO_URL,
                    params={
                        "layerCodes": _LAYER_PERMITS,
                        "radiuses": _PERMIT_RADIUS,
                        "longitude": str(lon),
                        "latitude": str(lat),
                    },
                )
                resp.raise_for_status()
                layers = resp.json()
            except Exception:
                logger.exception("TLV permits query failed")
                layers = []

            for layer in layers:
                if layer.get("layer") != _LAYER_PERMITS:
                    continue
                for entry in layer.get("data", []):
                    attrs = entry.get("attributes", {})
                    addrs = attrs.get("addresses", "")
                    if not _address_matches(addrs, street, house_number):
                        continue

                    sug = attrs.get("sug_bakasha", "")
                    koteret = attrs.get("koteret", "")
                    content = (attrs.get("tochen_bakasha") or "")[:200]
                    bldg_tik = str(attrs.get("ms_tik_binyan") or "")
                    stage = attrs.get("building_stage", "")
                    hadmaya_url = attrs.get("url_hadmaya", "") or ""

                    archive_url = ""
                    if bldg_tik and bldg_tik != "0":
                        archive_url = _archive_page_url(bldg_tik)

                    doc_url = hadmaya_url or archive_url

                    plans.append(
                        BuildingPlan(
                            name=f"{koteret} – {addrs}" if koteret else addrs,
                            plan_type=PlanType.PERMIT,
                            date=_epoch_to_date(attrs.get("permission_date")),
                            status=stage,
                            source=self.display_name,
                            source_url=doc_url,
                            document_url=doc_url,
                            embed_type="link",
                            details={
                                "request_num": attrs.get("request_num"),
                                "permit_num": attrs.get("permission_num"),
                                "tik_binyan": bldg_tik,
                                "request_type": sug,
                                "description": content,
                                "tama38": attrs.get("sw_tama_38", ""),
                                "housing_units": attrs.get("yechidot_diyur", 0),
                            },
                        )
                    )

        logger.info(
            "TLV engineering returned %d results for %s",
            len(plans), address,
        )
        return plans
