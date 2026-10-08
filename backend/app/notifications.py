"""Fail-closed email notifications for operational EPC events."""
from __future__ import annotations

import smtplib
from datetime import UTC, datetime, timezone
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
               actor_user_id: str | None = None,
               recipients: list[str] | None = None) -> bool:
    """Send one configured email and audit only a successful delivery.

    Disabled SMTP is a deliberate no-op, not an implicit localhost attempt.
    Callers can therefore calculate reminders on an air-gapped installation.
    """
    if not settings.smtp_enabled:
        return False
    _validate_runtime()
    recipient = ", ".join(sorted(set(recipients or []))) or settings.smtp_recipient.strip()
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


def send_risk_digest(created: list[dict], *, now: datetime | None = None) -> str:
    """ONE email for a whole detection run, never one per risk (#478).

    Returns "none" (nothing new), "disabled" (SMTP off: a deliberate no-op),
    "rate_limited" (a digest went out less than `risk_digest_min_interval_seconds`
    ago; the risks are in the register, only the email is skipped) or "sent".
    The body has counts and risk titles of the new risks, nothing else.
    """
    if not created:
        return "none"
    if not settings.smtp_enabled:
        return "disabled"
    current = (now or datetime.now(UTC)).astimezone(UTC)
    key = "risk_digest"
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS notification_schedule_runs (
            key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)""")
        row = conn.execute("SELECT sent_at FROM notification_schedule_runs WHERE key = ?",
                           (key,)).fetchone()
        if row is not None:
            try:
                last = datetime.fromisoformat(row["sent_at"].replace("Z", "+00:00"))
            except ValueError:
                last = None
            if last is not None and (current - last).total_seconds() < int(
                    settings.risk_digest_min_interval_seconds):
                return "rate_limited"
        # Reserve before sending, so two ticks cannot both send.
        conn.execute("INSERT OR REPLACE INTO notification_schedule_runs(key, sent_at) VALUES (?, ?)",
                     (key, current.isoformat(timespec="seconds").replace("+00:00", "Z")))
    counts: dict[str, int] = {}
    for item in created:
        counts[item["risk_type"]] = counts.get(item["risk_type"], 0) + 1
    lines = [f"EPC risk detection: {len(created)} new risk(s)"]
    lines += [f"{kind}: {n}" for kind, n in sorted(counts.items())]
    lines += ["", *[f"- {item['title']}" for item in created[:20]]]
    if len(created) > 20:
        lines.append(f"... and {len(created) - 20} more in the risk register")
    try:
        sent = send_email(subject=f"EPC risk digest: {len(created)} new", body="\n".join(lines),
                          trigger="automatic_risk_digest", resource_type="risk_digest",
                          resource_id=None)
    except Exception:
        with connect() as conn:
            conn.execute("DELETE FROM notification_schedule_runs WHERE key = ?", (key,))
        raise
    return "sent" if sent else "disabled"


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


def send_reminder(*, deliverable_id: str, title: str, due_date: str,
                  recipients: list[str] | None = None,
                  actor_user_id: str | None = None) -> bool:
    return send_email(subject=f"EPC deliverable reminder: {title}",
                      body=f"Deliverable {title} is due or overdue ({due_date}).",
                      trigger="overdue_deliverable", resource_type="deliverable",
                      resource_id=deliverable_id, recipients=recipients,
                      actor_user_id=actor_user_id)


def send_escalation(*, deliverable_id: str, title: str, level: int,
                    recipients: list[str] | None = None,
                    actor_user_id: str | None = None) -> bool:
    return send_email(subject=f"EPC escalation level {level}: {title}",
                      body=f"Deliverable {title} has reached escalation level {level}.",
                      trigger="escalation_level_change", resource_type="deliverable",
                      resource_id=deliverable_id, recipients=recipients,
                      actor_user_id=actor_user_id)


def run_scheduled_summary(summary: dict, *, now: datetime | None = None,
                          actor_user_id: str | None = None) -> bool:
    """Send at most one configured daily/weekly digest for the current window.

    This is deliberately a small idempotent job function: an existing worker or
    external scheduler can call it repeatedly without duplicate emails.
    """
    schedule = (settings.summary_schedule or "disabled").lower()
    if schedule not in {"daily", "weekly"}:
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current.hour != int(settings.summary_hour_utc):
        return False
    if schedule == "weekly" and current.weekday() != int(settings.summary_weekday_utc):
        return False
    window = current.strftime("%Y-%m-%d") if schedule == "daily" else current.strftime("%G-W%V")
    key = f"management_summary:{schedule}:{window}"
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS notification_schedule_runs (
            key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)""")
        if conn.execute("SELECT 1 FROM notification_schedule_runs WHERE key = ?", (key,)).fetchone():
            return False
        # Reserve before sending so two worker ticks cannot send duplicates.
        conn.execute("INSERT INTO notification_schedule_runs(key, sent_at) VALUES (?, ?)",
                     (key, _now()))
    try:
        sent = send_daily_summary(summary, actor_user_id=actor_user_id)
    except Exception:
        with connect() as conn:
            conn.execute("DELETE FROM notification_schedule_runs WHERE key = ?", (key,))
        raise
    if not sent:
        with connect() as conn:
            conn.execute("DELETE FROM notification_schedule_runs WHERE key = ?", (key,))
    return sent
