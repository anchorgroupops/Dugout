"""
GameChanger API Capture via Playwright Network Interception
Captures the raw API JSON payloads that the GameChanger web app uses
to render play-by-play and pitch-by-pitch data.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data" / "sharks"
AUTH_FILE = ROOT_DIR / "data" / "auth.json"

# We'll collect all API responses that look like game data
captured_responses = []

async def handle_response(response):
    """Intercept all API responses and save ones that look like game data."""
    url = response.url
    # Look for GameChanger API endpoints
    if any(keyword in url for keyword in [
        "api.team-manager.gc.com",
        "game-streams",
        "/events",
        "/plays",
        "/pitches",
        "/game/",
        "graphql",
        "gc.com/api",
    ]):
        try:
            content_type = response.headers.get("content-type", "")
            if "json" in content_type or "text" in content_type:
                body = await response.text()
                size = len(body)
                captured_responses.append({
                    "url": url,
                    "status": response.status,
                    "size": size,
                    "body": body
                })
                print(f"  [CAPTURED] {response.status} {url[:120]} ({size:,} bytes)")
        except Exception as e:
            print(f"  [SKIP] {url[:80]} - {e}")

async def run_capture():
    if not AUTH_FILE.exists():
        print(f"[ERROR] Auth file not found at {AUTH_FILE}. Please log in first.")
        return

    print("[GC API Capture] Starting Playwright network interception...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_FILE))
        page = await context.new_page()

        # Attach response listener to capture ALL API calls
        page.on("response", handle_response)

        # Navigate to team schedule to find latest game
        TEAM_URL = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule"
        print(f"[GC API Capture] Loading schedule: {TEAM_URL}")
        await page.goto(TEAM_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        # Find all game links on the schedule page
        game_links = await page.locator('a[href*="/schedule/"]').all()
        print(f"[GC API Capture] Found {len(game_links)} game links on schedule")

        # Get all hrefs
        hrefs = []
        for link in game_links:
            href = await link.get_attribute("href")
            if href and "/box-score" not in href and "/schedule/" in href:
                # Skip non-game links
                text = await link.inner_text()
                hrefs.append({"href": href, "text": text.strip()[:50]})

        # Print what we found
        for h in hrefs:
            print(f"  Game: {h['text']} -> {h['href']}")

        # Navigate to the most recent (last) completed game
        # Try to find the latest game with a score
        all_text = await page.locator("body").inner_text()
        print(f"\n[GC API Capture] Schedule page text length: {len(all_text)}")

        # Let's just navigate to the latest game box score page
        # First, let's look at what URLs were captured during schedule load
        print(f"\n[GC API Capture] Captured {len(captured_responses)} API responses so far")
        for r in captured_responses:
            print(f"  {r['status']} {r['url'][:120]} ({r['size']:,} bytes)")

        # Now navigate to the box-score page and click Plays
        # Use the first game link that looks like a game
        GAME_URL = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule"
        
        # Find all links that contain /schedule/ and have a UUID pattern
        import re
        game_uuid_links = []
        page_content = await page.content()
        uuids = re.findall(r'/schedule/([a-f0-9-]{36})', page_content)
        unique_uuids = list(dict.fromkeys(uuids))  # preserve order, dedupe
        print(f"\n[GC API Capture] Found {len(unique_uuids)} unique game UUIDs")
        for uid in unique_uuids:
            print(f"  UUID: {uid}")

        if not unique_uuids:
            print("[GC API Capture] No games found!")
            await browser.close()
            return

        # Navigate to the latest game (last UUID is usually most recent)
        latest_uuid = unique_uuids[-1]
        game_url = f"https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule/{latest_uuid}/plays"
        print(f"\n[GC API Capture] Navigating to latest game Plays: {game_url}")
        
        # Clear old captures
        captured_responses.clear()
        
        await page.goto(game_url, wait_until="domcontentloaded", timeout=60000)
        print("[GC API Capture] Waiting 10 seconds for all API calls to complete...")
        await page.wait_for_timeout(10000)

        print(f"\n[GC API Capture] Captured {len(captured_responses)} API responses from Plays page")
        
        # Save ALL captured responses
        all_captures_file = DATA_DIR / "api_captures.json"
        save_data = []
        for r in captured_responses:
            print(f"  {r['status']} {r['url'][:120]} ({r['size']:,} bytes)")
            save_data.append({
                "url": r["url"],
                "status": r["status"],
                "size": r["size"],
                "body": r["body"]
            })

        with open(all_captures_file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2)
        print(f"\n[GC API Capture] Saved all captures to {all_captures_file}")

        # Also save the largest response as the main payload
        if captured_responses:
            biggest = max(captured_responses, key=lambda r: r["size"])
            main_file = DATA_DIR / "app_plays_api.json"
            with open(main_file, "w", encoding="utf-8") as f:
                f.write(biggest["body"])
            print(f"[GC API Capture] Saved largest payload ({biggest['size']:,} bytes) to {main_file}")
            print(f"  URL: {biggest['url']}")
        else:
            print("[GC API Capture] No API responses captured! The data may be loaded via different mechanism.")
            # Fallback: capture ALL network responses (not just filtered)
            print("[GC API Capture] Trying broader capture...")

        await browser.close()

    print(f"\n[GC API Capture] Done! Total captured responses: {len(save_data)}")

if __name__ == "__main__":
    asyncio.run(run_capture())
