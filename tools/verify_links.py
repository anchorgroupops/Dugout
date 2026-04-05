"""
verify_links.py — Service connection verification for The Librarian.
Layer 3 Tool | NotebookLM Librarian

Run: python tools/verify_links.py
Expected: All critical checks return OK before running a full sync.
"""
import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).parent.parent))

MCP_EXE = (
    r"C:\Users\joely\AppData\Local\Packages"
    r"\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0"
    r"\LocalCache\local-packages\Python312\Scripts\notebooklm-mcp.exe"
)


def _ok(service, detail=""):
    icon = "[OK]"
    print(f"   {icon} {service}{f': {detail}' if detail else ''}")
    return {"service": service, "status": "ok", "detail": detail}


def _warn(service, detail=""):
    print(f"   [WARN] {service}{f': {detail}' if detail else ''}")
    return {"service": service, "status": "warning", "detail": detail}


def _fail(service, detail=""):
    print(f"   [FAIL] {service}{f': {detail}' if detail else ''}")
    return {"service": service, "status": "failed", "detail": detail}


# ── Individual checks ─────────────────────────────────────────────────────────

def check_mcp_exe() -> dict:
    print("Checking NotebookLM MCP executable...")
    if Path(MCP_EXE).exists():
        return _ok("MCP exe", Path(MCP_EXE).name)
    return _fail("MCP exe", f"Not found at {MCP_EXE}")


def check_registry() -> dict:
    print("Checking notebooks.json registry...")
    try:
        from tools.registry_manager import load
        registry = load()
        nb_count = len(registry["notebooks"])
        owned = sum(1 for nb in registry["notebooks"] if nb["ownership"] == "owned")
        return _ok("Registry", f"{nb_count} notebooks ({owned} owned)")
    except FileNotFoundError:
        return _warn("Registry", "notebooks.json not found — run initial sync first")
    except Exception as e:
        return _fail("Registry", str(e))


def check_youtube_rss() -> dict:
    print("Checking YouTube RSS feed...")
    test_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCWX3yGbODI3HqzDnVsOqCAg"
    try:
        req = Request(test_url, headers={"User-Agent": "NotebookLM-Librarian/1.0"})
        with urlopen(req, timeout=10) as resp:
            content = resp.read()
            if b"<feed" in content:
                return _ok("YouTube RSS")
            return _warn("YouTube RSS", "Unexpected response format")
    except URLError as e:
        return _fail("YouTube RSS", str(e))


def check_youtube_api() -> dict:
    print("Checking YouTube Data API v3...")
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return _warn("YouTube API", "YOUTUBE_API_KEY not set — topic notebooks disabled")
    test_url = f"https://www.googleapis.com/youtube/v3/videos?part=id&id=dQw4w9WgXcQ&key={api_key}"
    try:
        with urlopen(test_url, timeout=10) as resp:
            data = json.loads(resp.read())
            if "items" in data:
                return _ok("YouTube API", "key valid")
            return _warn("YouTube API", "Unexpected response")
    except Exception as e:
        err = str(e)
        if "403" in err:
            return _fail("YouTube API", "Invalid or quota-exceeded key")
        return _fail("YouTube API", err[:80])


def check_telegram() -> dict:
    print("Checking Telegram notification...")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return _warn("Telegram", "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                username = data.get("result", {}).get("username", "")
                return _ok("Telegram", f"@{username}")
            return _fail("Telegram", "Bot API returned not-ok")
    except Exception as e:
        return _fail("Telegram", str(e)[:80])


def check_postgresql() -> dict:
    print("Checking PostgreSQL sync logging...")
    try:
        from tools.db_sync import is_available, ensure_tables
        if is_available():
            ensure_tables()
            return _ok("PostgreSQL", "Connected and tables ready")
        return _warn("PostgreSQL", "psycopg2 not installed or DB unreachable — sync logging disabled")
    except Exception as e:
        return _warn("PostgreSQL", str(e)[:80])


def check_firecrawl() -> dict:
    print("Checking Firecrawl...")
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if key:
        return _ok("Firecrawl", "API key configured")
    return _warn("Firecrawl", "FIRECRAWL_API_KEY not set in .env (web scraping unavailable)")


# ── Runner ────────────────────────────────────────────────────────────────────

def run_all_checks() -> bool:
    print("\n" + "="*50)
    print("The Librarian -- Service Verification")
    print("="*50 + "\n")

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    results = [
        check_mcp_exe(),
        check_registry(),
        check_youtube_rss(),
        check_youtube_api(),
        check_telegram(),
        check_postgresql(),
        check_firecrawl(),
    ]

    print("\n" + "="*50)
    print("Summary:")
    critical_fail = False
    for r in results:
        icon = "[OK]  " if r["status"] == "ok" else ("[WARN] " if r["status"] == "warning" else "[FAIL] ")
        detail = r.get("detail", "")
        print(f"   {icon} {r['service']}{f': {detail}' if detail else ''}")
        # MCP exe and YouTube RSS are critical; others are optional
        if r["status"] == "failed" and r["service"] in ("MCP exe", "YouTube RSS"):
            critical_fail = True

    if critical_fail:
        print("\n[STOP] Fix critical failures before running sync.")
    else:
        print("\n[READY] Critical checks passed. Ready to sync.")

    return not critical_fail


if __name__ == "__main__":
    success = run_all_checks()
    sys.exit(0 if success else 1)
