from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class PlanType(str, Enum):
    PERMIT = "היתר"
    PLAN = "תב\"ע"
    COMPLETION = "תעודת גמר"
    OTHER = "אחר"


class GeocodeResult(BaseModel):
    lat: float
    lon: float
    city: str
    street: str = ""
    house_number: str = ""
    display_name: str = ""


class BuildingPlan(BaseModel):
    name: str
    plan_type: PlanType = PlanType.OTHER
    date: str = ""
    status: str = ""
    source: str = ""
    source_url: str = ""
    document_url: str = ""
    details: dict = Field(default_factory=dict)


class StreetImage(BaseModel):
    url: str
    thumbnail_url: str = ""
    source: str = ""
    date: str = ""
    heading: float | None = None
    lat: float | None = None
    lon: float | None = None


class SearchResult(BaseModel):
    address: str
    geocode: GeocodeResult | None = None
    plans: list[BuildingPlan] = Field(default_factory=list)
    images: list[StreetImage] = Field(default_factory=list)
    sources_tried: list[str] = Field(default_factory=list)
    from_cache: bool = False
    error: str | None = None
