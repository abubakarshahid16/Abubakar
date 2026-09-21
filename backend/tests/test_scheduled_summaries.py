from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import db, notifications
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "scheduled.sqlite")
    db.reset_connection(); db.init_db()
    yield
    db.reset_connection()


def test_daily_summary_is_idempotent_per_window(monkeypatch):
    settings.summary_schedule = "daily"
    settings.summary_hour_utc = 8
    sent = []
    monkeypatch.setattr(notifications, "send_daily_summary", lambda summary, **_: sent.append(summary) or True)
    when = datetime(2026, 9, 17, 8, 5, tzinfo=timezone.utc)
    assert notifications.run_scheduled_summary({"overdue_alerts": 2}, now=when)
    assert not notifications.run_scheduled_summary({"overdue_alerts": 2}, now=when)
    assert len(sent) == 1


def test_weekly_summary_waits_for_configured_weekday_and_hour(monkeypatch):
    settings.summary_schedule = "weekly"
    settings.summary_hour_utc = 8
    settings.summary_weekday_utc = 0
    monkeypatch.setattr(notifications, "send_daily_summary", lambda *_a, **_k: True)
    monday = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
    assert notifications.run_scheduled_summary({}, now=monday)
    assert not notifications.run_scheduled_summary({}, now=monday)
    assert not notifications.run_scheduled_summary({}, now=monday.replace(hour=9))
