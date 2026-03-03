from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    mapillary_client_token: str = ""
    google_streetview_api_key: str = ""

    sources_json_path: str = str(PROJECT_ROOT / "sources.json")
    db_path: str = str(PROJECT_ROOT / "cache.db")

    cache_ttl_plans_days: int = 30
    cache_ttl_images_days: int = 90
    cache_ttl_geocode_days: int = 90

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"


settings = Settings()
