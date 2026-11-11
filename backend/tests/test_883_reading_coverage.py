"""PF3 (#883): no page is silently lost, and a time-out never makes a clean run.

PF1's first run: the local model timed out on 4 of the 5 pages of the PSV
sheet ("the code readers' reading stands") and the run presented itself like
any other. A page the AI reader was asked to read and did not is named on the
run, the run's reading is INCOMPLETE with the page numbers, an approval cannot
be recommended on it, and the engineer must check those pages before the
contractor's copy is issued.

Invented runs and readers only; no model, no socket.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app import comparison, crs_issue, db, page_ledger
from tests.test_885_crs_issue_gate import _client, _finding, _gate, _submittal, temp_db  # noqa: F401 - fixture
from tests.test_crs_endpoint import NOW

COVERAGE = {"pages_total": 5, "pages_not_read_into_fields": [], "fact_pages": [1, 2, 3, 4, 5]}


def _gaps(reader, pages=None):
    return page_ledger.reading_gaps(reader, pages or COVERAGE)


# ------------------------------------------------------------------ the reading
def test_a_time_out_names_each_page_and_makes_the_reading_incomplete():
    """THE CASE of PF1's PSV sheet."""
    out = _gaps({"engine": "ollama", "pages": 5, "pages_read": 1, "timed_out": [1, 2, 3, 4],
                 "code_only": {"1": "x", "2": "x", "3": "x", "4": "x"}})
    assert out["pages_ai_not_read"] == [1, 2, 3, 4]
    assert out["ai_not_read_reasons"]["3"] == "the ollama reader timed out on this page"
    assert out["reading"] == {"status": page_ledger.READING_INCOMPLETE, "pages_total": 5,
                              "incomplete_pages": [1, 2, 3, 4], "reasons": {}}


def test_a_page_the_engine_failed_on_is_named_with_the_reason():
    out = _gaps({"engine": "claude", "pages": 5, "pages_read": 3, "timed_out": [],
                 "code_only": {"4": "engine failed (HTTPStatusError)", "5": "engine failed (HTTPStatusError)"}})
    assert out["pages_ai_not_read"] == [4, 5]
    assert out["ai_not_read_reasons"]["4"] == "the claude reader did not read this page (engine failed (HTTPStatusError))"


def test_a_reader_that_was_unavailable_or_cut_off_or_stopped_leaves_its_pages_unread():
    assert _gaps({"engine": "ollama", "unavailable": "model not loaded"})["pages_ai_not_read"] == [1, 2, 3, 4, 5]
    assert _gaps({"engine": "ollama", "cut_off": [5], "pages_read": 4})["pages_ai_not_read"] == [5]
    stopped = _gaps({"engine": "claude", "stopped": "budget", "pages_read": 2})
    assert stopped["pages_ai_not_read"] == [1, 2, 3, 4, 5]
    assert "stopped (budget)" in stopped["ai_not_read_reasons"]["1"]
    assert _gaps({"engine": "claude", "stopped": "budget", "pages_read": 5})["pages_ai_not_read"] == []


def test_a_complete_reading_is_complete():
    out = _gaps({"engine": "ollama", "pages": 5, "pages_read": 5, "timed_out": [], "code_only": {}})
    assert out["reading"]["status"] == page_ledger.READING_COMPLETE and out["pages_ai_not_read"] == []


def test_no_reader_recorded_claims_nothing_about_the_ai():
    """Off, or read before summaries were kept: only the code readers' pages count."""
    assert _gaps(None)["reading"]["status"] == page_ledger.READING_COMPLETE
    unread = _gaps(None, {**COVERAGE, "pages_not_read_into_fields": [2]})
    assert unread["reading"]["status"] == page_ledger.READING_INCOMPLETE and unread["reading"]["incomplete_pages"] == [2]


def test_a_page_the_code_readers_missed_and_one_the_ai_missed_are_both_listed_once():
    out = _gaps({"engine": "ollama", "timed_out": [2, 3]}, {**COVERAGE, "pages_not_read_into_fields": [3, 5]})
    assert out["reading"]["incomplete_pages"] == [2, 3, 5]


def test_a_run_with_no_page_accounted_for_is_incomplete_never_complete():
    out = _gaps({"engine": "ollama", "timed_out": []}, {"pages_total": None, "pages_not_read_into_fields": []})
    assert out["reading"]["status"] == page_ledger.READING_INCOMPLETE and out["pages_ai_not_read"] == []


@pytest.mark.parametrize("junk", [{"engine": None}, {"timed_out": None, "code_only": None}, {"code_only": "text"}, {}])
def test_an_odd_summary_is_read_as_nothing_not_as_a_crash(junk):
    assert _gaps(junk)["pages_ai_not_read"] == []


# ------------------------------------------------------------------ the code
def _recommend(page_coverage, findings=None):
    findings = findings if findings is not None else [{"compliance_status": comparison.COMPLIANT}]
    complete = {"sufficient": True, "fields_read": 240, "fields_estimated": 250}
    return comparison.recommend_code(findings, complete, page_coverage=page_coverage)


