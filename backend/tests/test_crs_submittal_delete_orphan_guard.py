"""B38's guard did not cover a SUBMITTAL delete cascading over its own
findings - only a STANDARD delete cascading over its requirement rows.

`review_findings.document_id` points straight at the contractor's submittal
(review.py) and is `ON DELETE CASCADE`. `DELETE /api/documents/{id}` for a
submittal with recorded CRS findings destroyed every one of them silently,
with no check, no audit record and no acknowledgement step - unlike the
standard-deletion path, which orphan_guard.py already guards. This file
proves the same record-then-refuse contract now applies to that column.

Mirrors tests/test_b38_orphan_guard.py's fixtures and assertion shape for
the "4. document delete cascade" case, one table over (document_id instead
of requirement_id -> standard_document_id).

Mutation-proof: `test_deleting_a_submittal_with_findings_is_refused` fails
if `check_submittal_delete` (or its call in `delete_document`) is removed,
because the delete would then succeed with a 200 instead of 409, and the
finding would be gone instead of intact.
"""

from __future__ import annotations

import uuid

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import comparison, db, keyword, orphan_guard, submittal_review
from app.chunker import chunk_document
from app.config import settings
from app.extract import extract_document
from app.main import app

NOW = "2026-09-22T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "crs_submittal.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _uploaded(name: str) -> str:
    """A real document: uploaded like any other, extracted and chunked."""
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


def _requirement(std: str) -> dict:
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
    return dict(db.connect().execute(
        "SELECT * FROM standard_requirements WHERE id = ?", (req_id,)).fetchone())


def _finding_against(submittal: str, requirement: dict) -> None:
    """A CRS finding, made by the real writer, recorded against `submittal`."""
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'completed',?,?)", (run, submittal, NOW, NOW))
    comparison.create_finding(
        review_run_id=run, submittal_document_id=submittal, requirement=requirement,
        fact=None, verdict=comparison.compare(requirement, None))
    cited = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE document_id = ?",
        (submittal,)).fetchone()[0]
    assert cited == 1, "precondition: a finding is recorded against the submittal"


def _audit(action: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM audit_events WHERE action = ?",
        (f"findings.orphaning.{action}",)).fetchall()]


def _submittal_exists(document_id: str) -> bool:
    return db.connect().execute(
        "SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is not None


def _findings_for(document_id: str) -> int:
    return db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE document_id = ?",
        (document_id,)).fetchone()[0]


def test_deleting_a_submittal_with_findings_is_a_409_and_leaves_it_whole():
    std = _uploaded("std.pdf")
    requirement = _requirement(std)
    submittal = _uploaded("sub.pdf")
    _finding_against(submittal, requirement)
    client = TestClient(app)

    refused = client.delete(f"/api/documents/{submittal}?confirm=true")

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "orphaning_refused"
    message = refused.json()["detail"]["message"]
    assert "1 review finding" in message
    assert message.startswith("Delete is blocked because 1 review finding")
    assert "acknowledge_orphaned_findings" not in message

    # The submittal and its finding must both survive a refused delete.
    assert _submittal_exists(submittal)
    assert _findings_for(submittal) == 1
    assert _audit("submittal_delete")[0]["outcome"] == "refused"


def test_an_acknowledged_submittal_delete_proceeds_and_findings_are_gone():
    std = _uploaded("std.pdf")
    requirement = _requirement(std)
    submittal = _uploaded("sub.pdf")
    _finding_against(submittal, requirement)
    client = TestClient(app)

    refused = client.delete(f"/api/documents/{submittal}?confirm=true")
    assert refused.status_code == 409

    done = client.delete(
        f"/api/documents/{submittal}?confirm=true&acknowledge_orphaned_findings=true")

    assert done.status_code == 200
    assert not _submittal_exists(submittal)
    # review_findings.document_id is ON DELETE CASCADE: an acknowledged
    # delete really does take the findings with it, same as the standard
    # path takes the requirements - this is the acknowledged trade, not a
    # bug, but it must never happen without the acknowledgement above.
    assert _findings_for(submittal) == 0
    assert [e["outcome"] for e in _audit("submittal_delete")] == ["refused", "ok"]


def test_nothing_is_refused_or_recorded_when_the_submittal_has_no_findings():
    """The ordinary case: a submittal no review has produced findings for
    yet deletes freely, exactly like an uncited standard does in B38."""
    submittal = _uploaded("sub.pdf")
    client = TestClient(app)

    ok = client.delete(f"/api/documents/{submittal}?confirm=true")

    assert ok.status_code == 200
    assert not _submittal_exists(submittal)
    assert _audit("submittal_delete") == []


def test_findings_citing_document_counts_only_this_submittals_findings():
    """Unit-level check on the counting function itself, isolated from the
    HTTP layer, so a regression in the SQL is caught even if the route
    wiring is otherwise fine."""
    std = _uploaded("std.pdf")
    requirement = _requirement(std)
    submittal_a = _uploaded("sub_a.pdf")
    submittal_b = _uploaded("sub_b.pdf")
    _finding_against(submittal_a, requirement)

    assert orphan_guard.findings_citing_document(submittal_a) == 1
    assert orphan_guard.findings_citing_document(submittal_b) == 0
