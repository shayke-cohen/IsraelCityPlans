"""Search API endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.schemas import SearchResult

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
