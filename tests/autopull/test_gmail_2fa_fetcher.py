"""Tests for IMAP/SMTP-based Gmail 2FA fetcher + sender."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import email
import pytest
from tools.autopull import gmail_2fa_fetcher as g


def _build_raw_email(body: str, sender: str = "no-reply@gc.com") -> bytes:
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "fly386@gmail.com"
    m["Subject"] = "Verify your GameChanger account"
    m.set_content(body)
    return m.as_bytes()


def test_extracts_six_digit_code():
    body = "Your GameChanger verification code is 482913. It expires in 10 minutes."
    assert g.extract_code(body) == "482913"


def test_ignores_other_numbers():
    body = "Confirm your account. Code: 123456. Order #9999 placed 04/22."
    assert g.extract_code(body) == "123456"


def test_returns_none_when_no_code():
    assert g.extract_code("Hi there, welcome to GameChanger.") is None


def test_fetch_latest_code_scans_newest_first():
    client = MagicMock()
    client.uid.side_effect = [
        ("OK", [b"100 101 102"]),                   # SEARCH returns 3 UIDs
        ("OK", [(b"102", _build_raw_email(
            "Your verification code is 654321."))]),
    ]
    code, uid = g.fetch_latest_code(client, lookback_minutes=5)
    assert code == "654321"
    assert uid == "102"
    # First call: SEARCH by sender
    assert client.uid.call_args_list[0].args[0] == "SEARCH"
    assert "no-reply@gc.com" in client.uid.call_args_list[0].args[2]


def test_fetch_latest_code_returns_none_when_no_messages():
    client = MagicMock()
    client.uid.return_value = ("OK", [b""])
    code, uid = g.fetch_latest_code(client, lookback_minutes=5)
    assert code is None
    assert uid is None


def test_fetch_latest_code_skips_codeless_emails():
    client = MagicMock()
    client.uid.side_effect = [
        ("OK", [b"50 51"]),
        ("OK", [(b"51", _build_raw_email(
            "Welcome to GameChanger — confirm your account."))]),
        ("OK", [(b"50", _build_raw_email(
            "Your code is 987654. Expires soon."))]),
    ]
    code, uid = g.fetch_latest_code(client, lookback_minutes=5)
    assert code == "987654"
    assert uid == "50"


def test_mark_read_stores_seen_flag():
    client = MagicMock()
    g.mark_read(client, "102")
    client.uid.assert_called_once_with("STORE", "102", "+FLAGS", "\\Seen")


def test_build_client_logs_in_and_selects_inbox():
    with patch("imaplib.IMAP4_SSL") as mock_imap:
        inst = MagicMock()
        mock_imap.return_value = inst
        client = g.build_client(username="fly386@gmail.com",
                                app_password="abcd efgh ijkl mnop")
    mock_imap.assert_called_once_with(g.IMAP_HOST, g.IMAP_PORT)
    # App password should have spaces stripped
    inst.login.assert_called_once_with("fly386@gmail.com", "abcdefghijklmnop")
    inst.select.assert_called_once_with("INBOX")


def test_send_email_uses_smtp_with_app_password():
    with patch("smtplib.SMTP_SSL") as mock_smtp:
        smtp_inst = MagicMock()
        mock_smtp.return_value.__enter__.return_value = smtp_inst
        g.send_email(
            username="fly386@gmail.com",
            app_password="abcd efgh ijkl mnop",
            sender="fly386@gmail.com",
            to="anchorgroupops@gmail.com",
            subject="Hello",
            body="Body text",
        )
    mock_smtp.assert_called_once_with(g.SMTP_HOST, g.SMTP_PORT)
    smtp_inst.login.assert_called_once_with("fly386@gmail.com", "abcdefghijklmnop")
    smtp_inst.send_message.assert_called_once()
