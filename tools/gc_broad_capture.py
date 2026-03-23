import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data" / "sharks"
AUTH_FILE = ROOT_DIR / "data" / "auth.json"

all_responses = []
ws_messages = []

async def handle_response(response):
    url = response.url
    if any(ext in url for ext in [".js", ".css", ".png", ".jpg", ".svg", ".woff", ".ico", ".gif"]):
        return
    if any(dom in url for dom in ["google", "doubleclick", "cloudfront.net", "recurly", "imasdk", "snapchat", "tiktok", "bing", "tapad", "braze", "reddit"]):
        return

    try:
        content_type = response.headers.get("content-type", "")
        status = response.status
        body = ""
        size = 0
        if "json" in content_type or "text" in content_type:
            body = await response.text()
            size = len(body)

        if size > 1000:  # Only care about substantial payloads
            all_responses.append({
                "url": url,
                "status": status,
                "content_type": content_type,
                "size": size,
                "body": body
            })
            print(f"  [RES] {status} {url[:100]} ({size:,} bytes) [{content_type[:30]}]")
    except Exception:
        pass

async def handle_websocket(ws):
    print(f"  [WS CONNECTED] {ws.url}")
    
    async def log_frame(payload, is_sent):
        prefix = "SENT" if is_sent else "RECV"
        size = len(payload) if isinstance(payload, str) else len(payload)
        
        # Keep track if it's large or looks like JSON
        is_string = isinstance(payload, str)
        content = payload if is_string else "<binary>"
        
        ws_messages.append({
            "url": ws.url,
            "direction": prefix,
            "size": size,
            "timestamp": asyncio.get_event_loop().time(),
            "payload": content[:2000] if is_string else "BINARY_DATA"
        })
        
        if size > 100:
            print(f"  [WS {prefix}] {size:,} bytes | {content[:100].strip() if is_string else '<binary>'}")

    ws.on("framesent", lambda p: asyncio.create_task(log_frame(p, True)))
    ws.on("framereceived", lambda p: asyncio.create_task(log_frame(p, False)))

async def run():
    if not AUTH_FILE.exists():
        print("[ERROR] No auth.json found")
        return

    print("[Broad Capture] Starting with WebSocket tracking...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_FILE))
        page = await context.new_page()
        
        page.on("response", handle_response)
        page.on("websocket", handle_websocket)

        # We first go to the Box Score or Schedule page, to replicate a natural user flow.
        game_box_url = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule/7b61aa7b-cde9-40c3-937f-48e2a9cdb0a2/box-score"
        print(f"[Broad Capture] Loading Box Score: {game_box_url}")
        await page.goto(game_box_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        
        # Click on Plays tab
        print("[Broad Capture] Clicking Plays tab...")
        try:
            tab = page.locator("text='Plays'")
            if await tab.count() > 0:
                await tab.first.click()
                await page.wait_for_timeout(10000)
            else:
                print("Could not find Plays tab text. Trying direct navigation.")
                plays_url = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule/7b61aa7b-cde9-40c3-937f-48e2a9cdb0a2/plays"
                await page.goto(plays_url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"Error clicking: {e}")

        print("\n[Broad Capture] Done waiting. Saving dumps...")
        
        # Save WS dump
        ws_file = DATA_DIR / "ws_captures.json"
        with open(ws_file, "w", encoding="utf-8") as f:
            json.dump(ws_messages, f, indent=2)
            
        # Save RES dump
        res_file = DATA_DIR / "res_captures.json"
        with open(res_file, "w", encoding="utf-8") as f:
            json.dump(all_responses, f, indent=2)

        print(f"Captured {len(all_responses)} responses > 1KB and {len(ws_messages)} WS frames.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
