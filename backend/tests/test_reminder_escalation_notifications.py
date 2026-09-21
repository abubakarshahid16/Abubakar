from app import notifications


def test_reminder_and_escalation_are_distinct_notification_entrypoints(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications, "send_email", lambda **kwargs: calls.append(kwargs) or True)
    assert notifications.send_reminder(deliverable_id="d", title="IFC", due_date="2026-09-17")
    assert notifications.send_escalation(deliverable_id="d", title="IFC", level=2)
    assert [call["trigger"] for call in calls] == ["overdue_deliverable", "escalation_level_change"]
