"""Tests for Gmail 2FA fetcher — pure logic, Gmail API mocked."""
from __future__ import annotations
import base64
from unittest.mock import MagicMock
import pytest
from tools.autopull import gmail_2fa_fetcher as g


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


def _message(body: str, message_id: str = "abc"):
    return {
        "id": message_id,
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": _b64(body)},
        },
    }


def test_extracts_six_digit_code():
    body = "Your GameChanger verification code is 482913. It expires in 10 minutes."
    assert g.extract_code(body) == "482913"


def test_ignores_other_numbers():
    body = "Confirm your account. Code: 123456. Order #9999 placed 04/22."
    assert g.extract_code(body) == "123456"


def test_returns_none_when_no_code():
    assert g.extract_code("Hi there, welcome to GameChanger.") is None


def test_fetch_latest_uses_gc_query():
    client = MagicMock()
    client.users().messages().list().execute.return_value = {
        "messages": [{"id": "m1"}]
    }
    client.users().messages().get().execute.return_value = _message(
        "Your verification code is 654321."
    )
    code, msg_id = g.fetch_latest_code(client, lookback_minutes=5)
    assert code == "654321"
    assert msg_id == "m1"
    # Query must target GC sender and recent window
    list_call = client.users().messages().list.call_args
    assert "from:no-reply@gc.com" in list_call.kwargs["q"]


def test_fetch_latest_returns_none_when_no_messages():
    client = MagicMock()
    client.users().messages().list().execute.return_value = {"messages": []}
    code, msg_id = g.fetch_latest_code(client, lookback_minutes=5)
    assert code is None
    assert msg_id is None


def test_mark_read_removes_unread_label():
    client = MagicMock()
    g.mark_read(client, "m1")
    client.users().messages().modify.assert_called_once()
    kwargs = client.users().messages().modify.call_args.kwargs
    assert kwargs["body"] == {"removeLabelIds": ["UNREAD"]}


def test_send_email_formats_message():
    client = MagicMock()
    g.send_email(client, sender="me@x.com", to="you@x.com",
                 subject="Hello", body="Body text")
    client.users().messages().send.assert_called_once()
    kwargs = client.users().messages().send.call_args.kwargs
    assert "raw" in kwargs["body"]
