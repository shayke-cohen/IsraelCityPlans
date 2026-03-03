"""Haifa open-data zoning adapter.

Uses the Haifa municipality open-data portal (CKAN) CSV export of the
``yeudei_karka`` (ייעודי קרקע) dataset.  The CSV provides per-parcel
zoning designations with direct links to plan documents on the Haifa
engineering department site.

Because the CSV has no coordinates, we first resolve the parcel
(gush/helka) via GovMap WFS, then look up the cached CSV.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from collections import defaultdict

import httpx

from app.models.schemas import BuildingPlan, PlanType
from app.services.coord_utils import wgs84_bbox
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)

_CSV_URL = (
    "https://opendata.haifa.muni.il/dataset/"
    "8fda51da-f8ff-4152-aeae-bf103bb038db/resource/"
    "fa3a6a26-7058-4729-933f-8076a2e31127/download/gis.csv"
)
_GOVMAP_WFS = "https://open.govmap.gov.il/geoserver/opendata/wfs"

_CACHE_TTL = 86_400  # re-download CSV once per day

_ZONING_TO_PLAN_TYPE = {
    "מגורים": PlanType.PLAN,
    "מסחר": PlanType.PLAN,
    "תעשי": PlanType.PLAN,
    "ציבור": PlanType.PLAN,
    "חנייה": PlanType.OTHER,
    "דרך": PlanType.OTHER,
    "שטח": PlanType.OTHER,
}


def _classify_zoning(desc: str) -> PlanType:
    for key, pt in _ZONING_TO_PLAN_TYPE.items():
        if key in desc:
            return pt
    return PlanType.OTHER


class _CSVCache:
    """In-memory cache of the Haifa zoning CSV, keyed by (gush, helka)."""

    def __init__(self) -> None:
        self._data: dict[tuple[int, int], list[dict]] = defaultdict(list)
        self._loaded_at: float = 0

    @property
    def stale(self) -> bool:
        return time.time() - self._loaded_at > _CACHE_TTL

    async def ensure_loaded(self) -> bool:
        if self._data and not self.stale:
            return True
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(_CSV_URL)
                resp.raise_for_status()
                text = resp.text
        except Exception:
            logger.exception("Failed to download Haifa zoning CSV")
            return bool(self._data)

        self._data.clear()
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                gush = int(row.get("Gush") or 0)
                helka = int(row.get("Helka") or 0)
            except (ValueError, TypeError):
                continue
            if gush and helka:
                self._data[(gush, helka)].append(row)

        self._loaded_at = time.time()
        logger.info("Loaded Haifa zoning CSV: %d parcels", len(self._data))
        return True

    def lookup(self, gush: int, helka: int) -> list[dict]:
        return self._data.get((gush, helka), [])


_cache = _CSVCache()


async def _resolve_parcels(lat: float, lon: float) -> list[tuple[int, int]]:
    """Get parcel (gush, helka) pairs near the coordinates via GovMap."""
    bbox = wgs84_bbox(lat, lon, radius_m=50)
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "opendata:PARCEL_ALL",
        "outputFormat": "application/json",
        "count": "10",
        "BBOX": f"{bbox},EPSG:4326",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_GOVMAP_WFS, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("GovMap parcel lookup failed for Haifa adapter")
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


@register_adapter
class HaifaDataAdapter(SourceAdapter):
    """Haifa zoning data via open-data portal CSV."""

    @property
    def name(self) -> str:
        return "haifa_data"

    @property
    def display_name(self) -> str:
        return "עיריית חיפה (ייעודי קרקע)"

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
        if not await _cache.ensure_loaded():
            return []

        parcels = await _resolve_parcels(lat, lon)
        if not parcels:
            return []

        plans: list[BuildingPlan] = []
        for gush, helka in parcels:
            rows = _cache.lookup(gush, helka)
            for row in rows:
                desc = (row.get("Yeud_Desc") or "").strip()
                taba = (row.get("Taba_Yeud") or "").strip()
                doc_url = (row.get("internet") or "").strip()
                site_url = (row.get("ToSite") or "").strip()

                name_parts = []
                if desc:
                    name_parts.append(desc)
                if taba:
                    name_parts.append(f"תכנית {taba}")
                name_parts.append(f"גוש {gush} חלקה {helka}")
                name = " – ".join(name_parts)

                plans.append(
                    BuildingPlan(
                        name=name,
                        plan_type=_classify_zoning(desc),
                        status=desc,
                        source=self.display_name,
                        source_url=doc_url or site_url,
                        document_url=doc_url,
                        embed_type="iframe" if doc_url else "link",
                        details={
                            "gush": gush,
                            "helka": helka,
                            "zoning_code": row.get("Yeud_Code", ""),
                            "taba": taba,
                            "site_url": site_url,
                        },
                    )
                )

        logger.info("Haifa data returned %d zoning entries for %s", len(plans), address)
        return plans
