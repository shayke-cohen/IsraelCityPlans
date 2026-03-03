"""Coordinate utilities for Israeli spatial data.

Provides bounding-box helpers for WGS84 (EPSG:4326) queries.
GovMap WFS accepts BBOX in WGS84 and returns geometry in EPSG:3857.
"""
from __future__ import annotations

import math


def wgs84_bbox(lat: float, lon: float, radius_m: float = 100) -> str:
    """Return a WGS84 BBOX string (minlon,minlat,maxlon,maxlat) for a *radius_m* buffer.

    Good enough for small radii typical of building-plan lookups (50-200 m).
    """
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    return f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"
