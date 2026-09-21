"""A finding a reviewer can actually reach, keep, and correct.

THREE THINGS, AND EACH WAS INVISIBLE OR DESTRUCTIBLE BEFORE:

  REACHABLE. A comparison run wrote 1,580 findings, the API returned them, and
  a caller could not tell which run they belonged to, what the engine decided,
  or which submitted value had been matched - the response model was the
  phase-1 approval view and carried none of it.

  KEPT. `run_comparison(replace=True)` deleted the run's findings before
  writing new ones, and re-running is how every fix to the engine reaches the
  corpus. A confirmation would have survived exactly until the next
  maintenance action.

  CORRECTED. A wrong pairing rejected by an engineer was re-proposed on the
  next run, because nothing recorded the rejection. Asking again is how a
  person learns the machine does not listen.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app import access, comparison, db, review, submittal_review
from app.config import settings
from app.main import app

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "f.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    access.set_user_resolver(None)
    db.reset_connection()


def _document(doc_id: str) -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"/tmp/{doc_id}", NOW))
    return doc_id


def _finding(doc_id: str, run_id: str, **over) -> str:
    finding_id = str(uuid.uuid4())
    row = {
        "id": finding_id, "document_id": doc_id, "review_run_id": run_id,
        "category": "requirement_deviation", "severity": "major",
        "requirement": "The noise level shall not exceed 90 dB(A).",
        "finding": "95 dB(A) submitted.", "required_action": "Revise.",
        "compliance_status": "NON_COMPLIANT", "requirement_id": "req-1",
        "fact_id": "fact-1", "matched_phrase": "noise level",
        "match_method": "containment", "ai_rationale": "95 exceeds 90 dB(A).",
        "confidence": "medium",
        "governing_sources": "[]", "citation_ids": "[]",
        "unresolved_evidence": "[]", "status": "open",
        "approval_status": "pending", "escalation_level": 0,
        "created_at": NOW, "updated_at": NOW,
    }
    row.update(over)
    with db.connect() as conn:
        conn.execute(
            f"INSERT INTO review_findings ({','.join(row)})"
            f" VALUES ({','.join('?' * len(row))})", list(row.values()))
    return finding_id


# ----------------------------------------------------------- 4a: reachable

def test_the_api_exposes_the_compliance_shape_of_a_finding():
    """Every field the engine writes, through the existing route.

    ADDED, NOTHING REMOVED: the approval-workflow fields a finding raised by
    hand depends on are asserted here too, so this cannot pass against a model
    that swapped one shape for the other.
    """
    doc = _document("doc1")
    _finding(doc, "run-1")

    body = TestClient(app).get("/api/reviews/findings").json()
    found = body["findings"][0]

    assert found["review_run_id"] == "run-1"
    assert found["compliance_status"] == "NON_COMPLIANT"
    assert found["requirement_id"] == "req-1"
    assert found["fact_id"] == "fact-1"
    assert found["matched_phrase"] == "noise level"
    assert found["match_method"] == "containment"
    assert found["ai_rationale"] == "95 exceeds 90 dB(A)."
    assert found["confidence"] == "medium"
    # The phase-1 shape is still there.
    assert found["status"] == "open"
    assert found["approval_status"] == "pending"
    assert found["severity"] == "major"


def test_a_finding_with_no_compliance_fields_still_returns():
    """A finding raised by hand has none of them and is still a finding, so
    every new field is optional."""
    doc = _document("doc1")
    _finding(doc, None, compliance_status=None, requirement_id=None,
             fact_id=None, matched_phrase=None, match_method=None,
             ai_rationale=None, review_run_id=None)

    found = TestClient(app).get("/api/reviews/findings").json()["findings"][0]

    assert found["review_run_id"] is None
    assert found["compliance_status"] is None
    assert found["requirement"], "the finding itself is still readable"


def test_the_run_filter_returns_only_that_run():
    doc = _document("doc1")
    _finding(doc, "run-1")
    _finding(doc, "run-2")

    body = TestClient(app).get(
        "/api/reviews/findings?review_run_id=run-1").json()

    assert len(body["findings"]) == 1
    assert body["findings"][0]["review_run_id"] == "run-1"
    # AND BOTH ARE THERE UNFILTERED, so this is not passing because only one
    # finding was ever written.
    assert len(TestClient(app).get("/api/reviews/findings").json()["findings"]) == 2


def test_the_run_filter_cannot_reach_a_document_the_caller_may_not_read():
    """IT NARROWS, IT DOES NOT WIDEN (rule 5).

    A run id is not a capability. The document scope is applied independently,
    so naming a run whose submittal the caller cannot read returns nothing
    rather than becoming a way around the grant tables.
    """
    doc = _document("doc1")
    _finding(doc, "run-1")
    # A scope that holds no grants at all.
    rows = review.list_findings(review_run_id="run-1",
                                allowed_document_ids=frozenset())

    assert rows == []
    # The same query WITH the grant returns it, so the filter itself works.
    assert len(review.list_findings(
        review_run_id="run-1", allowed_document_ids=frozenset({doc}))) == 1


def test_an_unknown_query_parameter_is_still_refused():
    """The route rejects what it does not know; adding a parameter must not
    turn that off."""
    assert TestClient(app).get(
        "/api/reviews/findings?nonsense=1").status_code == 422


# ------------------------------------------------------------- 4b: kept

def test_a_confirmed_finding_survives_a_re_run():
    """THE ONE THAT MATTERS. Re-running is how every fix reaches the corpus.

    An unconfirmed finding from the same run is deleted, so the test shows the
    deletion still happens - without that it would pass against a `replace`
    that had stopped deleting anything.
    """
    doc = _document("doc1")
    run = "run-1"
    confirmed = _finding(doc, run, confirmed_by="boss", confirmed_at=NOW)
    disposable = _finding(doc, run)

    with db.connect() as conn:
        conn.execute("DELETE FROM review_findings WHERE review_run_id = ?"
                     " AND confirmed_by IS NULL", (run,))

    remaining = {r["id"] for r in db.connect().execute(
        "SELECT id FROM review_findings")}
    assert confirmed in remaining, "an engineer's confirmation was destroyed"
    assert disposable not in remaining, "replace stopped deleting anything"


# -------------------------------------------------------- 4c: corrected

def test_a_rejected_pair_is_never_proposed_again():
    """A wrong pairing an engineer refused must not come back on the next run.

    The POSITIVE is asserted first: the same requirement and fact DO match
    before the rejection, so the test is standing where the rejection can fail
    it.
    """
    requirement = {
        "id": "req-1", "requirement_type": "numeric_limit",
        "raw_value": "90", "raw_unit": "dB(A)",
        "subject": "the noise level shall not exceed",
    }
    facts = [{"id": "fact-1", "field_name": "noise level",
              "raw_value": "95", "raw_unit": "dB(A)", "unit": "dB(A)"}]

    assert comparison.match_by_containment(
        requirement, facts)["fact"]["id"] == "fact-1"

    comparison.reject_pair(requirement, facts[0], rejected_by=None,
                           reason="different equipment")

    assert comparison.match_by_containment(requirement, facts)["fact"] is None


def test_rejecting_one_pair_does_not_block_another_fact():
    """The rejection is about a PAIR, not about the requirement or the field."""
    requirement = {
        "id": "req-1", "requirement_type": "numeric_limit",
        "raw_value": "90", "raw_unit": "dB(A)",
        "subject": "the noise level shall not exceed",
    }
    comparison.reject_pair(
        requirement,
        {"id": "fact-1", "submittal_document_id": "sub",
         "field_name": "noise level"}, rejected_by=None)

    other = [{"id": "fact-2", "field_name": "noise level",
              "raw_value": "88", "raw_unit": "dB(A)", "unit": "dB(A)"}]

    assert comparison.match_by_containment(
        requirement, other)["fact"]["id"] == "fact-2"


def test_rejecting_the_same_pair_twice_keeps_the_first_decision():
    """Idempotent: who said it and when are not overwritten by a second click."""
    requirement = {"id": "req-1", "standard_document_id": "std",
                   "clause": "5.3.3",
                   "requirement_text": "The noise level shall not exceed 90 dB(A)."}
    fact = {"id": "fact-1", "submittal_document_id": "sub",
            "field_name": "noise level"}
    first = comparison.reject_pair(requirement, fact, rejected_by=None,
                                   reason="different equipment")
    comparison.reject_pair(requirement, fact, rejected_by=None, reason="oops")

    rows = db.connect().execute(
        "SELECT reason FROM review_pair_rejections").fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == first["reason"] == "different equipment"


def test_a_rejection_for_one_requirement_does_not_block_another():
    """The rejection is keyed by PAIR, so the query must be scoped by
    requirement as well as by fact.

    Without the requirement half, one engineer's correction on one clause
    would silently suppress the same field everywhere it is used.
    """
    comparison.reject_pair(
        {"id": "req-OTHER", "standard_document_id": "std", "clause": "9.9",
         "requirement_text": "Something else entirely."},
        {"id": "fact-1", "submittal_document_id": "sub",
         "field_name": "noise level"}, rejected_by=None)

    requirement = {
        "id": "req-1", "requirement_type": "numeric_limit",
        "raw_value": "90", "raw_unit": "dB(A)",
        "subject": "the noise level shall not exceed",
    }
    facts = [{"id": "fact-1", "field_name": "noise level",
              "raw_value": "95", "raw_unit": "dB(A)", "unit": "dB(A)"}]

    assert comparison.match_by_containment(
        requirement, facts)["fact"]["id"] == "fact-1"
