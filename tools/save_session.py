"""
save_session.py — One-time interactive login to GameChanger.

Opens a headed browser, navigates to GC login, pre-fills your email,
then waits for you to manually enter the 2FA code + password and click
Sign In. Once authenticated, saves auth.json for all future scraper runs.

Usage:
    python save_session.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
AUTH_FILE = DATA_DIR / "auth.json"
GC_LOGIN = "https://web.gc.com/login"
GC_EMAIL = os.getenv("GC_EMAIL", "")

def main():
    print("=" * 60)
    print("GC Session Saver — Interactive Login")
    print("=" * 60)
    print(f"Email: {GC_EMAIL}")
    print()
    print("This will open a browser, fill in your email, and wait for")
    print("you to enter the 2FA code + password and click Sign In.")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        print("Opening browser...")
        page.goto(GC_LOGIN, wait_until="domcontentloaded", timeout=30000)

        # Pre-fill email and click Continue
        try:
            email_field = page.locator('input[type="email"], input[name="email"]').first
            email_field.wait_for(state="visible", timeout=10000)
            email_field.fill(GC_EMAIL)
            print(f"Email filled: {GC_EMAIL}")

            import re
            btn = page.get_by_role("button", name=re.compile("Continue|Sign in", re.I)).first
            if btn.count() > 0:
                btn.click()
                print("Clicked Continue — GC is sending a code to your email.")
            else:
                email_field.press("Enter")
                print("Pressed Enter — GC is sending a code to your email.")
        except Exception as e:
            print(f"Could not pre-fill email: {e}")
            print("Please log in manually in the browser window.")

        print()
        print("=" * 60)
        print("ACTION REQUIRED:")
        print("  1. Check the GC account email for the GameChanger code")
        print("  2. Enter the code + password in the browser window")
        print("  3. Click Sign In")
        print("  4. Wait for the page to reach /teams or /home")
        print("=" * 60)
        print()
        print("Waiting up to 3 minutes for you to complete login...")

        # Poll until we reach a confirmed authenticated URL (/home or /teams)
        authenticated = False
        for _ in range(180):  # 180 x 1s = 3 min
            url = page.url.lower()
            if any(p in url for p in ["/home", "/teams", "/schedule", "/stats", "/dashboard"]):
                authenticated = True
                print(f"\nAuthenticated! URL: {page.url}")
                break
            sys.stdout.write(".")
            sys.stdout.flush()
            page.wait_for_timeout(1000)

        if not authenticated:
            print("\nTimed out waiting for login. Exiting.")
            browser.close()
            return

        # Save session
        ctx.storage_state(path=str(AUTH_FILE))
        print(f"Session saved to {AUTH_FILE}")
        print()
        print("You can now run the scraper headlessly:")
        print("  python gc_full_scraper.py --schedule-only")
        print("  python gc_full_scraper.py")

        browser.close()


if __name__ == "__main__":
    main()
