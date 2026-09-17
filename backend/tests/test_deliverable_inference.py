from __future__ import annotations

from app import db, deliverables


def test_requirement_passage_infers_expected_deliverable_and_is_idempotent(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path); monkeypatch.setattr(settings, "db_path", tmp_path / "infer.sqlite")
    db.reset_connection(); db.init_db(); deliverables.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('req','requirements.pdf','x',1,'x','ready','2026-01-01')")
        conn.execute("INSERT INTO chunks(id,document_id,filename,ordinal,page_start,page_end,section,kind,token_count,content_hash,text,retrievable) VALUES ('c','req','requirements.pdf',0,1,1,'1.2','prose',10,'h','WBS 1.2 shall submit a complete IFC drawing for approval.',1)")
    first = deliverables.infer_expectations()
    second = deliverables.infer_expectations()
    assert first and first[0]["inferred"] == 1
    assert len(deliverables.expected_missing()) == 1
    assert second
    db.reset_connection()
