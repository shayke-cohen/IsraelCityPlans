"""Search API endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.models.schemas import SearchResult
from app.services.street_imagery import fetch_streetview_bytes

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResult)
async def search(
    request: Request,
    q: str = Query(..., min_length=2, description="Hebrew address to search"),
    plans_only: bool = Query(False, description="Only fetch building plans"),
    images_only: bool = Query(False, description="Only fetch street images"),
) -> SearchResult:
    orch = request.app.state.orchestrator
    result = await orch.search(q, plans_only=plans_only, images_only=images_only)
    if result.error:
        raise HTTPException(status_code=404, detail=result.error)
    return result


@router.get("/streetview/image")
async def streetview_image(
    lat: float = Query(...),
    lon: float = Query(...),
    heading: int = Query(0, ge=0, le=360),
    size: str = Query("640x480"),
) -> Response:
    """Proxy Google Street View Static API images (hides API key from frontend)."""
    data = await fetch_streetview_bytes(lat, lon, heading, size)
    if not data:
        raise HTTPException(status_code=404, detail="Street View image not available")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/streetview/download")
async def streetview_download(
    lat: float = Query(...),
    lon: float = Query(...),
    heading: int = Query(0, ge=0, le=360),
) -> Response:
    """Download a Street View image with a descriptive filename."""
    data = await fetch_streetview_bytes(lat, lon, heading, "640x480")
    if not data:
        raise HTTPException(status_code=404, detail="Street View image not available")
    filename = f"streetview_{lat:.5f}_{lon:.5f}_{heading}.jpg"
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/sources")
async def sources(request: Request) -> dict:
    orch = request.app.state.orchestrator
    return {
        "cities": orch.registry.registered_cities,
        "adapters": orch.registry.registered_adapters,
    }


@router.get("/cache/stats")
async def cache_stats(request: Request) -> dict:
    orch = request.app.state.orchestrator
    return await orch.cache.stats()


@router.delete("/cache")
async def cache_clear(request: Request) -> dict:
    orch = request.app.state.orchestrator
    count = await orch.cache.clear()
    return {"deleted": count}
