#!/usr/bin/env python3
"""Capture dashboard screenshots for the docs.

Usage (gateway must be running with the UI built — `make run`):

    python -m pip install playwright && python -m playwright install chromium
    python scripts/capture_screenshots.py --base-url http://localhost:11435
    python -m pip uninstall -y playwright   # keep it transient

Writes PNGs to docs/assets/screenshots/. The OllaBridge dashboard is a
single-page app with sidebar navigation, so pages are reached by clicking
the sidebar entries rather than by URL.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

# (screenshot name, sidebar label)
PAGES = [
    ("dashboard", "Overview"),
    ("sources", "Sources"),
    ("models", "Models"),
    ("providers", "Providers"),
    ("pairing", "Pairing"),
    ("cloud", "Cloud"),
    ("settings", "Settings"),
]


async def settle(page, ms: int = 1200) -> None:
    """Let animations, data fetches, and transitions finish."""
    await page.wait_for_timeout(ms)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:11435")
    parser.add_argument("--out", default="docs/assets/screenshots")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=args.scale,
            color_scheme="dark",
        )
        page = await context.new_page()

        await page.goto(f"{args.base_url}/ui/", wait_until="networkidle")
        await settle(page, 2000)

        for name, label in PAGES:
            try:
                if label != "Overview":
                    await page.get_by_role("button", name=label).first.click(timeout=4000)
                await settle(page)
                path = out_dir / f"{name}.png"
                await page.screenshot(path=str(path), full_page=False)
                print(f"shot: {path}")
            except Exception as exc:  # keep going — partial sets are still useful
                print(f"skipped {name}: {exc}")

        await browser.close()

    print("done")


if __name__ == "__main__":
    asyncio.run(main())
