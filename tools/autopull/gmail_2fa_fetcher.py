"""Headless Gmail helper to read GameChanger 2FA verification codes
and to send plain-text notification emails.

Uses a Gmail OAuth refresh token (not the claude.ai MCP) so the Pi can run
unattended. Read scope is limited to no-reply@gc.com within a short window.
"""
from __future__ import annotations
import base64
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

CODE_RE = re.compile(r"\b(\d{6})\b")
GC_SENDER = "no-reply@gc.com"


def build_client(*, client_id: str, client_secret: str, refresh_token: str) -> Any:
    """Build a Gmail API client from OAuth credentials.

    Separated so tests can mock by passing their own client object.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def fetch_latest_code(client: Any, *, lookback_minutes: int = 5) -> tuple[str | None, str | None]:
    """Return (code, message_id) for the latest GC 2FA email, or (None, None)."""
    q = f"from:{GC_SENDER} newer_than:{lookback_minutes}m"
    resp = client.users().messages().list(userId="me", q=q, maxResults=5).execute()
    messages = resp.get("messages", []) or []
    for m in messages:
        mid = m["id"]
        msg = client.users().messages().get(
            userId="me", id=mid, format="full"
        ).execute()
        body = _extract_text(msg.get("payload", {}))
        code = extract_code(body)
        if code:
            return code, mid
    return None, None


def extract_code(body: str) -> str | None:
    for m in CODE_RE.finditer(body):
        return m.group(1)
    return None


def mark_read(client: Any, message_id: str) -> None:
    client.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def send_email(client: Any, *, sender: str, to: str, subject: str, body: str) -> None:
    """Send a plain-text email via the same Gmail client used for 2FA reads."""
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    client.users().messages().send(userId="me", body={"raw": raw}).execute()


def _extract_text(payload: dict) -> str:
    """Walk a Gmail message payload and concatenate text/plain bodies."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    parts = payload.get("parts") or []
    return "\n".join(_extract_text(p) for p in parts)
