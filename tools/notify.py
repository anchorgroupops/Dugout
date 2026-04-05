"""
notify.py — Telegram notification tool for The Librarian.
Layer 3 Tool | NotebookLM Librarian

Sends sync completion and error alerts to a Telegram chat via the Bot API.
Configure in .env:
    TELEGRAM_BOT_TOKEN=<token>
    TELEGRAM_CHAT_ID=<chat_id>   # Get by messaging @userinfobot

Silently skips if either env var is missing.
"""
import json
import os
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(message: str, chat_id: str = None, token: str = None) -> bool:
    """
    Send a Telegram message. Returns True on success, False if unconfigured or failed.
    message supports Telegram MarkdownV2 formatting.
    """
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        return False  # Not configured — silent skip

    url = TELEGRAM_API.format(token=token)
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }).encode("utf-8")

    try:
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return bool(result.get("ok"))
    except (URLError, Exception) as e:
        # Notification failures are non-fatal — log and continue
        print(f"[NOTIFY] Telegram send failed: {e}")
        return False


def notify_sync_complete(
    total_added: int,
    total_failed: int,
    notebooks_synced: int,
    duration_secs: float,
    dry_run: bool = False,
) -> bool:
    mode = "[DRY RUN] " if dry_run else ""
    status = "OK" if total_failed == 0 else f"PARTIAL ({total_failed} failed)"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = (
        f"*{mode}The Librarian Sync Complete*\n"
        f"Status: `{status}`\n"
        f"Added: `{total_added}` sources across `{notebooks_synced}` notebooks\n"
        f"Duration: `{duration_secs:.0f}s`\n"
        f"Time: `{ts}`"
    )
    return send_telegram(msg)


def notify_error(context: str, error: str) -> bool:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = (
        f"*The Librarian ERROR*\n"
        f"Context: `{context}`\n"
        f"Error: `{error[:300]}`\n"
        f"Time: `{ts}`"
    )
    return send_telegram(msg)


def notify_circuit_open(notebook_title: str, consecutive_failures: int) -> bool:
    msg = (
        f"*The Librarian - Circuit Breaker*\n"
        f"Notebook: `{notebook_title}`\n"
        f"Stopped after `{consecutive_failures}` consecutive failures\n"
        f"Check NotebookLM session or API status"
    )
    return send_telegram(msg)


if __name__ == "__main__":
    # Test: python tools/notify.py
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

    def _load_env():
        env = __import__("pathlib").Path(__file__).parent.parent / ".env"
        if env.exists():
            with open(env) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip())

    _load_env()
    ok = send_telegram("*The Librarian* — Notification test OK")
    print(f"[NOTIFY] Test {'sent' if ok else 'skipped (TELEGRAM_BOT_TOKEN/CHAT_ID not set)'}")
