"""Fan-out notifications to email, n8n webhook, and PushNotification."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: int
    trigger: str
    outcome: str                    # 'success' | 'failure' | 'quarantined'
    failure_reason: str | None
    csv_path: str | None
    rows_ingested: int | None
    duration_ms: int | None
    drift_severity: str = "none"   # 'none' | 'advisory' | 'critical'


class GmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class N8nPoster(Protocol):
    def post(self, url: str, payload: dict) -> None: ...


class Pusher(Protocol):
    def notify(self, message: str) -> None: ...


class Notifier:
    def __init__(self, *, gmail_sender: GmailSender, n8n_poster: N8nPoster,
                 pusher: Pusher, status_webhook_url: str = "",
                 notify_to_email: str = ""):
        self._gmail = gmail_sender
        self._n8n = n8n_poster
        self._push = pusher
        self._status_url = status_webhook_url
        self._to = notify_to_email

    def emit(self, s: RunSummary) -> None:
        self._safe("n8n", lambda: self._post_n8n(s))
        is_failure = s.outcome in ("failure", "quarantined")
        is_advisory = s.drift_severity == "advisory"
        is_critical = s.drift_severity == "critical"
        if is_failure or is_advisory or is_critical:
            self._safe("email", lambda: self._send_email(s))
        if is_failure or is_critical:
            self._safe("push", lambda: self._push_alert(s))

    def _post_n8n(self, s: RunSummary) -> None:
        if not self._status_url:
            return
        self._n8n.post(self._status_url, asdict(s))

    def _send_email(self, s: RunSummary) -> None:
        if not self._to:
            return
        subject = f"[Dugout Autopull] {s.outcome.upper()} run #{s.run_id}"
        body_lines = [
            f"Run ID: {s.run_id}",
            f"Trigger: {s.trigger}",
            f"Outcome: {s.outcome}",
            f"Drift: {s.drift_severity}",
        ]
        if s.failure_reason:
            body_lines.append(f"Failure: {s.failure_reason}")
        if s.rows_ingested is not None:
            body_lines.append(f"Rows ingested: {s.rows_ingested}")
        if s.csv_path:
            body_lines.append(f"CSV: {s.csv_path}")
        if s.duration_ms is not None:
            body_lines.append(f"Duration: {s.duration_ms} ms")
        self._gmail.send(to=self._to, subject=subject,
                         body="\n".join(body_lines))

    def _push_alert(self, s: RunSummary) -> None:
        msg = self._short_message(s)
        self._push.notify(msg)

    @staticmethod
    def _short_message(s: RunSummary) -> str:
        if s.drift_severity == "critical":
            return f"GC schema drift CRITICAL (run #{s.run_id})"
        if s.outcome == "failure":
            return f"GC autopull failed: {s.failure_reason or 'unknown'} (#{s.run_id})"
        if s.outcome == "quarantined":
            return f"GC autopull quarantined: {s.failure_reason or 'bad CSV'} (#{s.run_id})"
        return f"GC autopull: {s.outcome} (#{s.run_id})"

    @staticmethod
    def _safe(channel: str, fn) -> None:
        try:
            fn()
        except Exception as e:
            log.exception("notifier channel %s failed: %s", channel, e)
