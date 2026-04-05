"""
fetch_youtube_deep.py — Scrape 200 videos from a YouTube channel.
Uses Playwright to scroll through the videos tab to get IDs beyond the RSS limit.
"""
import sys
import asyncio
from playwright.async_api import async_playwright
import json
from pathlib import Path
from datetime import datetime, timezone

async def fetch_deep(channel_handle, limit=200):
    print(f"🎥 The Librarian: Deep-syncing {limit} videos for {channel_handle}...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Determine URL
        if channel_handle.startswith("UC"):
            url = f"https://www.youtube.com/channel/{channel_handle}/videos"
        else:
            handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
            url = f"https://www.youtube.com/{handle}/videos"
            
        await page.goto(url)
        
        # Scroll logic
        videos = []
        last_count = 0
        while len(videos) < limit:
            # Extract current visible videos
            elements = await page.query_selector_all('a#video-title-link')
            for el in elements:
                v_url = await el.get_attribute('href')
                v_title = await el.get_attribute('title')
                full_url = f"https://www.youtube.com{v_url}"
                
                if full_url not in [v['url'] for v in videos]:
                    videos.append({
                        "url": full_url,
                        "title": v_title,
                        "added_at": datetime.now(timezone.utc).isoformat()
                    })
                    if len(videos) >= limit: break
            
            if len(videos) == last_count:
                # No new videos found, break
                break
            
            last_count = len(videos)
            print(f"   Collected {len(videos)} sources...")
            
            # Scroll down
            await page.keyboard.press("End")
            await page.wait_for_timeout(2000)

        await browser.close()
        print(f"✅ Deep-sync complete. Found {len(videos)} videos.")
        return videos

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_youtube_deep.py <handle_or_id> [limit]")
        sys.exit(1)
        
    handle = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    
    results = asyncio.run(fetch_deep(handle, limit))
    print(json.dumps(results, indent=2))
