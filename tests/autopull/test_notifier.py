"""Tests for tools.autopull.notifier — 3-channel fan-out."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
from tools.autopull import notifier as n


def _summary(outcome="success", failure_reason=None, drift="none"):
    return n.RunSummary(
        run_id=42,
        trigger="cron",
        outcome=outcome,
        failure_reason=failure_reason,
        csv_path="/tmp/x.csv" if outcome == "success" else None,
        rows_ingested=100 if outcome == "success" else None,
        duration_ms=2500,
        drift_severity=drift,
    )


def test_success_silent_on_email_and_push(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push,
                          status_webhook_url="https://x/y", notify_to_email="a@b")

    notifier.emit(_summary(outcome="success"))

    gmail.send.assert_not_called()
    push.notify.assert_not_called()
    n8n.post.assert_called_once()  # n8n always receives


def test_failure_fires_all_three(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push,
                          status_webhook_url="https://x/y", notify_to_email="a@b")

    notifier.emit(_summary(outcome="failure", failure_reason="auth expired"))

    gmail.send.assert_called_once()
    n8n.post.assert_called_once()
    push.notify.assert_called_once()


def test_critical_drift_fires_push_even_on_success(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push,
                          status_webhook_url="https://x/y", notify_to_email="a@b")

    notifier.emit(_summary(outcome="quarantined", drift="critical",
                           failure_reason="schema drift critical"))

    push.notify.assert_called_once()
    assert "drift" in push.notify.call_args[0][0].lower()


def test_advisory_drift_on_success_silent_push_but_emails(monkeypatch):
    gmail = MagicMock()
    n8n = MagicMock()
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push,
                          status_webhook_url="https://x/y", notify_to_email="a@b")

    notifier.emit(_summary(outcome="success", drift="advisory"))

    gmail.send.assert_called_once()   # advisory gets email
    push.notify.assert_not_called()   # but no push noise


def test_n8n_failure_does_not_break_other_channels(monkeypatch, caplog):
    gmail = MagicMock()
    n8n = MagicMock(); n8n.post.side_effect = RuntimeError("network")
    push = MagicMock()
    notifier = n.Notifier(gmail_sender=gmail, n8n_poster=n8n, pusher=push,
                          status_webhook_url="https://x/y", notify_to_email="a@b")
    notifier.emit(_summary(outcome="failure", failure_reason="x"))
    gmail.send.assert_called_once()
    push.notify.assert_called_once()
