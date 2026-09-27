"""Owner order section 3 (screen, part A): the readiness strip and Edit.

On a synthetic sheet (no client text):
  * readiness states pages read N of M and the standards held / missing,
    under the caller's grants;
  * "Nothing changed since the last run" is claimed only when NO datasheet
    value was read and NO standard was added after the last COMPLETED run -
    mutations M1082-M1085;
  * Edit puts the engineer's words on the CRS, confirmed under their name,
    leaves the review's own text on the finding, and the audit says what
    changed - M1086, M1087, M1089;
  * a rejected comment is left off the CRS - M1090.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import comparison, db, submittal_review
from app.main import app
from tests.test_b3_page_ledger import _review, _sheet, temp_storage  # noqa: F401 - autouse
from tests.test_model_matching import _signed_in

FUTURE = "2999-01-01T00:00:00+00:00"
PAST = "2000-01-01T00:00:00+00:00"


@pytest.fixture
def world(tmp_path, monkeypatch):
    import tests.test_b3_page_ledger as ledger_tests
    # A made-up sheet whose noise level (95) exceeds the standard's 90 dB(A),
    # so the run has one comment the CRS prints.
    monkeypatch.setattr(ledger_tests, "ROWS", [*ledger_tests.ROWS, ("Noise level", "95 dB(A)")])
    sub = _sheet(tmp_path, notes_page=False)
    from app import datasheets
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))
    run, scope = _review(sub)
    comparison.run_comparison(run, allowed_document_ids=scope)
    return sub, run, scope


def _readiness(sub):
    response = TestClient(app).get(f"/api/reviews/readiness/{sub}")
    assert response.status_code == 200, response.text
    return response.json()


def test_readiness_counts_pages_and_held_standards(world):
    sub, run, _scope = world
    body = _readiness(sub)
    assert body["pages_total"] >= 1
    assert 1 <= body["pages_read"] <= body["pages_total"]
    assert body["standards_held"] == ["std.pdf"]
    assert body["standards_cited"] == len(body["standards_held"]) + len(body["standards_missing"])
    assert body["last_run_id"] == run


def test_straight_after_a_run_nothing_changed(world):
    """M1082: the claim is made - and only - when nothing moved."""
    sub, _run, _scope = world
    body = _readiness(sub)
    assert body["nothing_changed"] is True and body["changes"] == []


def test_a_value_read_after_the_run_is_a_change(world):
    """M1083."""
    sub, run, _scope = world
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET completed_at = ? WHERE id = ?", (PAST, run))
    body = _readiness(sub)
    assert body["nothing_changed"] is False
    assert any("datasheet value(s) read since the last run" in c for c in body["changes"])


def test_a_standard_added_after_the_run_is_a_change(world):
    """M1084."""
    sub, _run, _scope = world
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES ('doc_new','API 999 new.pdf','sha-new',1,'x','ready',1,?)""", (FUTURE,))
        conn.execute("INSERT INTO document_classification (document_id,document_role,suggested_by)"
                     " VALUES ('doc_new','COMPANY_STANDARD','test')")
    body = _readiness(sub)
    assert body["nothing_changed"] is False
    assert any("API 999 new.pdf" in c for c in body["changes"])


def test_the_last_run_is_the_last_completed_one(world):
    """M1099: a run still pending produced nothing to compare against."""
    sub, run, scope = world
    pending = submittal_review.create_review_run(submittal_document_id=sub, allowed_document_ids=scope)
    # Forced later than the completed run - ordering must not decide this by
    # luck of two same-second timestamps.
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET created_at = ? WHERE id = ?", (FUTURE, pending))
    assert _readiness(sub)["last_run_id"] == run


def test_the_last_run_is_measured_from_completion_not_the_code_decision(world):
    """M1088: the engineer's code decision moves updated_at, not the run."""
    sub, run, _scope = world
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET completed_at = ?, updated_at = ? WHERE id = ?",
                     (PAST, FUTURE, run))
    assert _readiness(sub)["nothing_changed"] is False


def test_a_submittal_the_caller_cannot_read_is_404(world, monkeypatch):
    sub, _run, _scope = world
    _signed_in(monkeypatch, frozenset(), user_id="outsider")
    assert TestClient(app).get(f"/api/reviews/readiness/{sub}").status_code == 404


def _first_comment(run):
    """A finding the CRS prints as a comment (non-compliant or needs review)."""
    return db.connect().execute(
        "SELECT id, finding FROM review_findings WHERE review_run_id = ?"
        " AND compliance_status IN ('NON_COMPLIANT', 'NEEDS_ENGINEER_REVIEW')"
        " AND COALESCE(origin, '') = '' LIMIT 1", (run,)).fetchone()


def _noise_rows(run):
    """The CRS rows about the one noise-level comment (edited or not)."""
    rows = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview").json()["rows"]
    return [r for r in rows if "95 dB(A)" in r["comment"] or EDITED in r["comment"]]


EDITED = "Contractor to state the noise level at 1 m."


def test_edit_is_the_crs_comment_confirmed_and_the_audit_keeps_both(world, monkeypatch):
    """M1086, M1087, M1089: the edited words are printed, under the editor's
    name; the review's own text stays on the finding; the audit says what
    changed from."""
    _sub, run, scope = world
    finding_id, original = _first_comment(run)
    _signed_in(monkeypatch, scope)
    response = TestClient(app).patch(f"/api/reviews/findings/{finding_id}",
                                     json={"engineer_comment": EDITED})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engineer_comment"] == EDITED
    assert body["finding"] == original, "the review's own text is never overwritten"
    assert body["confirmed_by"], "saving an edit confirms it, so a re-run keeps it"

    [row] = _noise_rows(run)
    assert row["comment"].endswith("\n" + EDITED)
    assert "95 dB(A)" not in row["comment"], "the review's wording is replaced, not appended to"
    assert row["comment_by"].startswith("AI Review, edited and confirmed by ")

    [event] = [json.loads(r["changes"]) for r in db.connect().execute(
        "SELECT changes FROM review_finding_events WHERE finding_id = ?"
        " AND changes LIKE '%engineer_comment%'", (finding_id,))]
    assert event["engineer_comment"] == EDITED and event["engineer_comment_before"] is None


def test_an_edited_comment_survives_a_re_run(world, monkeypatch):
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    TestClient(app).patch(f"/api/reviews/findings/{finding_id}", json={"engineer_comment": EDITED})
    comparison.run_comparison(run, allowed_document_ids=scope)
    # A re-run also writes a fresh proposal beside every confirmed row (the
    # existing design, `comparison.create_finding`); the edit is what must stay.
    [row] = [r for r in _noise_rows(run) if EDITED in r["comment"]]
    assert row["comment"].endswith(EDITED)


def test_a_rejected_comment_is_left_off_the_sheet(world, monkeypatch):
    """M1090."""
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    assert len(_noise_rows(run)) == 1
    _signed_in(monkeypatch, scope)
    assert TestClient(app).patch(f"/api/reviews/findings/{finding_id}",
                                 json={"approval_status": "rejected"}).status_code == 200
    assert _noise_rows(run) == []


def test_an_empty_edit_is_refused(world, monkeypatch):
    _sub, run, scope = world
    finding_id, _ = _first_comment(run)
    _signed_in(monkeypatch, scope)
    assert TestClient(app).patch(f"/api/reviews/findings/{finding_id}",
                                 json={"engineer_comment": ""}).status_code == 422

