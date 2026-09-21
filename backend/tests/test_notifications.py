"""SMTP notification regressions: delivery is real, disabled is inert, and audited."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import db, deliverables, notifications
from app.config import NotificationConfigError, Settings, settings
from app.db import connect


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "notifications.sqlite")
    db.reset_connection()
    db.init_db()
    deliverables.ensure_schema()
    for name, value in {
        "smtp_enabled": False, "smtp_host": "", "smtp_port": 587,
        "smtp_username": "", "smtp_password": "", "smtp_from": "",
        "smtp_recipient": "", "smtp_starttls": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    yield
    db.reset_connection()


class FakeSMTP:
    sent: list[object] = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        assert username == "smtp-user"
        assert password == "smtp-password"

    def send_message(self, message):
        self.sent.append(message)


def _enable_smtp(monkeypatch):
    for name, value in {
        "smtp_enabled": True, "smtp_host": "smtp.example.test",
        "smtp_port": 587, "smtp_username": "smtp-user",
        "smtp_password": "smtp-password", "smtp_from": "epc@example.test",
        "smtp_recipient": "controls@example.test", "smtp_starttls": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    FakeSMTP.sent = []
    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)


def test_enabled_smtp_sends_and_writes_audit_event(monkeypatch):
    _enable_smtp(monkeypatch)
    assert notifications.send_email(
        subject="Overdue deliverable", body="Status required.",
        trigger="overdue_deliverable", resource_type="deliverable",
        resource_id="d-1") is True
    assert len(FakeSMTP.sent) == 1
    assert FakeSMTP.sent[0]["Subject"] == "Overdue deliverable"
    row = connect().execute(
        "SELECT action, resource_id, detail, outcome FROM audit_events"
        " WHERE action = 'notification.email'"
    ).fetchone()
    assert dict(row) == {
        "action": "notification.email", "resource_id": "d-1",
        "detail": "trigger=overdue_deliverable; recipient=controls@example.test",
        "outcome": "sent",
    }


def test_overdue_and_escalation_events_send_once_per_level(monkeypatch):
    _enable_smtp(monkeypatch)
    due = datetime.now(timezone.utc).date().isoformat()
    item = deliverables.create({
        "wbs_code": "1.1", "title": "Design submittal", "deliverable_type": "PDF",
        "due_date": due,
    }, created_by=None)
    first = deliverables.reminder_events()
    second = deliverables.reminder_events()
    assert len(first) == 1 and len(second) == 1
    assert len(FakeSMTP.sent) == 1, "UNIQUE reminder event must not email twice"
    assert item["id"] == first[0]["deliverable_id"]
    audit = connect().execute(
        "SELECT COUNT(*) AS n FROM audit_events WHERE action = 'notification.email'"
    ).fetchone()["n"]
    assert audit == 1


def test_escalation_level_change_uses_escalation_trigger(monkeypatch):
    _enable_smtp(monkeypatch)
    due = (datetime.now(timezone.utc).date() - timedelta(days=8)).isoformat()
    deliverables.create({
        "wbs_code": "1.2", "title": "Late design", "deliverable_type": "PDF",
        "due_date": due,
    }, created_by=None)
    deliverables.reminder_events()
    assert len(FakeSMTP.sent) == 1
    assert "escalation level 2" in FakeSMTP.sent[0]["Subject"].lower()
    audit = connect().execute(
        "SELECT detail FROM audit_events WHERE action = 'notification.email'"
    ).fetchone()["detail"]
    assert "trigger=escalation_level_change" in audit


def test_daily_summary_trigger_sends_and_is_audited(monkeypatch):
    _enable_smtp(monkeypatch)
    assert notifications.send_daily_summary({
        "deliverables_total": 4, "overdue_alerts": 1, "escalated_findings": 2,
    }) is True
    assert FakeSMTP.sent[0]["Subject"] == "EPC daily management summary"
    row = connect().execute(
        "SELECT detail FROM audit_events WHERE action = 'notification.email'"
    ).fetchone()
    assert "trigger=daily_summary" in row["detail"]


def test_disabled_smtp_is_a_noop_and_does_not_open_a_socket(monkeypatch):
    monkeypatch.setattr(notifications.smtplib, "SMTP", lambda *a, **k: pytest.fail("SMTP opened"))
    assert notifications.send_email(
        subject="x", body="y", trigger="daily_summary",
        resource_type="management_summary", resource_id=None) is False
    assert connect().execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_settings_fail_closed_when_smtp_is_incomplete():
    with pytest.raises(NotificationConfigError, match="SMTP_HOST"):
        Settings(smtp_enabled=True, smtp_from="a@example.test",
                 smtp_recipient="b@example.test")
