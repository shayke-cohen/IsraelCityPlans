"""Layered city source registry.

Maps city names to an ordered chain of source adapters.
For any lookup the system identifies the city via geocoding, then tries each
source in order until one returns results.  When no city-specific sources
exist, the ``_default`` chain is used.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from app.models.schemas import BuildingPlan

logger = logging.getLogger(__name__)


class SourceAdapter(ABC):
    """Base class all city building-plan adapters must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Machine-readable adapter id (matches key in sources.json)."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable Hebrew name shown in UI badges."""

    @abstractmethod
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
        """Return building plans for the given address / coordinates."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ADAPTER_CLASSES: dict[str, type[SourceAdapter]] = {}


def register_adapter(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Class decorator that registers an adapter by its ``name``."""
    instance = cls.__new__(cls)
    _ADAPTER_CLASSES[instance.name] = cls
    return cls


class CitySourceRegistry:
    """Reads ``sources.json`` and resolves adapter chains per city."""

    def __init__(self, config_path: str | Path) -> None:
        self._config_path = Path(config_path)
        self._city_map: dict[str, list[str]] = {}
        self._adapters: dict[str, SourceAdapter] = {}
        self._load()

    def _load(self) -> None:
        raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        for city, entry in raw.items():
            self._city_map[city] = entry["sources"]

        for adapter_id, cls in _ADAPTER_CLASSES.items():
            self._adapters[adapter_id] = cls()

    @staticmethod
    def _normalize_city(city: str) -> str:
        """Normalise unicode dashes, whitespace, and separators for stable lookup.

        Strips all spaces and punctuation variations so that
        ``"תל אביב-יפו"``, ``"תל־אביב–יפו"``, and ``"תל-אביב-יפו"``
        all resolve to the same key.
        """
        import unicodedata

        out: list[str] = []
        for ch in city:
            cat = unicodedata.category(ch)
            if cat.startswith("P"):
                continue  # drop all punctuation
            if cat.startswith("Z"):
                continue  # drop all whitespace/separators
            out.append(ch)
        return "".join(out)

    def get_chain(self, city: str) -> list[SourceAdapter]:
        """Return the ordered adapter chain for *city*, falling back to ``_default``."""
        norm = self._normalize_city(city)
        ids: list[str] | None = None
        for key, val in self._city_map.items():
            if key == "_default":
                continue
            if self._normalize_city(key) == norm:
                ids = val
                break
        if ids is None:
            ids = self._city_map.get("_default", [])

        chain: list[SourceAdapter] = []
        for aid in ids:
            adapter = self._adapters.get(aid)
            if adapter is not None:
                chain.append(adapter)
            else:
                logger.warning("Adapter %r listed in config but not registered", aid)
        return chain

    async def find_plans(
        self,
        city: str,
        address: str,
        lat: float,
        lon: float,
        *,
        street: str = "",
        house_number: str = "",
    ) -> tuple[list[BuildingPlan], list[str]]:
        """Try each adapter in the chain; return on first success.

        Returns ``(plans, sources_tried)``.
        """
        chain = self.get_chain(city)
        sources_tried: list[str] = []
        for adapter in chain:
            sources_tried.append(adapter.name)
            try:
                plans = await adapter.search(
                    address,
                    lat,
                    lon,
                    city=city,
                    street=street,
                    house_number=house_number,
                )
                if plans:
                    logger.info(
                        "Adapter %s returned %d plans for %s",
                        adapter.name,
                        len(plans),
                        address,
                    )
                    return plans, sources_tried
            except Exception:
                logger.exception("Adapter %s failed for %s", adapter.name, address)
        return [], sources_tried

    @property
    def registered_cities(self) -> dict[str, list[str]]:
        return dict(self._city_map)

    @property
    def registered_adapters(self) -> list[str]:
        return list(self._adapters.keys())
