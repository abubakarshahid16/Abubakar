import pytest

from app import db, deliverables
from app.config import settings
from app.db import connect


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


def test_management_report_exports_operational_summary_pdf():
    deliverables.create(
        {"wbs_code": "3.1", "title": "Late management item", "deliverable_type": "report",
         "due_date": "2020-01-01", "status": "under_review"}, created_by="owner-1",
    )
    path = deliverables.render_management_report()
    try:
        pdf = __import__("fitz").open(str(path))
        text = "\n".join(page.get_text() for page in pdf)
        pdf.close()
        assert "EPC MANAGEMENT REPORT" in text
        assert "Late management item" in text
        assert "Overdue alerts: 1" in text
    finally:
        path.unlink(missing_ok=True)


def test_stakeholder_roles_migrate_owner_and_route_assignments():
    with connect() as conn:
        for user_id, email in (("owner", "owner@example.test"),
                               ("reviewer", "reviewer@example.test")):
            conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash,created_at)"
                " VALUES (?,?,?,?,?)", (user_id, email, user_id, "hash", "now"))
    item = deliverables.create({
        "wbs_code": "4.1", "title": "Review package", "deliverable_type": "PDF",
        "owner_user_id": "owner",
    }, created_by="owner")
    assert [row["role"] for row in deliverables.stakeholders(item["id"])] == ["owner"]
    assigned = deliverables.replace_stakeholders(item["id"], [
        {"user_id": "owner", "role": "owner"},
        {"user_id": "reviewer", "role": "reviewer"},
    ], actor_user_id="owner")
    assert {(row["user_id"], row["role"]) for row in assigned} == {
        ("owner", "owner"), ("reviewer", "reviewer")}


def test_wbs_parent_child_workspace_and_cycle_guard():
    parent = deliverables.create(
        {"wbs_code": "5.0", "title": "Design package", "deliverable_type": "package"},
        created_by="owner",
    )
    child = deliverables.create(
        {"wbs_code": "5.1", "parent_id": parent["id"], "title": "Structural submittal",
         "deliverable_type": "drawing"}, created_by="owner",
    )
    view = deliverables.workspace(parent["id"], allowed_document_ids=frozenset())
    assert view is not None
    assert [row["id"] for row in view["children"]] == [child["id"]]
    with pytest.raises(ValueError, match="cycle"):
        deliverables.update(parent["id"], {"parent_id": child["id"]})
