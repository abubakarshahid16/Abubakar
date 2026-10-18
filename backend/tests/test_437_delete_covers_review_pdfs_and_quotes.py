"""#437 (W1-02): a document delete also removes the review PDFs rendered for
it and the canonical field-name quotes drawn from it.

What was wrong: `review.render_report` wrote `engineering-review-<uuid>.pdf`
with nothing tying the file to its document, so a delete left it on disk
(the file quotes the document); `canonical_field_names.quote` rows survived
too (`document_refs` listed both as text that stays). Invented PDFs only.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import db, document_refs, review
from app.config import settings
from app.field_naming import LABEL, REQUIREMENT, label_key
from app.main import app
from tests.test_crs_submittal_delete_orphan_guard import (  # noqa: F401 - fixtures and helpers
    NOW, _finding_against, _requirement, _uploaded, temp_storage)

_TABLE = """CREATE TABLE IF NOT EXISTS canonical_field_names (
    subject_kind TEXT NOT NULL, subject_key TEXT NOT NULL, dictionary_sha256 TEXT NOT NULL,
    field_name TEXT, quote TEXT, provider TEXT, model_tag TEXT, prompt_sha256 TEXT,
    created_at TEXT NOT NULL, PRIMARY KEY (subject_kind, subject_key, dictionary_sha256))"""


def _delete(document_id: str, *, acknowledge: bool = False) -> dict:
    extra = "&acknowledge_orphaned_findings=true" if acknowledge else ""
    r = TestClient(app).delete(f"/api/documents/{document_id}?confirm=true{extra}")
    assert r.status_code == 200, r.text
    return r.json()


def _name(kind: str, key: str, quote: str) -> None:
    with db.connect() as conn:
        conn.execute(_TABLE)
        conn.execute("INSERT OR REPLACE INTO canonical_field_names (subject_kind, subject_key,"
                     " dictionary_sha256, field_name, quote, created_at) VALUES (?,?,'d',?,?,?)",
                     (kind, key, "noise level", quote, NOW))


def _names() -> set[tuple[str, str]]:
    return {(r[0], r[1]) for r in db.connect().execute(
        "SELECT subject_kind, subject_key FROM canonical_field_names")}


def _fact(submittal: str, label: str, *, superseded: bool = False) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO submittal_facts (id, submittal_document_id, field_name, field_value,"
                     " superseded_at, created_at, updated_at) VALUES (?,?,?,'95',?,?,?)",
                     (f"fact-{submittal}-{label_key(label)}-{int(superseded)}", submittal, label,
                      NOW if superseded else None, NOW, NOW))


def test_a_delete_removes_the_documents_review_pdfs_and_no_other_documents():
    mine, other = _uploaded("sub.pdf"), _uploaded("other.pdf")
    kept = review.render_report(other)
    gone = [review.render_report(mine), review.render_report(mine)]
    assert all(p.exists() for p in gone) and kept.exists()
    assert len(review.report_files_for(mine)) == 2
    out = _delete(mine)
    assert not any(p.exists() for p in gone), "the review PDFs of a deleted document stayed on disk"
    assert kept.exists() and review.report_files_for(other) == [kept]
    assert out["files_removed"] >= 2
    assert review.report_files_for(mine) == []


def test_a_file_name_carries_the_document_so_the_delete_can_find_it():
    sub = _uploaded("sub.pdf")
    path = review.render_report(sub)
    assert path.name.startswith(f"engineering-review-{sub}-") and path.name.endswith(".pdf")
    assert path.parent == settings.data_dir / "review_reports"


def test_deleting_a_standard_removes_the_quotes_of_its_requirements_only():
    std, other_std = _uploaded("std.pdf"), _uploaded("std2.pdf")
    req, other_req = _requirement(std), _requirement(other_std)
    _name(REQUIREMENT, req["id"], "noise level shall not exceed 90 dB(A)")
    _name(REQUIREMENT, other_req["id"], "the other standard's own sentence")
    out = _delete(std)
    assert out["rows_removed"]["canonical_field_names"] == 1
    assert _names() == {(REQUIREMENT, other_req["id"])}


def test_a_label_quote_goes_only_when_no_remaining_document_carries_the_label():
    mine, other = _uploaded("sub.pdf"), _uploaded("other.pdf")
    _fact(mine, "Noise level")
    _fact(mine, "Orifice designation")
    _fact(other, "Noise level")            # the other sheet still justifies this label
    _name(LABEL, label_key("Noise level"), "Noise level")
    _name(LABEL, label_key("Orifice designation"), "Orifice designation")
    out = _delete(mine)
    assert out["rows_removed"]["canonical_field_names"] == 1
    assert _names() == {(LABEL, label_key("Noise level"))}


def test_a_label_the_sheet_carried_only_in_an_earlier_read_still_goes_with_it():
    """cloud-2's note on #1042: the deleted sheet's OWN labels count from every
    read, superseded ones included; another sheet keeps a quote alive only by
    a label it carries now."""
    sub, other = _uploaded("sub.pdf"), _uploaded("other.pdf")
    _fact(sub, "Design pressure", superseded=True)          # only an earlier read
    _fact(other, "Design temperature")
    _fact(other, "Design pressure", superseded=True)        # the other no longer carries it
    _name(LABEL, label_key("Design pressure"), "quote from the sheet's first read")
    _name(LABEL, label_key("Design temperature"), "quote the other sheet keeps")
    out = _delete(sub)
    assert out["rows_removed"]["canonical_field_names"] == 1
    assert _names() == {(LABEL, label_key("Design temperature"))}


def test_a_database_that_never_named_a_field_deletes_as_before():
    sub = _uploaded("sub.pdf")
    tables = {r[0] for r in db.connect().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "canonical_field_names" not in tables
    out = _delete(sub)
    assert out["rows_removed"]["canonical_field_names"] == 0 and out["deleted"] == sub


def test_1053_deleting_a_standard_takes_the_review_pdfs_of_the_submittals_that_cite_it():
    """#1053: the review PDF prints each finding's requirement text, taken
    from the STANDARD; a submittal reviewed against a deleted standard kept
    PDFs that still quoted it."""
    std, other_std = _uploaded("std.pdf"), _uploaded("std2.pdf")
    sub, other_sub = _uploaded("sub.pdf"), _uploaded("sub2.pdf")
    _finding_against(sub, _requirement(std))
    _finding_against(other_sub, _requirement(other_std))
    gone = [review.render_report(sub), review.render_report(sub)]
    kept = [review.render_report(other_sub), review.render_report(other_std)]
    assert document_refs.submittals_citing(std) == [sub]
    out = _delete(std, acknowledge=True)
    assert not any(p.exists() for p in gone), "a submittal's PDFs still quote the deleted standard"
    assert all(p.exists() for p in kept)
    assert out["rows_removed"]["review_pdfs_of_citing_submittals"] == 2
    assert out["files_removed"] >= 2
    # the finding itself stays: the record survives, its citation nulled by the cascade
    assert db.connect().execute("SELECT COUNT(*) FROM review_findings WHERE document_id = ?",
                                (sub,)).fetchone()[0] == 1


def test_1053_a_library_that_never_ran_a_review_cites_nothing_and_does_not_fail(tmp_path, monkeypatch):
    """The delete route asks which submittals cite the standard before it
    deletes. A database where no review ever ran has no findings table yet:
    the answer is "none", never an error that blocks the delete (CI caught
    this on test_worker_health and test_keyword's delete tests)."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "fresh.sqlite")
    db.reset_connection()
    db.init_db()
    try:
        tables = {r[0] for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "review_findings" not in tables, "the fixture must start with no review tables"
        assert document_refs.submittals_citing("doc_never_reviewed") == []
    finally:
        db.reset_connection()
