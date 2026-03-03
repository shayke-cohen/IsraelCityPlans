"""Integration test for city adapters.

Geocodes representative addresses, runs each adapter, and prints a
summary table comparing plan counts and quality across cities.

Usage:
    python test_adapters.py [--baseline]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.services.adapters  # noqa: F401  — trigger registration
from app.services import geocoder
from app.services.source_registry import CitySourceRegistry

SOURCES_JSON = Path(__file__).resolve().parent / "sources.json"

TEST_ADDRESSES: list[dict] = [
    {"address": "יפו 97, ירושלים", "city_label": "Jerusalem"},
    {"address": "הרצל 1, חיפה", "city_label": "Haifa"},
    {"address": "רגר 25, באר שבע", "city_label": "Beer Sheva"},
    {"address": "הרצל 50, ראשון לציון", "city_label": "Rishon LeZion"},
    {"address": "רוטשילד 10, פתח תקווה", "city_label": "Petah Tikva"},
]


def _details_summary(plan) -> str:
    """One-line summary of interesting detail keys."""
    d = plan.details
    parts: list[str] = []
    if d.get("plan_number"):
        parts.append(f"plan={d['plan_number']}")
    if d.get("taba_number") or d.get("taba"):
        parts.append(f"taba={d.get('taba_number') or d.get('taba')}")
    if d.get("gush"):
        parts.append(f"gush={d['gush']}")
    if d.get("parcel") or d.get("helka"):
        parts.append(f"helka={d.get('parcel') or d.get('helka')}")
    if d.get("distance_m") is not None:
        parts.append(f"dist={d['distance_m']}m")
    if d.get("area_dunam"):
        parts.append(f"area={d['area_dunam']}d")
    if d.get("is_fallback"):
        parts.append("FALLBACK")
    return ", ".join(parts) if parts else "-"


async def test_address(registry: CitySourceRegistry, entry: dict) -> dict:
    address = entry["address"]
    label = entry["city_label"]
    print(f"\n{'='*70}")
    print(f"  {label}: {address}")
    print(f"{'='*70}")

    geo = await geocoder.geocode(address)
    if geo is None:
        print("  *** GEOCODE FAILED ***")
        return {"city": label, "address": address, "error": "geocode_failed"}

    print(f"  Geocode: {geo.city} | {geo.street} {geo.house_number}")
    print(f"  Coords:  {geo.lat:.6f}, {geo.lon:.6f}")

    t0 = time.monotonic()
    plans, sources_tried = await registry.find_plans(
        geo.city, address, geo.lat, geo.lon,
        street=geo.street, house_number=geo.house_number,
    )
    elapsed = time.monotonic() - t0

    print(f"  Sources tried: {sources_tried}")
    print(f"  Plans found:   {len(plans)}  ({elapsed:.1f}s)")

    per_source: dict[str, int] = {}
    for p in plans:
        per_source[p.source] = per_source.get(p.source, 0) + 1
    print(f"  Per source:    {per_source}")

    for i, p in enumerate(plans[:8], 1):
        print(f"  [{i}] {p.source} | {p.plan_type.value} | {p.name[:60]}")
        print(f"      status={p.status}  {_details_summary(p)}")

    if len(plans) > 8:
        print(f"  ... and {len(plans) - 8} more")

    return {
        "city": label,
        "address": address,
        "geocode": {"city": geo.city, "street": geo.street, "house_number": geo.house_number},
        "total_plans": len(plans),
        "per_source": per_source,
        "sources_tried": sources_tried,
        "elapsed_s": round(elapsed, 2),
    }


async def main() -> None:
    save_baseline = "--baseline" in sys.argv

    registry = CitySourceRegistry(SOURCES_JSON)

    results = []
    for entry in TEST_ADDRESSES:
        r = await test_address(registry, entry)
        results.append(r)

    print(f"\n\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    print(f"  {'City':<18} {'Plans':>6}  {'Sources':>8}  {'Time':>6}  Per-source breakdown")
    print(f"  {'-'*18} {'-'*6}  {'-'*8}  {'-'*6}  {'-'*30}")
    for r in results:
        if r.get("error"):
            print(f"  {r['city']:<18} {'ERR':>6}")
            continue
        src_str = ", ".join(f"{k}:{v}" for k, v in r["per_source"].items())
        print(
            f"  {r['city']:<18} {r['total_plans']:>6}  "
            f"{len(r['sources_tried']):>8}  "
            f"{r['elapsed_s']:>5.1f}s  {src_str}"
        )

    if save_baseline:
        out = Path(__file__).resolve().parent / "test_baseline.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  Baseline saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
