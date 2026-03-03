"""Address autocomplete endpoints backed by data.gov.il."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/address", tags=["address"])


@router.get("/cities")
async def cities(
    request: Request,
    q: str = Query("", min_length=0, description="City name prefix (Hebrew or English)"),
) -> list[dict]:
    svc = request.app.state.address_data
    results = await svc.get_cities(q)
    return [{"code": c.code, "name": c.name, "name_en": c.name_en} for c in results]


@router.get("/streets")
async def streets(
    request: Request,
    city_code: int = Query(..., description="City code from /api/address/cities"),
    q: str = Query("", min_length=0, description="Street name prefix"),
) -> list[dict]:
    svc = request.app.state.address_data
    results = await svc.get_streets(city_code, q)
    return [{"code": s.code, "name": s.name} for s in results]
