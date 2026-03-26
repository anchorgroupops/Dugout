"""
scrape_sharks_games.py — Scrape all confirmed Sharks game IDs (DOM-linked)
using gc_full_scraper. Runs headlessly using saved auth.json.
"""
import subprocess
import sys
from pathlib import Path

# Game IDs confirmed to be on the Sharks schedule page
SHARKS_GAME_IDS = [
    "7931431c-a877-4839-9c6c-c512a138db25",
    "2c4bb11e-58d7-47b1-bf30-aa1220f3777c",
    "f831909e-280e-4983-b91c-7fb0e0bf01fe",
    "bf0e62bf-8f9e-4d1e-986c-818eacf20029",
    "83e0e636-e090-4fa8-8ae5-d863067dcffc",
    "715884f5-1670-4373-b697-4c4b34d487c3",
    "bf2a3900-fe68-4fea-9449-2d51461aec46",
    "c788b67e-8590-4fb1-b652-572778624aed",
    "5b21551a-baac-4f96-bc51-472f451d33c3",
    "c96ba9b4-21d3-4690-92bc-1ed4227febba",
    "0283fcaf-b6d4-4551-98cc-0517638d9b09",
    "dd699b95-0408-4994-8405-cffae23b43f9",
    "df7a90f6-261a-40ce-a820-80c4d68596c9",
    "a4ebc615-5a99-4586-a8d2-925906d93ec4",
    "391b34ad-ec65-49cc-b772-4d61387a6eb0",
    "7b61aa7b-cde9-40c3-937f-48e2a9cdb0a2",
]

TOOLS_DIR = Path(__file__).resolve().parent

def main():
    force = "--force" in sys.argv
    total = len(SHARKS_GAME_IDS)
    success = 0
    skipped = 0
    failed = 0

    for i, gid in enumerate(SHARKS_GAME_IDS, 1):
        print(f"\n[{i}/{total}] Scraping {gid}")
        cmd = [sys.executable, str(TOOLS_DIR / "gc_full_scraper.py"), "--game-id", gid]
        if force:
            cmd.append("--force")
        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode == 0:
            success += 1
        else:
            failed += 1

    print(f"\n=== Done: {success} scraped, {skipped} skipped, {failed} failed ===")

if __name__ == "__main__":
    main()
