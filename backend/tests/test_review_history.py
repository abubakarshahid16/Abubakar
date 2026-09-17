"""Review workflow history is immutable and queryable."""

import pytest

from app import db, review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _document() -> None:
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("doc-1", "submittal.pdf", "hash-1", 1, "submittal.pdf",
             "ready", "2026-09-17T00:00:00Z"),
        )


def test_finding_history_records_creation_and_updates():
    _document()
    finding = review.create(
        {
            "document_id": "doc-1",
            "category": "design",
            "severity": "major",
            "requirement": "Submit calculations",
            "finding": "Calculation package is missing",
            "required_action": "Provide the package",
        },
        created_by="engineer-1",
    )

    review.update(
        finding["id"],
        {"status": "in_progress", "response_text": "Package due Friday"},
        actor_user_id="engineer-2",
    )

    events = review.history(finding["id"])
    assert [event["event_type"] for event in events] == ["created", "updated"]
    assert events[0]["actor_user_id"] == "engineer-1"
    assert events[1]["actor_user_id"] == "engineer-2"
    assert events[1]["changes"] == {
        "status": "in_progress",
        "response_text": "Package due Friday",
    }


def test_review_templates_are_versioned_and_filterable():
    first = review.create_template(
        {
            "name": "Civil submittal",
            "version": "1.0",
            "discipline": "civil",
            "governing_sources": ["Project specification §01 33 00"],
            "categories": ["document_control", "requirement_deviation"],
            "severity_levels": ["critical", "major", "minor"],
            "approval_terms": ["accepted", "rejected"],
            "required_sections": ["finding", "required action", "response"],
        },
        created_by="admin-1",
    )
    second = review.create_template(
        {"name": "Civil submittal", "version": "2.0", "discipline": "civil"},
        created_by="admin-1",
    )

    templates = review.list_templates(discipline="civil")
    assert [item["version"] for item in templates] == ["2.0", "1.0"]
    assert templates[-1]["id"] == first["id"]
    assert second["active"] is True
    assert templates[-1]["governing_sources"] == ["Project specification §01 33 00"]


def test_finding_inherits_governing_sources_from_selected_template():
    template = review.create_template(
        {"name": "Electrical submittal", "version": "1.0",
         "governing_sources": ["IEC 60364", "Project specification §26 05 00"]},
        created_by="admin-1",
    )
    _document()
    finding = review.create(
        {"document_id": "doc-1", "template_id": template["id"],
         "category": "requirement_deviation", "severity": "major",
         "requirement": "Use approved cable type", "finding": "Cable type is not stated",
         "required_action": "Confirm cable schedule"},
        created_by="engineer-1",
    )
    assert finding["template_id"] == template["id"]
    assert finding["governing_sources"] == ["IEC 60364", "Project specification §26 05 00"]
