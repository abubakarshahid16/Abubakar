"""B38: no deletion may orphan review findings by default, or silently.

`review_findings.requirement_id` has no foreign key, so every path that
deleted a requirement row left the findings citing it untraceable - 16,168 of
20,288 on the laptop database (owner's evaluation, reported). Four paths
delete requirement rows; each is asserted here to RECORD the attempt in
`audit_events` and REFUSE unless explicitly acknowledged:

  1. re-extraction  (standards.extract_requirements, replace=True)
  2. reject         (standards.decide_requirement)
  3. re-chunk       (chunker.chunk_document - the chunk_id CASCADE)
  4. document delete (DELETE /api/documents/{id} - the standard_document_id
                      CASCADE)

and to do NOTHING when no finding cites the rows, the ordinary case.

Mutations: M326-M330, `python scripts/mutation_check.py --phase 38`.
"""

from __future__ import annotations

import uuid

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import comparison, db, keyword, orphan_guard, standards, submittal_review
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.main import app

NOW = "2026-09-22T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "b38.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _standard(name="std.pdf") -> str:
    """A real standard: uploaded, extracted and chunked like any other."""
    path = settings.data_dir / name
    pdf = pymupdf.open()
    page = pdf.new_page()
    for i, line in enumerate([
        "5.3.3 Noise",
        "The noise level of rotating equipment shall not exceed 90 dB(A) at",
        "one metre from the equipment surface under rated operating conditions.",
    ]):
        page.insert_text((72, 100 + i * 16), line)
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        doc_id = TestClient(app).post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    extract_document(doc_id)
    chunk_document(doc_id)
    return doc_id


def _requirement(std: str) -> str:
    chunk = db.connect().execute(
        "SELECT id FROM chunks WHERE document_id = ? ORDER BY ordinal LIMIT 1",
        (std,)).fetchone()["id"]
    req_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO standard_requirements (id, standard_document_id, clause,"
            " page, chunk_id, requirement_text, created_at, updated_at)"
            " VALUES (?,?,?,1,?,?,?,?)",
            (req_id, std, "5.3.3", chunk,
             "The noise level shall not exceed 90 dB(A).", NOW, NOW))
    return req_id


def _finding_citing(std: str, req_id: str) -> None:
    """A finding made by the real writer, citing `req_id`."""
    sub = str(uuid.uuid4())
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (sub, "sub.pdf", f"sha-{sub}", "sub.pdf", NOW))
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'completed',?,?)", (run, sub, NOW, NOW))
    requirement = dict(db.connect().execute(
        "SELECT * FROM standard_requirements WHERE id = ?", (req_id,)).fetchone())
    comparison.create_finding(
        review_run_id=run, submittal_document_id=sub, requirement=requirement,
        fact=None, verdict=comparison.compare(requirement, None))
    cited = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE requirement_id = ?",
        (req_id,)).fetchone()[0]
    assert cited == 1, "precondition: a finding cites the requirement"


def _requirement_exists(req_id: str) -> bool:
    return db.connect().execute(
        "SELECT 1 FROM standard_requirements WHERE id = ?", (req_id,)).fetchone() is not None


def _audit(action: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM audit_events WHERE action = ?",
        (f"findings.orphaning.{action}",)).fetchall()]


def _scope(*ids): return frozenset(ids)


# ================================================== 1. re-extraction

def test_a_re_extraction_that_would_orphan_findings_is_recorded_and_refused():
    std = _standard()
    req = _requirement(std)
    _finding_citing(std, req)

    with pytest.raises(orphan_guard.OrphaningRefused, match="1 review finding"):
        standards.extract_requirements(std, allowed_document_ids=_scope(std))

    assert _requirement_exists(req), "the refused re-extraction deleted the row"
    [event] = _audit("re_extraction")
    assert event["outcome"] == "refused"
    assert event["detail"] == "findings_orphaned=1"
    assert event["resource_id"] == std


def test_an_acknowledged_re_extraction_proceeds_and_is_recorded():
    std = _standard()
    req = _requirement(std)
    _finding_citing(std, req)

    standards.extract_requirements(std, allowed_document_ids=_scope(std),
                                   acknowledge_orphaned_findings=True)

    assert not _requirement_exists(req)
    [event] = _audit("re_extraction")
    assert event["outcome"] == "ok"
    assert event["detail"] == "findings_orphaned=1"


def test_nothing_is_refused_or_recorded_when_no_finding_cites_the_rows():
    """The ordinary case: a standard no review has cited re-extracts freely."""
    std = _standard()
    req = _requirement(std)

    standards.extract_requirements(std, allowed_document_ids=_scope(std))

    assert not _requirement_exists(req)
    assert _audit("re_extraction") == []


# ============================================================ 2. reject

def test_rejecting_a_cited_requirement_is_refused():
    std = _standard()
    req = _requirement(std)
    _finding_citing(std, req)

    with pytest.raises(orphan_guard.OrphaningRefused):
        standards.decide_requirement(req, decision="reject",
                                     allowed_document_ids=_scope(std))

    assert _requirement_exists(req)
    assert _audit("reject")[0]["outcome"] == "refused"


# ====================================================== 3. re-chunk cascade

def test_a_re_chunk_that_would_cascade_away_cited_requirements_is_refused():
    """standard_requirements.chunk_id is ON DELETE CASCADE: replacing the
    chunks took their requirements with them, confirmed or not."""
    std = _standard()
    req = _requirement(std)
    _finding_citing(std, req)
    chunks_before = db.connect().execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (std,)).fetchone()[0]

    with pytest.raises(orphan_guard.OrphaningRefused):
        chunk_document(std, force=True)

    assert _requirement_exists(req), "the cascade ran despite the refusal"
    assert db.connect().execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = ?",
        (std,)).fetchone()[0] == chunks_before
    assert _audit("re_chunk")[0]["outcome"] == "refused"


# ================================================ 4. document delete cascade

def test_deleting_a_cited_standard_is_a_409_and_leaves_it_whole():
    std = _standard()
    req = _requirement(std)
    _finding_citing(std, req)
    client = TestClient(app)

    refused = client.delete(f"/api/documents/{std}?confirm=true")

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "orphaning_refused"
    assert "1 review finding" in refused.json()["detail"]["message"]
    assert _requirement_exists(req)
    assert db.connect().execute(
        "SELECT 1 FROM documents WHERE id = ?", (std,)).fetchone() is not None
    assert _audit("document_delete")[0]["outcome"] == "refused"

    done = client.delete(
        f"/api/documents/{std}?confirm=true&acknowledge_orphaned_findings=true")
    assert done.status_code == 200
    assert not _requirement_exists(req)
    assert [e["outcome"] for e in _audit("document_delete")] == ["refused", "ok"]
