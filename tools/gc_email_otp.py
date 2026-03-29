"""
gc_email_otp.py — Auto-read GameChanger 2FA codes from email via IMAP.

Connects to Gmail (or any IMAP server) and retrieves the latest OTP code
sent by GameChanger. Used by gc_scraper.py and gc_full_scraper.py when
2FA is triggered during login.

Requires:
  GC_IMAP_EMAIL       — Gmail address (e.g. fly386@gmail.com)
  GC_IMAP_APP_PASSWORD — Google App Password (NOT your regular password)

Generate an App Password at: https://myaccount.google.com/apppasswords
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

IMAP_HOST = os.getenv("GC_IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("GC_IMAP_PORT", "993"))
IMAP_EMAIL = os.getenv("GC_IMAP_EMAIL", os.getenv("GC_EMAIL", "")).strip()
IMAP_PASSWORD = os.getenv("GC_IMAP_APP_PASSWORD", "").strip()

# GameChanger sender patterns
_GC_SENDER_PATTERNS = [
    "gamechanger",
    "gc.com",
    "no-reply@gc.com",
    "noreply@gc.com",
    "team-manager",
]

# Regex to find a 6-digit OTP code in the email body
_OTP_RE = re.compile(r"\b(\d{6})\b")


def is_configured() -> bool:
    """Return True if IMAP credentials are set."""
    return bool(IMAP_EMAIL and IMAP_PASSWORD)


def _connect() -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP connection."""
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(IMAP_EMAIL, IMAP_PASSWORD)
    return conn


def _is_gc_sender(from_header: str) -> bool:
    """Check if the From header matches known GameChanger senders."""
    lower = from_header.lower()
    return any(pat in lower for pat in _GC_SENDER_PATTERNS)


def _extract_otp(body: str) -> str | None:
    """Extract a 6-digit code from the email body."""
    # Look for patterns like "verification code: 123456" or just a standalone 6-digit number
    # Prefer codes near keywords
    for pattern in [
        r"(?:code|verification|verify|confirm)[:\s]+(\d{6})",
        r"(\d{6})",
    ]:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _get_email_body(msg: email.message.Message) -> str:
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
            elif ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    # Strip HTML tags for simple extraction
                    text = re.sub(r"<[^>]+>", " ", payload.decode("utf-8", errors="replace"))
                    return text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
    return ""


def fetch_latest_otp(
    max_wait_seconds: int = 90,
    poll_interval: int = 5,
    since_minutes: int = 5,
) -> str | None:
    """
    Poll IMAP for the latest GameChanger OTP code.

    Args:
        max_wait_seconds: How long to keep polling before giving up.
        poll_interval: Seconds between polls.
        since_minutes: Only consider emails received in the last N minutes.

    Returns:
        The 6-digit OTP code as a string, or None if not found.
    """
    if not is_configured():
        print("[OTP] IMAP not configured (missing GC_IMAP_EMAIL or GC_IMAP_APP_PASSWORD)")
        return None

    print(f"[OTP] Polling {IMAP_EMAIL} for GameChanger verification code...")
    deadline = time.time() + max_wait_seconds
    best_code = None
    best_date = None

    while time.time() < deadline:
        try:
            conn = _connect()
            conn.select("INBOX", readonly=True)

            # Search for recent emails (IMAP SINCE uses date only, not time)
            since_date = datetime.now(timezone.utc).strftime("%d-%b-%Y")
            _status, msg_ids = conn.search(None, f'(SINCE "{since_date}")')

            if msg_ids and msg_ids[0]:
                ids = msg_ids[0].split()
                # Check most recent emails first (last N)
                for msg_id in reversed(ids[-20:]):
                    _status, data = conn.fetch(msg_id, "(RFC822)")
                    if not data or not data[0] or not isinstance(data[0], tuple):
                        continue
                    raw = data[0][1]
                    msg = email.message_from_bytes(raw)

                    from_header = msg.get("From", "")
                    if not _is_gc_sender(from_header):
                        continue

                    # Check if email is recent enough
                    date_str = msg.get("Date", "")
                    try:
                        msg_date = email.utils.parsedate_to_datetime(date_str)
                        age_minutes = (datetime.now(timezone.utc) - msg_date).total_seconds() / 60
                        if age_minutes > since_minutes:
                            continue
                    except Exception:
                        pass  # If we can't parse the date, still try

                    body = _get_email_body(msg)
                    code = _extract_otp(body)
                    if code:
                        # Track the newest code
                        try:
                            msg_dt = email.utils.parsedate_to_datetime(date_str)
                        except Exception:
                            msg_dt = datetime.now(timezone.utc)
                        if best_date is None or msg_dt > best_date:
                            best_code = code
                            best_date = msg_dt

            conn.close()
            conn.logout()

            if best_code:
                print(f"[OTP] Found verification code: {'*' * 6}")
                return best_code

        except imaplib.IMAP4.error as e:
            print(f"[OTP] IMAP error: {e}")
            return None
        except Exception as e:
            print(f"[OTP] Error checking email: {e}")

        remaining = int(deadline - time.time())
        if remaining > 0:
            print(f"[OTP] No code yet, retrying in {poll_interval}s ({remaining}s remaining)...")
            time.sleep(poll_interval)

    print("[OTP] Timed out waiting for verification code email.")
    return None


if __name__ == "__main__":
    if not is_configured():
        print("IMAP not configured. Set GC_IMAP_EMAIL and GC_IMAP_APP_PASSWORD in .env")
        print()
        print("To generate a Google App Password:")
        print("  1. Go to myaccount.google.com/apppasswords")
        print("  2. Create an app password named 'Softball Scraper'")
        print("  3. Add to .env: GC_IMAP_APP_PASSWORD=xxxx xxxx xxxx xxxx")
    else:
        print(f"IMAP configured for {IMAP_EMAIL}")
        print("Testing connection...")
        try:
            conn = _connect()
            conn.select("INBOX", readonly=True)
            _status, msg_ids = conn.search(None, "ALL")
            count = len(msg_ids[0].split()) if msg_ids and msg_ids[0] else 0
            conn.close()
            conn.logout()
            print(f"Connected successfully. {count} messages in INBOX.")
        except Exception as e:
            print(f"Connection failed: {e}")
