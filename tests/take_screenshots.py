#!/usr/bin/env python3
"""Take dashboard screenshots for visual inspection."""
import asyncio
import sys
from pathlib import Path

async def main():
    from playwright.async_api import async_playwright
    import requests
    
    # Check server is running
    try:
        r = requests.get("http://localhost:8000/api/state", timeout=2)
        r.raise_for_status()
    except:
        print("Server not running!")
        return
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        
        # Load page
        await page.goto("http://localhost:8000")
        await page.wait_for_timeout(2000)
        
        # Screenshot idle state
        logs_dir = Path(__file__).parent.parent / "logs"
        await page.screenshot(path=str(logs_dir / "screenshot_idle.png"))
        print(f"✓ Saved idle screenshot")
        
        # Start simulation
        await page.click("#btn-start")
        await page.wait_for_timeout(5000)
        
        # Screenshot running state
        await page.screenshot(path=str(logs_dir / "screenshot_running.png"))
        print(f"✓ Saved running screenshot (5s)")
        
        # Wait more and take another
        await page.wait_for_timeout(5000)
        await page.screenshot(path=str(logs_dir / "screenshot_running_10s.png"))
        print(f"✓ Saved running screenshot (10s)")
        
        # Stop
        await page.click("#btn-stop")
        
        await browser.close()
        print("\n✅ Screenshots saved to logs/")

if __name__ == "__main__":
    asyncio.run(main())
