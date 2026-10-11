"""R15 part 1 (#779): every CRS comment carries its permanent number.

Until now a number was minted only when an engineer made a comment theirs, so
the live system had issued 0 and Item No printed 1..N. Now a FINISHED review
numbers every CRS row (`main.number_crs_rows`, called by the review job):

  * the machine draft carries "CRS-<no>-001" in Item No, marked
    "Draft (not issued)" - it is NOT an engineer's: never printed as
    confirmed, never in the issue copy, never carried forward;
  * the same comment keeps the same number on a re-run and on a new run of
    the same submittal; a number is never reused;
  * an engineer confirming the draft ISSUES that same number.
Synthetic sheet only (no client text).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import access, comparison, crs_numbers, db, submittal_review
from app.main import DRAFT_NOT_ISSUED, app, number_crs_rows
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_crs_permanent_numbers import _confirm, _count
from tests.test_review_screen import _noise_rows, world  # noqa: F401


def _scope(scope):
    return access.AccessScope(user_id=None, allowed_document_ids=scope)


def test_a_finished_review_numbers_every_crs_row_as_a_draft(world):
    """THE MUTATION TARGET: 0 numbers before R15."""
    _sub, run, scope = world
    assert number_crs_rows(run, _scope(scope)) >= 1
    [row] = _noise_rows(run)
    assert row["crs_ref"].startswith("CRS-") and row["crs_ref"].endswith("-001")
    assert row["item_no"] == row["crs_ref"]
    assert row["final_resolution"] == DRAFT_NOT_ISSUED
    # Not an engineer's: never in the copy issued to the contractor.
    issue = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview?copy=issue").json()
    assert row["crs_ref"] not in [r["crs_ref"] for r in issue["rows"]]


def test_the_same_comment_keeps_its_number_on_a_re_run_and_a_new_run(world):
    _sub, run, scope = world
    number_crs_rows(run, _scope(scope))
    [first] = _noise_rows(run)
    comparison.run_comparison(run, allowed_document_ids=scope)
    number_crs_rows(run, _scope(scope))
    [again] = [r for r in _noise_rows(run) if r["crs_ref"]]
    assert again["crs_ref"] == first["crs_ref"]
    # A second run of the same submittal raises the same comment: same number.
    sub = _sub
    run2 = submittal_review.create_review_run(submittal_document_id=sub, allowed_document_ids=scope)
    with db.connect() as conn:
        conn.execute("INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id,"
                     " selection_method, included, created_at)"
                     " SELECT id || '-2', ?, standard_document_id, selection_method, included, created_at"
                     " FROM review_applicable_standards WHERE review_run_id = ?", (run2, run))
    comparison.run_comparison(run2, allowed_document_ids=scope)
    number_crs_rows(run2, _scope(scope))
    [third] = [r for r in _noise_rows(run2) if r["crs_ref"]]
    assert third["crs_ref"] == first["crs_ref"]


def test_numbering_twice_mints_nothing_new(world):
    _sub, run, scope = world
    number_crs_rows(run, _scope(scope))
    before = _count()
    number_crs_rows(run, _scope(scope))
    assert _count() == before


def test_confirming_the_draft_issues_the_same_number(world, monkeypatch):
    _sub, run, scope = world
    number_crs_rows(run, _scope(scope))
    [draft] = _noise_rows(run)
    _confirm(run, scope, monkeypatch)
    [row] = _noise_rows(run)
    assert row["crs_ref"] == draft["crs_ref"]
    assert row["final_resolution"] == "Open"
    issue = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview?copy=issue").json()
    assert row["crs_ref"] in [r["crs_ref"] for r in issue["rows"]]


def test_an_unissued_draft_no_longer_raised_is_not_carried_forward(world):
    _sub, run, scope = world
    number_crs_rows(run, _scope(scope))
    [draft] = _noise_rows(run)
    with db.connect() as conn:  # the problem is gone on the next run
        conn.execute("DELETE FROM review_findings WHERE review_run_id = ?", (run,))
    rows = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview").json()["rows"]
    assert draft["crs_ref"] not in [r["crs_ref"] for r in rows]


def test_a_draft_number_is_never_reused():
    """A drafted number stays taken: the next comment in the scope gets the next one."""
    crs_numbers.assign("no:abc", "ABC", ["draft"], document_id="d", review_run_id="r1", issued=False)
    crs_numbers.assign("no:abc", "ABC", ["other"], document_id="d", review_run_id="r2")
    found = crs_numbers.lookup("no:abc", ["draft", "other"])
    assert (found["draft"]["seq"], found["other"]["seq"]) == (1, 2)


def test_a_number_an_engineer_issued_is_never_un_issued_by_a_review():
    crs_numbers.assign("no:abc", "ABC", ["k"], document_id="d", review_run_id="r1")
    crs_numbers.assign("no:abc", "ABC", ["k"], document_id="d", review_run_id="r2", issued=False)
    assert crs_numbers.lookup("no:abc", ["k"])["k"]["issued"] == 1
