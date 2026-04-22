"""Gmail 2FA reader + notification sender via IMAP/SMTP + app password.

Phase 1-rc2: swapped OAuth for an app password. App passwords are simpler
to provision on iPhone (no consent flow, no Testing-mode test-user list),
and for a dedicated utility account like fly386@gmail.com the tighter
scope of OAuth isn't worth the operator friction.

Provisioning (one time, by the human):
  https://myaccount.google.com/apppasswords → generate → copy 16 chars.

Env keys consumed:
  GMAIL_USERNAME      — full email (e.g. fly386@gmail.com)
  GMAIL_APP_PASSWORD  — 16-char app password, spaces optional
"""
from __future__ import annotations
import email
import imaplib
import logging
import re
import smtplib
from email.message import EmailMessage
from typing import Any

log = logging.getLogger(__name__)

CODE_RE = re.compile(r"\b(\d{6})\b")
GC_SENDER = "no-reply@gc.com"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def build_client(*, username: str, app_password: str) -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP SSL connection and select INBOX.

    Caller is responsible for calling .logout() when done.
    """
    client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    # App passwords are tolerant of spaces; strip to be safe.
    client.login(username, app_password.replace(" ", ""))
    client.select("INBOX")
    return client


def fetch_latest_code(
    client: imaplib.IMAP4_SSL, *, lookback_minutes: int = 5
) -> tuple[str | None, str | None]:
    """Return (code, message_uid) for the latest GC 2FA email, or (None, None).

    IMAP SEARCH filters by date (day granularity), so we rely on the sort
    order of returned UIDs for the ~5-minute recency filter and additionally
    walk from newest backwards.
    """
    typ, data = client.uid("SEARCH", None, f'FROM "{GC_SENDER}"')
    if typ != "OK" or not data or not data[0]:
        return None, None
    uids = data[0].split()
    if not uids:
        return None, None

    # Newest first
    for uid in reversed(uids[-10:]):  # cap scanned emails
        typ, msg_data = client.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
        try:
            msg = email.message_from_bytes(raw)
        except Exception:  # pragma: no cover — defensive
            continue
        body = _extract_text(msg)
        code = extract_code(body)
        if code:
            return code, uid.decode() if isinstance(uid, bytes) else str(uid)
    return None, None


def extract_code(body: str) -> str | None:
    for m in CODE_RE.finditer(body):
        return m.group(1)
    return None


def mark_read(client: imaplib.IMAP4_SSL, message_uid: str) -> None:
    client.uid("STORE", message_uid, "+FLAGS", "\\Seen")


def send_email(*, username: str, app_password: str,
               sender: str, to: str, subject: str, body: str) -> None:
    """Send a plain-text email via Gmail SMTP using the same app password."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
        s.login(username, app_password.replace(" ", ""))
        s.send_message(msg)


def _extract_text(msg: "email.message.Message") -> str:
    """Walk a parsed email message and concatenate text/plain bodies."""
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    parts.append(part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    ))
                except Exception:
                    continue
    else:
        if msg.get_content_type() == "text/plain":
            try:
                parts.append(msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                ))
            except Exception:
                pass
    return "\n".join(parts)
