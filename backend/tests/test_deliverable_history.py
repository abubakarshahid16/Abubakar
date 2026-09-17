import pytest

from app import db, deliverables
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def test_deliverable_revision_history_is_preserved():
    item = deliverables.create(
        {"wbs_code": "1.1", "title": "30% design", "deliverable_type": "submittal", "revision": "A"},
        created_by="owner-1",
    )
    deliverables.update(item["id"], {"revision": "B", "status": "under_review"}, actor_user_id="owner-2")
    events = deliverables.history(item["id"])
    assert [event["event_type"] for event in events] == ["created", "updated"]
    assert events[1]["changes"] == {"revision": "B", "status": "under_review"}
    assert events[1]["actor_user_id"] == "owner-2"


def test_overdue_deliverable_creates_acknowledgeable_reminder():
    item = deliverables.create(
        {"wbs_code": "2.1", "title": "Late submittal", "deliverable_type": "drawing",
         "due_date": "2020-01-01", "status": "under_review"}, created_by="owner-1",
    )
    reminders = deliverables.reminder_events()
    assert len(reminders) == 1
    assert reminders[0]["deliverable_id"] == item["id"]
    assert reminders[0]["status"] == "pending"
    acknowledged = deliverables.acknowledge_reminder(reminders[0]["id"])
    assert acknowledged is not None
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_at"] is not None
