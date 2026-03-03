#!/usr/bin/env python3
"""CLI for Israel Address Building Plans Finder."""
from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from app.orchestrator import SearchOrchestrator

console = Console()


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


@click.group()
def cli():
    """Israel Address Building Plans Finder."""
    pass


@cli.command()
@click.argument("address")
@click.option("--plans-only", is_flag=True, help="Only fetch building plans")
@click.option("--images-only", is_flag=True, help="Only fetch street images")
def search(address: str, plans_only: bool, images_only: bool):
    """Search for building plans and street images by address."""

    async def _search():
        orch = SearchOrchestrator()
        await orch.startup()
        try:
            return await orch.search(
                address, plans_only=plans_only, images_only=images_only
            )
        finally:
            await orch.shutdown()

    with console.status("[bold blue]מחפש...", spinner="dots"):
        result = _run(_search())

    if result.error:
        console.print(Panel(
            f"[red bold]{result.error}[/]\n\n"
            "כמה טיפים:\n"
            "  • ודאו שהכתובת כוללת שם עיר\n"
            "  • בדקו את איות שם הרחוב\n"
            "  • נסו בלי מספר בית",
            title="שגיאה",
            border_style="red",
        ))
        sys.exit(1)

    geo = result.geocode
    console.print()
    console.print(f"[bold green]📍 נמצא:[/] {geo.display_name}")
    console.print(f"   נ.צ: {geo.lat:.5f}, {geo.lon:.5f}  |  עיר: {geo.city}")

    if result.from_cache:
        console.print("[dim]   (מהמטמון)[/]")

    # Plans table
    if result.plans:
        console.print()
        table = Table(
            title=f"תוכניות בנייה ({len(result.plans)} תוצאות)",
            show_lines=True,
            title_style="bold cyan",
        )
        table.add_column("שם", style="bold", max_width=50)
        table.add_column("סוג", justify="center", width=10)
        table.add_column("סטטוס", width=14)
        table.add_column("תאריך", width=12)
        table.add_column("מקור", width=18)

        for p in result.plans:
            type_style = {
                "היתר": "green",
                'תב"ע': "blue",
                "תעודת גמר": "magenta",
                "אחר": "dim",
            }.get(p.plan_type.value, "dim")

            table.add_row(
                p.name,
                f"[{type_style}]{p.plan_type.value}[/]",
                p.status,
                p.date,
                p.source,
            )

        console.print(table)

        # Document links (show first 10)
        linked = [p for p in result.plans if p.document_url]
        if linked:
            console.print()
            console.print("[bold]קישורים למסמכים:[/]")
            for p in linked[:10]:
                console.print(f"  📄 {p.name[:40]}: {p.document_url}")
            if len(linked) > 10:
                console.print(f"  [dim]... ועוד {len(linked) - 10} תוכניות[/]")
    elif not images_only:
        console.print("\n[yellow]לא נמצאו תוכניות בנייה עבור כתובת זו.[/]")

    # Images
    if result.images:
        console.print()
        console.print(f"[bold cyan]תמונות רחוב ({len(result.images)} תוצאות):[/]")
        for i, img in enumerate(result.images, 1):
            console.print(
                f"  {i}. [{img.source}] {img.date}  {img.url}"
            )
    elif not plans_only:
        console.print(
            "\n[yellow]לא נמצאו תמונות רחוב."
            " (הגדירו MAPILLARY_CLIENT_TOKEN או GOOGLE_STREETVIEW_API_KEY ב-.env)[/]"
        )

    # Map link
    if geo:
        console.print()
        console.print(
            f"[bold]🗺️  מפה:[/] https://www.openstreetmap.org/"
            f"?mlat={geo.lat:.5f}&mlon={geo.lon:.5f}#map=18/{geo.lat:.5f}/{geo.lon:.5f}"
        )

    console.print()
    console.print(f"[dim]מקורות שנבדקו: {', '.join(result.sources_tried)}[/]")


@cli.command()
def sources():
    """List registered city sources."""
    import app.services.adapters  # noqa: F401
    from app.services.source_registry import CitySourceRegistry
    from app.config import settings

    registry = CitySourceRegistry(settings.sources_json_path)

    table = Table(title="מקורות מידע רשומים", show_lines=True, title_style="bold cyan")
    table.add_column("עיר", style="bold")
    table.add_column("מקורות (לפי סדר עדיפות)")

    for city, adapter_ids in registry.registered_cities.items():
        label = city if city != "_default" else "[dim]ברירת מחדל[/]"
        table.add_row(label, " → ".join(adapter_ids))

    console.print(table)
    console.print(f"\n[dim]מתאמים רשומים: {', '.join(registry.registered_adapters)}[/]")


@cli.group()
def cache():
    """Manage the results cache."""
    pass


@cache.command("clear")
def cache_clear():
    """Clear all cached results."""

    async def _clear():
        from app.db import CacheDB
        db = CacheDB()
        await db.connect()
        count = await db.clear()
        await db.close()
        return count

    count = _run(_clear())
    console.print(f"[green]נמחקו {count} רשומות מהמטמון.[/]")


@cache.command("stats")
def cache_stats():
    """Show cache statistics."""

    async def _stats():
        from app.db import CacheDB
        db = CacheDB()
        await db.connect()
        stats = await db.stats()
        await db.close()
        return stats

    stats = _run(_stats())
    if not stats:
        console.print("[dim]המטמון ריק.[/]")
    else:
        for kind, count in stats.items():
            console.print(f"  {kind}: {count} רשומות")


if __name__ == "__main__":
    cli()
