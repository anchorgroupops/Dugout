from playwright.sync_api import sync_playwright

def test():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://example.com")
            print(f"Success! Title: {page.title()}")
            browser.close()
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test()
