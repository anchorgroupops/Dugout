"""
nb_cleaner.py — Automated Notebook Deletion via Playwright.
NotebookLM MCP lacks a delete tool, so we use browser automation.
"""
import sys
import os
import asyncio
from playwright.async_api import async_playwright
import json
from pathlib import Path

# Project root
ROOT = Path(__file__).parent.parent

async def delete_notebooks(notebook_ids):
    if not notebook_ids:
        print("✅ No notebooks specified for deletion.")
        return

    print(f"🧹 The Librarian: Starting automated cleanup of {len(notebook_ids)} notebooks...")
    
    async with async_playwright() as p:
        # We use the user's Chrome data to inherit the session
        # This assumes the user has 'notebooklm.google.com' open in their default Chrome
        user_data_dir = os.path.join(os.environ['LOCALAPPDATA'], 'Google', 'Chrome', 'User Data')
        
        try:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir,
                headless=True, # Change to False if debugging
                args=["--profile-directory=Default"] # Or 'Profile 1' etc
            )
        except Exception as e:
            print(f"❌ Could not launch browser with persistent context: {e}")
            print("💡 Close all Chrome windows and try again, or use a separate profile.")
            return

        page = await browser.new_page()
        
        for nb_id in notebook_ids:
            url = f"https://notebooklm.google.com/notebook/{nb_id}"
            print(f"👉 Navigating to notebook: {nb_id}")
            
            try:
                await page.goto(url, wait_until="networkidle")
                
                # Deletion logic:
                # 1. Click the '...' menu (Top right)
                # 2. Click 'Delete notebook'
                # 3. Confirm in dialog
                
                # Note: These selectors are based on current NotebookLM UI. 
                # They may need updates if the UI shifts.
                
                # Finding the menu button (more options)
                menu_btn = page.locator('button[aria-label="More options"]').first
                if await menu_btn.is_visible():
                    await menu_btn.click()
                    await page.wait_for_timeout(500)
                    
                    delete_btn = page.locator('text="Delete notebook"')
                    if await delete_btn.is_visible():
                        await delete_btn.click()
                        await page.wait_for_timeout(500)
                        
                        confirm_btn = page.locator('button:has-text("Delete")').last
                        if await confirm_btn.is_visible():
                            await confirm_btn.click()
                            print(f"✅ Deleted notebook: {nb_id}")
                            await page.wait_for_timeout(2000)
                        else:
                            print(f"⚠️ Could not find confirm button for: {nb_id}")
                    else:
                        print(f"⚠️ Could not find 'Delete notebook' option for: {nb_id}")
                else:
                    print(f"⚠️ Could not find menu button for: {nb_id}")
                    
            except Exception as e:
                print(f"❌ Error deleting {nb_id}: {e}")

        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python nb_cleaner.py id1 id2 ...")
        sys.exit(1)
        
    ids = sys.argv[1:]
    asyncio.run(delete_notebooks(ids))