def test_an_incomplete_reading_cannot_be_approved():
    clean = _recommend({**COVERAGE, **_gaps(None)})
    assert clean["code"] == comparison.CODE_APPROVED                      # the same run, read in full
    timed_out = _recommend({**COVERAGE, **_gaps({"engine": "ollama", "timed_out": [3]})})
    assert timed_out["code"] == comparison.CODE_MANUAL
    assert "the reading is incomplete (page 3 not read in full" in timed_out["details"]
    assert timed_out["code"] not in (comparison.CODE_APPROVED, comparison.CODE_APPROVED_WITH_COMMENTS)


def test_an_approval_with_comments_is_not_a_way_round():
    findings = [{"compliance_status": comparison.COMPLIANT}, {"compliance_status": comparison.MISSING_INFORMATION}]
    assert _recommend({**COVERAGE, **_gaps(None)}, findings)["code"] == comparison.CODE_APPROVED_WITH_COMMENTS
    assert _recommend({**COVERAGE, **_gaps({"engine": "ollama", "timed_out": [1]})}, findings)["code"] == comparison.CODE_MANUAL


def test_a_proven_breach_stays_a_breach_on_an_incomplete_reading():
    result = _recommend({**COVERAGE, **_gaps({"engine": "ollama", "timed_out": [1, 2]})},
                        [{"compliance_status": comparison.NON_COMPLIANT, "severity": "major"}])
    assert result["code"] == comparison.CODE_REJECTED


def test_a_stored_run_with_no_reading_key_is_unchanged():
    """Runs stored before PF3 carry no `reading`: nothing is claimed about them."""
    assert _recommend(COVERAGE)["code"] == comparison.CODE_APPROVED


# ------------------------------------------------------------------ the gate
def test_pages_to_check_is_the_union_of_what_no_reader_and_the_ai_did_not_read():
    assert crs_issue.pages_to_check({"pages_not_read_into_fields": [5, 2], "pages_ai_not_read": [2, 3]}) == [2, 3, 5]
    assert crs_issue.pages_to_check(None) == [] and crs_issue.pages_to_check({}) == []


def _run(doc_id, coverage):
    run_id = str(uuid.uuid4())
    outcome = {"recommended_code": "Manual Review Required", "reason": "r", "page_coverage": coverage}
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,outcome_json,"
                     "engineer_final_code,created_at,updated_at) VALUES (?,?,'completed',?,?,?,?)",
                     (run_id, doc_id, json.dumps(outcome), "Approved", NOW, NOW))
    return run_id


def _timed_out_run(doc):
    coverage = {**COVERAGE, **_gaps({"engine": "ollama", "timed_out": [2, 3]}), "not_read_reasons": {}}
    run = _run(doc, coverage)
    _finding(doc, run, "NON_COMPLIANT")
    return run


def test_a_time_out_blocks_the_contractor_copy_until_an_engineer_has_checked_the_page():
    doc = _submittal()
    run = _timed_out_run(doc)
    client = _client(doc)
    gate = _gate(client, run)
    assert [p["page"] for p in gate["unread_pages"]] == [2, 3]
    assert gate["unread_pages"][0]["reason"] == "the ollama reader timed out on this page"
    assert any("2 page(s) of the submittal were not read" in b for b in gate["blockers"])
    decision = client.post(f"/api/reviews/runs/{run}/crs/open-items/pages/2/decision",
                           json={"reason": "checked by eye on the drawing"})
    assert decision.status_code == 200, decision.text
    assert [p["page"] for p in _gate(client, run)["unread_pages"]] == [3]


def test_a_page_that_nobody_failed_to_read_cannot_be_decided():
    doc = _submittal()
    run = _timed_out_run(doc)
    refused = _client(doc).post(f"/api/reviews/runs/{run}/crs/open-items/pages/5/decision",
                             json={"reason": "checked by eye"})
    assert refused.status_code == 422


def test_the_stored_page_coverage_carries_the_reading(monkeypatch):
    """What the run stores is the ledger's coverage WITH the reader's gaps."""
    monkeypatch.setattr(page_ledger, "coverage", lambda _id: dict(COVERAGE))
    monkeypatch.setattr(comparison.datasheets, "latest_reader_summary",
                        lambda _id: {"engine": "ollama", "timed_out": [2], "code_only": {"2": "x"}})
    stored = comparison.pages_read_with_reading("doc_sheet")
    assert stored["pages_total"] == 5 and stored["pages_ai_not_read"] == [2]
    assert stored["reading"]["status"] == page_ledger.READING_INCOMPLETE and stored["reading"]["incomplete_pages"] == [2]
    monkeypatch.setattr(comparison.datasheets, "latest_reader_summary", lambda _id: None)
    assert comparison.pages_read_with_reading("doc_sheet")["reading"]["status"] == page_ledger.READING_COMPLETE
