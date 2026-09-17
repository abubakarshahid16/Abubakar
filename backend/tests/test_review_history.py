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

