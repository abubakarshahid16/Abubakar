from __future__ import annotations

from app import db, review


def test_finding_traceability_returns_citations_and_event_chain(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path); monkeypatch.setattr(settings, "db_path", tmp_path / "trace.sqlite")
    db.reset_connection(); db.init_db(); review.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES ('u1','engineer@example.test','Lead Engineer','x','2026-01-01')")
        conn.execute("INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('doc','review.pdf','x',1,'x','ready','2026-01-01')")
    from app import deliverables
    item = deliverables.create({"wbs_code": "1.1", "title": "Package", "deliverable_type": "report", "document_id": "doc"}, created_by=None)
    with db.connect() as conn:
        conn.execute("INSERT INTO deliverable_stakeholders(deliverable_id,user_id,role,created_at) VALUES (?,?,?,?)", (item["id"], "u1", "owner", "2026-01-01"))
    finding = review.create({"document_id": "doc", "category": "technical_query", "severity": "major", "requirement": "r", "finding": "f", "required_action": "a", "citation_ids": ["c1"]}, created_by=None)
    chain = review.traceability(finding["id"], allowed_document_ids=frozenset({"doc"}))
    assert chain and chain["citations"] == ["c1"] and chain["events"]
    assert chain["owner"]["display_name"] == "Lead Engineer"
    assert chain["action"] == "a"
    db.reset_connection()
