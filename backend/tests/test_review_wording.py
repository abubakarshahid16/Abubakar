"""Owner order 2g: the review speaks plain words; the technical ones go to Details.

The owner saw "NOMINAL ESTIMATE", "denominator" and "MISSING_LOCALLY" on the
review screen. The recommendation's `reason` is now plain; the engine's own
sentence is kept as `details`, verbatim. A run stored BEFORE this change is
given its plain sentence from the same stored counts. Mutations M1041-M1044.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import comparison, db
from app.main import app
from tests.test_b3_page_ledger import _review, _sheet, temp_storage  # noqa: F401 - autouse

DEVELOPER_WORDS = ("NOMINAL", "denominator", "MISSING_LOCALLY", "NEEDS_ENGINEER_REVIEW",
                   "NOT_IN_DOCUMENT_SCOPE")
MISSING_25 = [f"XYZ {n}" for n in range(1, 26)]


def test_the_gated_reason_names_what_was_checked_and_the_missing_standards():
    """The owner's example sentence, shape for shape."""
    result = comparison.recommend_code(
        [], {"sufficient": False, "fields_read": 177, "fields_estimated": 245, "pages": 7},
        missing_references=MISSING_25,
        page_coverage={"pages_total": 7, "fact_pages": [1, 2, 3, 4, 5]})
    assert result["reason"] == (
        "Checked 177 datasheet fields on 5 of 7 pages. 25 standards the datasheet cites "
        "are not in your library (XYZ 1, XYZ 2, XYZ 3, XYZ 4, XYZ 5 and 20 more), "
        "so a review code can't be suggested yet.")
    assert "NOMINAL ESTIMATE" in result["details"] and "245" in result["details"]
    assert not any(word in result["reason"] for word in DEVELOPER_WORDS)


def _stored_old_run(tmp_path) -> tuple[str, frozenset]:
    """A run whose outcome was stored before 2g: technical sentence only."""
    sub = _sheet(tmp_path, notes_page=False)
    run, scope = _review(sub)
    old = {"recommended_code": comparison.CODE_MANUAL,
           "reason": ("the review examined 3 fields; the denominator is a NOMINAL ESTIMATE of 35 "
                      "(1 pages x 35 fields per page, not a count of this document), and that is "
                      "not enough of the submittal to recommend a code; 1 cited standard(s) are "
                      "not held locally (MISSING_LOCALLY): ABC 1"),
           "completeness": {"fields_read": 3, "fields_estimated": 35, "pages": 1,
                            "sufficient": False},
           "page_coverage": {"pages_total": 1, "fact_pages": [1]},
           "missing_references": [{"identifier": "ABC 1", "status": "MISSING_LOCALLY"}]}
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'completed', refusal_reason = ? WHERE id = ?",
                     (json.dumps(old), run))
    return run, scope


def test_a_run_stored_before_the_change_reads_plainly_with_its_old_words_in_details(tmp_path):
    """M1042: the 24 runs already on the laptop change too, not only new ones."""
    run, _scope = _stored_old_run(tmp_path)
    [summary] = [r for r in TestClient(app).get("/api/reviews/runs").json()["runs"]
                 if r["review_run_id"] == run]
    assert summary["recommended_reason"] == (
        "Checked 3 datasheet fields on 1 of 1 page. 1 standard the datasheet cites is not "
        "in your library (ABC 1), so a review code can't be suggested yet.")
    assert "NOMINAL ESTIMATE" in summary["recommended_details"]


def test_the_crs_prints_the_plain_reason_and_plain_standard_status(tmp_path):
    """M1043: what the client reads carries no engine word either."""
    run, _scope = _stored_old_run(tmp_path)
    view = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview").json()
    assert view["recommended_code_reason"].startswith("Checked 3 datasheet fields")
    text = json.dumps({k: view[k] for k in ("recommended_code_reason", "applicable_standards")})
    assert not any(word in text for word in DEVELOPER_WORDS), text
    # The plain status on the Applicable standards sheet is proved end to end
    # in test_b5_live (a submittal that really cites a missing standard).


def test_a_plain_reason_is_left_as_the_owner_wrote_it():
    """Only developer wording is rewritten: the owner's own reason stays."""
    findings = [{"compliance_status": comparison.NOT_IN_DOCUMENT_SCOPE}] * 3
    result = comparison.recommend_code(findings, {"sufficient": True})
    assert result["reason"] == "Manual review: 3 requirements require other documents"
