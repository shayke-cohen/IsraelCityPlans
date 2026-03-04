#!/usr/bin/env python3
"""Capture screenshots of the AmitAddress web application for documentation."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

SCREENSHOTS_DIR = Path("/Users/shayco/AmitAddress/docs/screenshots")
BASE_URL = "http://localhost:8000"


async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # 1. Main search page (empty state)
        await page.goto(BASE_URL)
        await page.screenshot(path=SCREENSHOTS_DIR / "search-page.png")
        print("Saved: search-page.png")

        # 2. Search results for "כיסופים 18, תל אביב"
        await page.goto(f"{BASE_URL}/?q=כיסופים%2018,%20תל%20אביב")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        await page.screenshot(path=SCREENSHOTS_DIR / "search-results.png", full_page=True)
        print("Saved: search-results.png")

        # 3. Building plans section - scroll to plans, viewport screenshot
        plans_selectors = [
            '#plans-section',
            '[data-testid="building-plans"]',
            '[id*="plans"]',
            '[class*="plans"]',
            '[class*="plan"]',
            'text=תוכניות',
            'text=תוכנית',
            'h2:has-text("תוכניות")',
            'h2:has-text("תוכנית")',
        ]
        scrolled = False
        for selector in plans_selectors:
            try:
                el = page.locator(selector).first
                if await el.count() > 0:
                    await el.scroll_into_view_if_needed()
                    scrolled = True
                    break
            except Exception:
                continue

        if not scrolled:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)

        await page.screenshot(path=SCREENSHOTS_DIR / "building-plans.png")
        print("Saved: building-plans.png")

        await browser.close()

    return [
        str(SCREENSHOTS_DIR / "search-page.png"),
        str(SCREENSHOTS_DIR / "search-results.png"),
        str(SCREENSHOTS_DIR / "building-plans.png"),
    ]


if __name__ == "__main__":
    paths = asyncio.run(capture())
    print("\nAll screenshots saved to:")
    for p in paths:
        print(f"  {p}")
