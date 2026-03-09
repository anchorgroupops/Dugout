import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data" / "sharks"
AUTH_FILE = ROOT_DIR / "data" / "auth.json"

def parse_plays_text(text_content):
    lines = [line.strip() for line in text_content.splitlines() if line.strip()]
    plays = []
    current_inning = ""
    current_team = ""
    
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        inning_match = re.match(r"(Top|Bottom)\s+(\w+)\s+-\s+(.+)", line, re.IGNORECASE)
        if inning_match:
            current_inning = f"{inning_match.group(1)} {inning_match.group(2)}"
            current_team = inning_match.group(3)
            idx += 1
            continue
            
        if current_inning and idx + 3 < len(lines):
            outs_match = re.match(r"(\d)\s+Outs?", lines[idx+1], re.IGNORECASE)
            if outs_match:
                result = lines[idx]
                outs = int(outs_match.group(1))
                pitches = lines[idx+2]
                description = lines[idx+3]
                
                lineup_change = None
                if "Lineup changed:" in pitches:
                    parts = pitches.split(", ", 1)
                    lineup_change = parts[0]
                    pitches = parts[1] if len(parts) > 1 else ""

                play_obj = {
                    "inning": current_inning,
                    "team": current_team,
                    "result": result,
                    "outs": outs,
                    "pitches": pitches,
                    "description": description
                }
                if lineup_change:
                    play_obj["lineup_change"] = lineup_change
                    
                plays.append(play_obj)
                idx += 4
                continue
        idx += 1
        
    return plays


def _safe_val(v):
    if not v: return None
    v = v.strip()
    return v if v else None

async def extract_plays(page, game_url):
    """Navigates to a game page, clicks Plays, and extracts the play-by-play data."""
    print(f"[GC PBP] Navigating to game: {game_url}")
    await page.goto(f"https://web.gc.com{game_url}", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)
    
    # Click Plays tab
    try:
        # The Plays tab usually has text 'Plays'
        plays_tab = page.locator("text='Plays'")
        if await plays_tab.count() > 0:
            await plays_tab.first.click()
            await page.wait_for_timeout(2000)
        else:
            print(f"[GC PBP] No 'Plays' tab found for {game_url}")
            return None
    except Exception as e:
        print(f"[GC PBP] Error clicking Plays tab: {e}")
        return None

    # (Removed obsolete JS extraction block)
async def run_scraper():
    if not AUTH_FILE.exists():
        print(f"[ERROR] Auth file not found at {AUTH_FILE}. Please log in first.")
        return

    print("[GC PBP] Starting Play-by-Play Scraper (DOM Text Extraction)...")
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_FILE))
        page = await context.new_page()

        GAME_URL = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule/f831909e-280e-4983-b91c-7fb0e0bf01fe/box-score"
        
        print(f"[GC PBP] Navigating directly to Game Page: {GAME_URL}")
        # Use domcontentloaded
        await page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
        
        print("[GC PBP] Waiting 5 seconds for React to mount...")
        await page.wait_for_timeout(5000) 
        
        try:
            # GameChanger tabs are usually links
            plays_tab = page.locator('a:has-text("Plays")').first
            if await plays_tab.count() > 0:
                print("[GC PBP] Clicking Plays tab...")
                await plays_tab.click()
                print("[GC PBP] Waiting 8 seconds for plays data to render...")
                await page.wait_for_timeout(8000) 
                # Extract all text from the page
                print("[GC PBP] Extracting visible text...")
                text_content = await page.locator("body").inner_text()
                
                out_file_raw = DATA_DIR / "raw_plays_text.txt"
                with open(out_file_raw, "w", encoding="utf-8") as f:
                    f.write(text_content)
                    
                print(f"[GC PBP] Extracted text. Parsing...")
                plays = parse_plays_text(text_content)
                
                out_file_json = DATA_DIR / "plays.json"
                with open(out_file_json, "w", encoding="utf-8") as f:
                    json.dump(plays, f, indent=4)
                    
                print(f"[GC PBP] Successfully parsed {len(plays)} plays. Saved to {out_file_json}")
            else:
                print("[GC PBP] Could not find Plays tab.")
                
        except Exception as e:
            print(f"[GC PBP] Failed to scrape plays tab: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_scraper())
