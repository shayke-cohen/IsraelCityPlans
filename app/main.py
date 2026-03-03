"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.orchestrator import SearchOrchestrator
from app.routers.address import router as address_router
from app.routers.search import router as search_router
from app.services.address_data import AddressDataService
from app.services.playwright_capture import shutdown_browser, CAPTURES_DIR

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    orch = SearchOrchestrator()
    await orch.startup()
    app.state.orchestrator = orch
    app.state.address_data = AddressDataService()
    yield
    await shutdown_browser()
    await orch.shutdown()


app = FastAPI(
    title="Israel Building Plans Finder",
    description="Search Israeli building plans and street images by address",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(search_router)
app.include_router(address_router)

CAPTURES_DIR.mkdir(exist_ok=True)
app.mount("/captures", StaticFiles(directory=str(CAPTURES_DIR)), name="captures")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Israel Building Plans Finder API", "docs": "/docs"}
