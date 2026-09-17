"""Fail-closed email notifications for operational EPC events."""
from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from .config import NotificationConfigError, settings
from .db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit(*, trigger: str, resource_type: str, resource_id: str | None,
           recipient: str, outcome: str, actor_user_id: str | None = None) -> None:
    # Recipients and trigger metadata are operational facts; message bodies are
    # deliberately excluded because audit_events is routinely exported.
    with connect() as conn:
        conn.execute(
            """INSERT INTO audit_events
               (at, actor_user_id, actor_username, action, resource_type,
                resource_id, detail, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (_now(), actor_user_id, "system", "notification.email",
             resource_type, resource_id,
             f"trigger={trigger}; recipient={recipient}", outcome),
        )


def _validate_runtime() -> None:
    if not settings.smtp_enabled:
        raise NotificationConfigError("SMTP notifications are disabled")
    if not settings.smtp_host or not settings.smtp_from or not settings.smtp_recipient:
        raise NotificationConfigError(
            "SMTP notifications require SMTP_HOST, SMTP_FROM and SMTP_RECIPIENT")
    if not 1 <= int(settings.smtp_port) <= 65535:
        raise NotificationConfigError("SMTP_PORT must be between 1 and 65535")
    if bool(settings.smtp_username) != bool(settings.smtp_password):
        raise NotificationConfigError(
            "SMTP_USERNAME and SMTP_PASSWORD must be provided together")


def send_email(*, subject: str, body: str, trigger: str,
               resource_type: str, resource_id: str | None,
               actor_user_id: str | None = None) -> bool:
    """Send one configured email and audit only a successful delivery.

    Disabled SMTP is a deliberate no-op, not an implicit localhost attempt.
    Callers can therefore calculate reminders on an air-gapped installation.
    """
    if not settings.smtp_enabled:
        return False
    _validate_runtime()
    recipient = settings.smtp_recipient.strip()
    message = EmailMessage()
    message["From"] = settings.smtp_from.strip()
    message["To"] = recipient
    message["Subject"] = subject[:200]
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                          timeout=settings.smtp_timeout_seconds) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except Exception:
        _audit(trigger=trigger, resource_type=resource_type,
               resource_id=resource_id, recipient=recipient, outcome="failed",
               actor_user_id=actor_user_id)
        raise
    _audit(trigger=trigger, resource_type=resource_type,
           resource_id=resource_id, recipient=recipient, outcome="sent",
           actor_user_id=actor_user_id)
    return True


def send_daily_summary(summary: dict, *, actor_user_id: str | None = None) -> bool:
    """Send the current management summary as an operator-triggered digest."""
    lines = [
        "EPC daily management summary",
        f"Deliverables: {summary.get('deliverables_total', 0)}",
        f"Overdue alerts: {summary.get('overdue_alerts', 0)}",
        f"Escalated findings: {summary.get('escalated_findings', 0)}",
    ]
    return send_email(subject="EPC daily management summary", body="\n".join(lines),
                      trigger="daily_summary", resource_type="management_summary",
                      resource_id=None, actor_user_id=actor_user_id)
