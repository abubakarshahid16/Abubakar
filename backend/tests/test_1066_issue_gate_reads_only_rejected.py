"""#1066: the CRS composition reads the submittal's REJECTED findings in one
query instead of every finding of every run.

The issue gate, the CRS export and the preview share `_crs_content`, whose
`_prior_rejections` loaded all findings of all runs of the submittal (41 runs,
61,500 rows on an invented copy; 88% of the gate's time) to keep the rejected
ones. The one-query read must give the same rows under the same grants, with
the same standard-withholding, and the per-run scan must be gone.

Invented runs and findings only.
"""
from __future__ import annotations

import uuid

import pytest

from app import main as main_mod, submittal_review
from tests.test_crs_endpoint import NOW, _client, _finding, _run, _submittal, temp_db  # noqa: F401 - fixture


def _rejected_by_scanning_every_run(submittal: str, allowed: frozenset[str]) -> list[dict]:
    """The read this replaces, kept here as the oracle."""
    runs = [r["id"] for r in submittal_review.connect().execute(
        "SELECT id FROM review_runs WHERE submittal_document_id = ?", (submittal,))]
    return [f for run_id in runs
            for f in submittal_review.list_run_findings(run_id, allowed_document_ids=allowed)
            if f.get("approval_status") == "rejected"]


def _seed() -> tuple[str, list[str]]:
    doc = _submittal()
    other = _submittal("doc_other", "other.pdf")
    runs = [_run(doc) for _ in range(3)]
    _finding(doc, runs[0], "NON_COMPLIANT", approval_status="rejected",
             approved_by="eng", approved_at="2026-09-20T00:00:00Z", requirement="r-first")
    _finding(doc, runs[0], "NON_COMPLIANT")  # pending: not a rejection
    _finding(doc, runs[1], "NON_COMPLIANT", approval_status="approved", approved_by="eng")
    _finding(doc, runs[2], "NON_COMPLIANT", approval_status="rejected",
             approved_by="eng", approved_at="2026-09-21T00:00:00Z", requirement="r-last",
             citation_ids='["c1"]')
    # a rejected finding on a standard the caller may NOT read (r2 S2)
    _finding(doc, runs[2], "NON_COMPLIANT", approval_status="rejected", approved_by="eng",
             standard_document_id="doc_secret", requirement="r-secret")
    with submittal_review.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('doc_secret','secret.pdf','sha-secret',1,'secret.pdf','ready',4,?)", (NOW,))
    # another submittal's rejection must not leak in
    _finding(other, _run(other), "NON_COMPLIANT", approval_status="rejected", approved_by="eng")
    return doc, runs


def test_one_query_gives_the_rows_the_per_run_scan_gave():
    doc, _runs = _seed()
    allowed = frozenset({doc, "doc_std"})

    fast = submittal_review.list_rejected_findings(doc, allowed_document_ids=allowed)
    slow = _rejected_by_scanning_every_run(doc, allowed)

    by_id = lambda rows: {f["id"]: f for f in rows}  # noqa: E731
    assert by_id(fast) == by_id(slow)
    assert len(fast) == 3
    assert sorted(f["requirement"] for f in fast if f.get("standard_document_id")) == ["r-first", "r-last"]
    # decoded the same way, and the unreadable standard withheld the same way
    assert next(f for f in fast if f["requirement"] == "r-last")["citation_ids"] == ["c1"]
    secret = next(f for f in fast if not f.get("standard_document_id"))
    assert secret.get("standard_clause") is None and "r-secret" not in str(secret)


def test_the_grants_still_decide_and_no_grant_means_nothing():
    doc, _runs = _seed()
    assert submittal_review.list_rejected_findings(doc, allowed_document_ids=frozenset()) == []
    assert submittal_review.list_rejected_findings(
        doc, allowed_document_ids=frozenset({"doc_other"})) == []


def test_the_crs_composition_no_longer_scans_every_run(monkeypatch):
    doc, _runs = _seed()

    def refuse(*_a, **_k):
        raise AssertionError("#1066: _prior_rejections must not read every run's findings")
    monkeypatch.setattr(submittal_review, "list_run_findings", refuse)

    rejections = main_mod._prior_rejections(doc, frozenset({doc, "doc_std"}))

    assert rejections  # keyed by comment; every value names who rejected it
    assert all(by == "eng" for by, _at in rejections.values())


@pytest.mark.parametrize("copy", ["internal"])
def test_the_issue_gate_still_says_previously_rejected(copy):
    """The screen-facing claim is unchanged: a draft the engineer rejected on
    an earlier run says so on the new run's sheet."""
    doc, runs = _seed()
    new_run = _run(doc)
    _finding(doc, new_run, "NON_COMPLIANT", requirement="r-first")
    rows = main_mod._crs_content(new_run, _scope(doc), copy)[0]
    noted = [r for r in rows if r.get("previously_rejected")]
    assert noted and all("previously rejected by" in r["previously_rejected"] for r in noted)


def _scope(*allowed: str):
    from app import access
    return access.AccessScope(user_id="eng", allowed_document_ids=frozenset(allowed))
