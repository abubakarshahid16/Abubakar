"""B19: a review reads the datasheet into facts before it compares anything.

`datasheets.extract_facts` had no caller in `backend/app`, so a newly uploaded
datasheet was reviewed against ZERO facts: every requirement came back
MISSING_INFORMATION and the submittal was never read. It is now called from
`submittal_review.create_review_run`, with the guards the execution order
names, each asserted here:

  * guarded on "has no facts" - a second review extracts nothing;
  * replace=False - nothing is deleted by a review;
  * one transaction - a failure leaves no partial set behind;
  * confirmed facts untouched;
  * no duplicates on a second review.

Datasheets are built here with real geometry, never the client's files
(CLAUDE.md rule 3). Mutations: M316-M319, `python scripts/mutation_check.py
--phase 36`.
"""

from __future__ import annotations

import pytest

from app import datasheets, db, submittal_review
from app.config import settings

NOW = "2026-09-22T00:00:00Z"

ROWS = [
    ("Design pressure", "23.5 barg"),
    ("Density at relieving temper.", "23.55 Kg/m3"),
    ("Compressibility factor", "0.892"),
    ("Set pressure", "340 psig By Contractor"),
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "b19.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _datasheet(tmp_path, doc_id="doc_sheet") -> str:
    """A real, ruled one-page datasheet, stored and chunked like an upload."""
    import pymupdf
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=500)
    y = 60
    for index, (label, value) in enumerate(ROWS, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), f"{index}", fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26
    pdf.save(str(path))
    text = pdf[0].get_text()
    pdf.close()
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", str(path), NOW))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,1,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"))
    return doc_id


def _facts(doc_id: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ?"
        " ORDER BY id", (doc_id,)).fetchall()]


def _review(doc_id: str) -> str:
    return submittal_review.create_review_run(
        submittal_document_id=doc_id, allowed_document_ids=frozenset({doc_id}))


def _run(run_id: str) -> dict:
    return dict(db.connect().execute(
        "SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone())


def _fail_after(monkeypatch, good: int) -> None:
    """Let `good` facts through, then fail - an extraction dying mid-sheet."""
    real = datasheets.create_fact
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] > good:
            raise RuntimeError("disk full")
        return real(**kwargs)

    monkeypatch.setattr(datasheets, "create_fact", flaky)


# ======================================================== the review reads it

def test_a_review_reads_the_datasheet_before_anything_compares_it(tmp_path):
    doc = _datasheet(tmp_path)
    assert _facts(doc) == [], "precondition: nothing read before the review"

    run_id = _review(doc)

    facts = _facts(doc)
    assert len(facts) >= 3, f"the review read {len(facts)} fact(s) from the sheet"
    # Provenance: the run that first produced them (facts are per document).
    assert {f["review_run_id"] for f in facts} == {run_id}
    assert _run(run_id)["status"] == "running"


def test_a_second_review_extracts_nothing_and_duplicates_nothing(tmp_path):
    doc = _datasheet(tmp_path)
    run = _review(doc)
    first = _facts(doc)
    assert first, "precondition: the first review read the sheet"
    # B11: one running review per submittal (the route always refused a
    # second with 409; the rule now lives where the run is created). The
    # second review follows a finished first one, as it does in use.
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'completed' WHERE id = ?", (run,))

    _review(doc)

    assert _facts(doc) == first, "a second review re-read the sheet"


def test_a_confirmed_fact_is_never_touched_by_a_review(tmp_path):
    """An engineer's confirmation is a person's work. Any fact at all means
    the sheet has been read, so the review leaves the set exactly alone."""
    doc = _datasheet(tmp_path)
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,"
                     "created_at) VALUES ('eng','eng@e.test','Eng','h',?)", (NOW,))
    fact = datasheets.create_fact(
        submittal_document_id=doc, chunk_id=f"{doc}-c1",
        field_label="Design pressure", raw_value="99 barg", page=1)
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET confirmed_by='eng',"
                     " confirmed_at=? WHERE id=?", (NOW, fact["id"]))
    before = _facts(doc)

    _review(doc)

    assert _facts(doc) == before


# ============================================================= all or nothing

def test_a_failed_extraction_leaves_nothing_behind_and_says_why(tmp_path, monkeypatch):
    """ONE TRANSACTION. Facts used to commit one by one, so a sheet that
    failed on its third row kept its first two - and the "has no facts"
    guard then treated that partial set as finished, forever."""
    doc = _datasheet(tmp_path)
    real = datasheets.create_fact
    _fail_after(monkeypatch, good=2)

    with pytest.raises(submittal_review.FactExtractionFailed, match="disk full"):
        _review(doc)

    assert _facts(doc) == [], "a failed extraction left a partial fact set"
    failed = db.connect().execute(
        "SELECT status, refusal_reason FROM review_runs").fetchone()
    assert failed["status"] == "failed", "the run was left saying 'running'"
    assert "fact extraction failed" in failed["refusal_reason"]

    # And the next review, with the fault gone, reads the WHOLE sheet.
    monkeypatch.setattr(datasheets, "create_fact", real)
    _review(doc)
    assert len(_facts(doc)) >= 3


def test_a_failed_re_extraction_keeps_the_facts_it_had(tmp_path, monkeypatch):
    """The replace=True DELETE is in the same transaction, so a re-read that
    dies cannot leave the sheet with FEWER facts than before it started."""
    doc = _datasheet(tmp_path)
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    before = _facts(doc)
    assert before, "precondition"
    _fail_after(monkeypatch, good=1)

    with pytest.raises(RuntimeError, match="disk full"):
        datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}),
                                 replace=True)

    assert _facts(doc) == before
