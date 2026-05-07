"""Tests for IMAP/SMTP-based Gmail 2FA fetcher + sender."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import email
import pytest
from tools.autopull import gmail_2fa_fetcher as g


def _build_raw_email(body: str, sender: str = "gamechanger-noreply@info.gc.com",
                     subject: str = "Verify your GameChanger account") -> bytes:
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "fly386@gmail.com"
    m["Subject"] = subject
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
            "body text",
            subject="Your GameChanger code is 654321"))]),
    ]
    code, uid = g.fetch_latest_code(client, lookback_minutes=5)
    assert code == "654321"   # picked up from subject
    assert uid == "102"
    # First call: SEARCH by sender DOMAIN
    assert client.uid.call_args_list[0].args[0] == "SEARCH"
    assert any("info.gc.com" in str(a) for a in client.uid.call_args_list[0].args)


def test_fetch_latest_code_falls_back_to_body():
    client = MagicMock()
    client.uid.side_effect = [
        ("OK", [b"50"]),
        ("OK", [(b"50", _build_raw_email(
            "Your verification code is 987654. Expires soon.",
            subject="GameChanger notification"))]),
    ]
    code, uid = g.fetch_latest_code(client, lookback_minutes=5)
    assert code == "987654"
    assert uid == "50"


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
            "Welcome to GameChanger — confirm your account.",
            subject="Welcome to GameChanger"))]),
        ("OK", [(b"50", _build_raw_email(
            "Your code is 987654. Expires soon.",
            subject="Your GameChanger code is 987654"))]),
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


# ---------------------------------------------------------------------------
# current_max_uid
# ---------------------------------------------------------------------------

def test_current_max_uid_returns_max():
    client = MagicMock()
    client.uid.return_value = ("OK", [b"101 205 150"])
    result = g.current_max_uid(client)
    assert result == 205


def test_current_max_uid_returns_zero_when_no_messages():
    client = MagicMock()
    client.uid.return_value = ("OK", [b""])
    result = g.current_max_uid(client)
    assert result == 0


def test_current_max_uid_returns_zero_on_non_ok():
    client = MagicMock()
    client.uid.return_value = ("NO", [b""])
    result = g.current_max_uid(client)
    assert result == 0


def test_current_max_uid_single_uid():
    client = MagicMock()
    client.uid.return_value = ("OK", [b"42"])
    result = g.current_max_uid(client)
    assert result == 42


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

def test_extract_text_from_simple_plain_message():
    from email.message import EmailMessage
    m = EmailMessage()
    m.set_content("Hello from GC!")
    result = g._extract_text(m)
    assert "Hello from GC!" in result


def test_extract_text_from_multipart_message():
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("Plain text content", "plain"))
    msg.attach(MIMEText("<b>HTML content</b>", "html"))
    result = g._extract_text(msg)
    assert "Plain text content" in result
    assert "<b>" not in result  # HTML part skipped


def test_extract_text_returns_empty_for_html_only():
    from email.mime.text import MIMEText
    msg = MIMEText("<h1>Only HTML</h1>", "html")
    result = g._extract_text(msg)
    assert result == ""


def test_extract_text_returns_string():
    from email.message import EmailMessage
    m = EmailMessage()
    m.set_content("test")
    assert isinstance(g._extract_text(m), str)


def test_fetch_returns_none_when_uids_empty_after_split():
    """SEARCH returns a whitespace-only payload: uids list is empty after split."""
    client = MagicMock()
    client.uid.return_value = ("OK", [b"   "])  # truthy but no real UIDs
    code, uid = g.fetch_latest_code(client)
    assert code is None
    assert uid is None


def test_fetch_min_uid_filters_all_older_messages():
    """min_uid > 0 and all UIDs are <= min_uid — returns None, None."""
    client = MagicMock()
    client.uid.return_value = ("OK", [b"10 20 30"])
    code, uid = g.fetch_latest_code(client, min_uid=100)
    assert code is None
    assert uid is None


def test_fetch_min_uid_keeps_newer_messages():
    """min_uid filters out older UIDs but newer one with code is kept."""
    client = MagicMock()
    client.uid.side_effect = [
        ("OK", [b"10 20 200"]),
        ("OK", [(b"200", _build_raw_email(
            "Your code is 112233",
            subject="GameChanger code 112233"))]),
    ]
    code, uid = g.fetch_latest_code(client, min_uid=100)
    assert code == "112233"


def test_fetch_continues_on_bad_fetch_result():
    """When FETCH returns non-OK for a UID, it should continue to the next."""
    client = MagicMock()
    client.uid.side_effect = [
        ("OK", [b"50 51"]),
        ("NO", [None]),   # FETCH 51 fails
        ("OK", [(b"50", _build_raw_email(
            "Your code is 998877", subject="Code 998877"))]),
    ]
    code, uid = g.fetch_latest_code(client)
    assert code == "998877"


def test_fetch_noop_exception_is_ignored():
    """If client.noop() raises, the exception is swallowed."""
    client = MagicMock()
    client.noop.side_effect = OSError("NOOP failed")
    client.uid.side_effect = [
        ("OK", [b"42"]),
        ("OK", [(b"42", _build_raw_email("code: 654321", subject="code 654321"))]),
    ]
    code, uid = g.fetch_latest_code(client)
    assert code == "654321"


def test_fetch_all_emails_have_no_code_returns_none():
    """All fetched emails lack a 6-digit code — returns None, None."""
    client = MagicMock()
    client.uid.side_effect = [
        ("OK", [b"50"]),
        ("OK", [(b"50", _build_raw_email(
            "Welcome to GameChanger!", subject="Welcome!"))]),
    ]
    code, uid = g.fetch_latest_code(client)
    assert code is None
    assert uid is None
