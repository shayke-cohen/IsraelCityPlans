"""SQLite cache layer.

Stores geocoding results, building plans, and street images keyed by
normalised address.  Each entry type has an independent TTL.
"""
from __future__ import annotations

import json
import logging
import time
import unicodedata
from pathlib import Path

import aiosqlite

from app.config import settings
from app.models.schemas import (
    BuildingPlan,
    GeocodeResult,
    SearchResult,
    StreetImage,
)

logger = logging.getLogger(__name__)

_DAY = 86_400  # seconds


def _normalize_key(address: str) -> str:
    """Collapse whitespace and punctuation for stable cache keys."""
    chars = []
    for ch in address.lower():
        cat = unicodedata.category(ch)
        if cat.startswith("Z"):
            chars.append(" ")
        elif cat.startswith("P"):
            continue
        else:
            chars.append(ch)
    return " ".join("".join(chars).split())


class CacheDB:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = str(db_path or settings.db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key       TEXT PRIMARY KEY,
                kind      TEXT NOT NULL,
                data      TEXT NOT NULL,
                stored_at REAL NOT NULL
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Generic get / set
    # ------------------------------------------------------------------

    async def _get(self, key: str, kind: str, ttl_days: int) -> str | None:
        assert self._db
        cursor = await self._db.execute(
            "SELECT data, stored_at FROM cache WHERE key = ? AND kind = ?",
            (key, kind),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        data, stored_at = row
        if time.time() - stored_at > ttl_days * _DAY:
            await self._db.execute(
                "DELETE FROM cache WHERE key = ? AND kind = ?", (key, kind)
            )
            await self._db.commit()
            return None
        return data

    async def _set(self, key: str, kind: str, data: str) -> None:
        assert self._db
        await self._db.execute(
            """
            INSERT OR REPLACE INTO cache (key, kind, data, stored_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, kind, data, time.time()),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Typed accessors
    # ------------------------------------------------------------------

    async def get_geocode(self, address: str) -> GeocodeResult | None:
        key = _normalize_key(address)
        raw = await self._get(key, "geocode", settings.cache_ttl_geocode_days)
        if raw is None:
            return None
        return GeocodeResult.model_validate_json(raw)

    async def set_geocode(self, address: str, result: GeocodeResult) -> None:
        key = _normalize_key(address)
        await self._set(key, "geocode", result.model_dump_json())

    async def get_search(self, address: str) -> SearchResult | None:
        key = _normalize_key(address)
        raw = await self._get(key, "search", settings.cache_ttl_plans_days)
        if raw is None:
            return None
        result = SearchResult.model_validate_json(raw)
        result.from_cache = True
        return result

    async def set_search(self, address: str, result: SearchResult) -> None:
        key = _normalize_key(address)
        await self._set(key, "search", result.model_dump_json())

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    async def clear(self) -> int:
        """Remove all cached entries. Returns count of deleted rows."""
        assert self._db
        cursor = await self._db.execute("SELECT count(*) FROM cache")
        row = await cursor.fetchone()
        count = row[0] if row else 0
        await self._db.execute("DELETE FROM cache")
        await self._db.commit()
        return count

    async def stats(self) -> dict:
        assert self._db
        cursor = await self._db.execute(
            "SELECT kind, count(*) FROM cache GROUP BY kind"
        )
        rows = await cursor.fetchall()
        return {kind: cnt for kind, cnt in rows}
