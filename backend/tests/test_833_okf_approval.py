"""R29 #833: engineer approval and versions of the OKF map.

A decision is keyed on (concept_id, content_sha256) - the same concept AT
the same content. Invented standard only; no model, no socket.
"""
from __future__ import annotations

import pytest

from app import db, okf, standards, submittal_review
from app.config import settings

NOW = "2026-10-12T00:00:00Z"
NOISE = "The noise level shall not exceed 90 dB(A)."
VIBRATION = "The vibration velocity shall not exceed 3 mm/s."


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "okf-approval.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                     "uploaded_at) VALUES ('doc_std','doc_std.pdf','sha',1,'x','ready',2,?)", (NOW,))
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
                     "text,token_count,content_hash,retrievable) VALUES ('c1','doc_std','doc_std.pdf',1,1,1,"
                     "NULL,'prose',?,1,'h1',1)", (NOISE,))
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
                     "text,token_count,content_hash,retrievable) VALUES ('c2','doc_std','doc_std.pdf',2,2,2,"
                     "NULL,'prose',?,1,'h2',1)", (VIBRATION,))
    standards.create_requirement(standard_document_id="doc_std", chunk_id="c1", clause="5.3.3", page=1,
                                 requirement_text=NOISE, source_text=NOISE,
                                 structured={"requirement_type": "numeric_limit"})
    yield
    db.reset_connection()


def _build():
    return okf.build(["doc_std"], allowed_document_ids=frozenset({"doc_std"}))


def _requirement(built):
    return next(c for c in built["concepts"] if c["kind"] == okf.REQUIREMENT)


def test_a_concept_never_decided_is_a_draft():
    concept = _requirement(_build())
    status = okf.approval_status(concept)
    assert status == {"status": okf.DRAFT, "decided_by": None, "decided_at": None}
    assert okf.confirmed_requirement_ids(_build()["concepts"]) == set()


def test_approving_confirms_it_for_an_engineer():
    concept = _requirement(_build())
    okf.approve(concept["id"], concept["content_sha256"], decided_by="eng-1")
    status = okf.approval_status(concept)
    assert status["status"] == okf.CONFIRMED
    assert status["decided_by"] == "eng-1" and status["decided_at"]


def test_rejecting_is_a_different_decision_not_a_draft():
    concept = _requirement(_build())
    okf.reject(concept["id"], concept["content_sha256"], decided_by="eng-2")
    assert okf.approval_status(concept)["status"] == okf.REJECTED


def test_re_deciding_overwrites_the_earlier_decision():
    concept = _requirement(_build())
    okf.reject(concept["id"], concept["content_sha256"], decided_by="eng-1")
    okf.approve(concept["id"], concept["content_sha256"], decided_by="eng-2")
    status = okf.approval_status(concept)
    assert status["status"] == okf.CONFIRMED and status["decided_by"] == "eng-2"


def test_an_unrelated_rebuild_keeps_the_decision():
    """THE ACCEPTANCE CRITERION: the SAME content hash across two builds
    means the decision still applies - re-running the compiler must not
    silently reset an engineer's approval."""
    first = _requirement(_build())
    okf.approve(first["id"], first["content_sha256"], decided_by="eng-1")
    second = _requirement(_build())        # a fresh build, nothing changed
    assert second["content_sha256"] == first["content_sha256"]
    assert okf.approval_status(second)["status"] == okf.CONFIRMED


def test_a_changed_standard_makes_a_confirmed_concept_stale_not_silently_true():
    """THE OTHER ACCEPTANCE CRITERION: the standard's own text changes
    (a correction, a re-extraction) -> the content hash changes -> the old
    confirmation must not keep reading as `confirmed` for words that are no
    longer there."""
    concept = _requirement(_build())
    okf.approve(concept["id"], concept["content_sha256"], decided_by="eng-1")
    with db.connect() as conn:
        conn.execute("UPDATE standard_requirements SET source_text = ?, requirement_text = ?"
                    " WHERE clause = '5.3.3'",
                    ("The noise level shall not exceed 85 dB(A).",) * 2)
        conn.execute("UPDATE chunks SET text = ? WHERE id = 'c1'",
                    ("The noise level shall not exceed 85 dB(A).",))
    changed = _requirement(_build())
    assert changed["content_sha256"] != concept["content_sha256"]
    status = okf.approval_status(changed)
    assert status["status"] == okf.STALE
    assert status["previous_status"] == okf.CONFIRMED, "the old decision is kept, not thrown away"
    assert okf.confirmed_requirement_ids(_build()["concepts"]) == set(), (
        "a review must not prefer a requirement confirmed at an old hash")


def test_confirmed_requirement_ids_names_only_the_confirmed_ones():
    concept = _requirement(_build())
    assert okf.confirmed_requirement_ids([concept]) == set()
    okf.approve(concept["id"], concept["content_sha256"], decided_by="eng-1")
    assert okf.confirmed_requirement_ids([concept]) == {concept["facts"]["requirement_id"]}
    okf.reject(concept["id"], concept["content_sha256"], decided_by="eng-1")
    assert okf.confirmed_requirement_ids([concept]) == set()


def test_annotate_adds_approval_without_mutating_the_original_dict():
    concept = _requirement(_build())
    okf.approve(concept["id"], concept["content_sha256"], decided_by="eng-1")
    annotated = okf.annotate([concept])
    assert annotated[0]["approval"]["status"] == okf.CONFIRMED
    assert "approval" not in concept, "annotate must not mutate the concept it was given"


def test_approving_an_unknown_decision_word_is_refused():
    with pytest.raises(ValueError):
        okf._decide("okf:requirement:x", "hash", "maybe", None)


# -------------------------------------------------------------- the routes

def _client(monkeypatch):
    from fastapi.testclient import TestClient

    from app import access
    from app.main import app
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    return TestClient(app)


def test_the_approve_route_confirms_and_reads_back(monkeypatch):
    concept = _requirement(_build())
    client = _client(monkeypatch)
    r = client.post(f"/api/standards/doc_std/okf/concepts/{concept['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == okf.CONFIRMED
    assert okf.approval_status(concept)["status"] == okf.CONFIRMED


def test_the_reject_route_overwrites_a_prior_approval(monkeypatch):
    concept = _requirement(_build())
    client = _client(monkeypatch)
    client.post(f"/api/standards/doc_std/okf/concepts/{concept['id']}/approve")
    r = client.post(f"/api/standards/doc_std/okf/concepts/{concept['id']}/reject")
    assert r.status_code == 200 and r.json()["status"] == okf.REJECTED


def test_approving_an_unknown_concept_is_404(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/api/standards/doc_std/okf/concepts/okf:requirement:not-real/approve")
    assert r.status_code == 404


def test_approving_through_an_unheld_document_is_404(monkeypatch):
    concept = _requirement(_build())
    client = _client(monkeypatch)
    r = client.post(f"/api/standards/doc_absent/okf/concepts/{concept['id']}/approve")
    assert r.status_code == 404
