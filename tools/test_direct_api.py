import asyncio
import json
from playwright.async_api import async_playwright

AUTH_FILE = "h:/Repos/Personal/Softball/data/auth.json"
EVENTS_API_URL = "https://api.team-manager.gc.com/game-streams/c857aa3a-a5d2-4cf5-906d-22207137475e/events"

async def test_direct_api():
    async with async_playwright() as p:
        # We can just use the APIRequestContext attached to the browser context
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=AUTH_FILE)
        page = await context.new_page()
        
        print(f"[DIRECT API] Navigating to authenticate domain context...")
        # Just need the domain to be set so cookies apply to the fetch, don't wait for full load
        await page.goto("https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule", wait_until="commit")
        
        print(f"[DIRECT API] Requesting {EVENTS_API_URL} via page DOM fetch...")
        
        # Execute fetch inside the authenticated browser context to automatically attach JWTs and cookies
        js_fetch = f"""
        async () => {{
            try {{
                const res = await fetch("{EVENTS_API_URL}");
                if (!res.ok) return {{ error: res.statusText, status: res.status }};
                return await res.json();
            }} catch(e) {{
                return {{ error: e.toString() }};
            }}
        }}
        """
        
        data = await page.evaluate(js_fetch)
        
        if "error" in data:
            print(f"[DIRECT API] Failed request inside DOM. Error: {data}")
        else:
            print(f"[DIRECT API] Success! Received data.")
            with open("h:/Repos/Personal/Softball/data/sharks/raw_events_api.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print("[DIRECT API] Saved to raw_events_api.json")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_direct_api())
