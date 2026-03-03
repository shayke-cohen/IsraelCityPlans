"""MAVAT national planning database adapter.

MAVAT (mavat.iplan.gov.il) is the official Israeli planning information system.
Its web interface requires JavaScript rendering, so this adapter provides
search-by-link functionality and relies on XPLAN for actual data retrieval.
It acts as a last-resort source that always returns a helpful reference link.
"""
from __future__ import annotations

import logging

from app.models.schemas import BuildingPlan, PlanType
from app.services.source_registry import SourceAdapter, register_adapter

logger = logging.getLogger(__name__)


@register_adapter
class MAVATAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "mavat"

    @property
    def display_name(self) -> str:
        return 'מבא"ת (מידע תכנוני)'

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
        # MAVAT doesn't expose a clean REST API.
        # Return a reference entry that links to the MAVAT map viewer centred
        # on the requested coordinates so the user can explore interactively.
        mavat_url = (
            f"https://mavat.iplan.gov.il/SV4/1?center={lon},{lat}&zoom=17"
        )
        return [
            BuildingPlan(
                name=f"חיפוש במבא\"ת – {address}",
                plan_type=PlanType.OTHER,
                status="קישור לחיפוש ידני",
                source=self.display_name,
                source_url=mavat_url,
                document_url=mavat_url,
            )
        ]
