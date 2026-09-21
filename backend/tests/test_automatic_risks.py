from __future__ import annotations

from app import db, deliverables, review, risks


def _setup(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "automatic-risks.sqlite")
    db.reset_connection(); db.init_db(); deliverables.ensure_schema(); review.ensure_schema(); risks.ensure_schema()


def test_automatic_risks_create_all_four_types_and_are_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr("app.notifications.send_email", lambda **kwargs: sent.append(kwargs) or True)
    with db.connect() as conn:
        conn.execute("INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('doc','review.pdf','hash',1,'x','ready','2020-01-01')")
    parent = deliverables.create({"wbs_code": "1.1", "title": "Parent", "deliverable_type": "report", "due_date": "2020-01-01"}, created_by=None)
    child = deliverables.create({"wbs_code": "1.1.1", "parent_id": parent["id"], "title": "Child", "deliverable_type": "drawing", "document_id": "doc"}, created_by=None)
    deliverables.update(parent["id"], {"due_date": "2020-01-01"})
    finding = review.create({"document_id": "doc", "category": "requirement_deviation", "severity": "major",
                             "requirement": "r", "finding": "f", "required_action": "a",
                             "unresolved_evidence": ["missing citation"]}, created_by=None)
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET updated_at='2020-01-01' WHERE id=?", (finding["id"],))
    created = risks.detect_automatic_risks()
    assert {item["risk_type"] for item in created} == {"schedule", "review", "dependency", "compliance"}
    assert len(sent) == 4
    assert len(risks.detect_automatic_risks()) == 0
    db.reset_connection()
