"""B40 -> #179: re-reading a datasheet must not orphan the findings that cite its fields.

B40 (2026-09-22) found that `extract_facts(replace=True)` deleted the
document's unconfirmed `submittal_facts` while `review_findings.fact_id`
pointed at them with no foreign key. Its answer was a GUARD: count, record,
refuse unless acknowledged. The owner authorised the redesign on 2026-09-25
(issue #179, live re-extraction "preserving the historical findings"):
replace=True now SUPERSEDES. The old rows stay with `superseded_at` set, the
finding's `fact_id` keeps resolving, and every reader of CURRENT facts leaves
the superseded rows out. Nothing is deleted, so nothing is refused.

What this file proves, each against a real ruled datasheet read twice:

  - the cited fact survives the re-read, marked superseded, still cited;
  - `list_facts`, `list_submittal_facts`, the has-no-facts guard and the
    equipment-tag scoping query read CURRENT facts only;
  - a CONFIRMED fact is never superseded;
  - the re-read is recorded (`facts.superseded.re_extract_facts`) with the
    number of rows marked and the number of findings citing them, and a
    first read records nothing;
  - B19's own path (replace=False behind the has-no-facts guard) is untouched.

Mutations: M334-M336 (re-anchored) and M440-M444,
`python scripts/mutation_check.py --phase 56`.
"""

from __future__ import annotations

import uuid

import pymupdf
import pytest

from app import comparison, datasheets, db, submittal_review
from app.config import settings

NOW = "2026-09-22T00:00:00Z"
ROWS = [("Design pressure", "23.5 barg"), ("Set pressure", "340 psig"),
        ("Compressibility factor", "0.892")]
SUPERSEDED_ACTION = "facts.superseded.re_extract_facts"
OLD_GUARD_ACTION = "findings.orphaning.re_extract_facts"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "b40.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _datasheet(tmp_path, doc_id="doc_sheet") -> str:
    """A real ruled datasheet, stored and chunked as an upload leaves it.

    Written straight to the tables rather than through the ingest pipeline:
    the chunker's quality gate marks a page this small NOT retrievable, and
    `extract_facts` reads retrievable chunks only, so the pipeline route
    yields 0 facts and this file would test nothing. Same approach as
    test_b19_review_reads_the_datasheet.
    """
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=400)
    y = 60
    for i, (label, value) in enumerate(ROWS, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), str(i), fontsize=9)
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
    datasheets.extract_facts(doc_id, allowed_document_ids=frozenset({doc_id}))
    assert _current(doc_id), "precondition: the sheet was read into facts"
    return doc_id


def _rows(doc: str, where: str = "") -> list[str]:
    return [r[0] for r in db.connect().execute(
        "SELECT id FROM submittal_facts WHERE submittal_document_id = ?"
        + where + " ORDER BY id", (doc,))]


def _current(doc: str) -> list[str]:
    return _rows(doc, " AND superseded_at IS NULL")


def _superseded(doc: str) -> list[str]:
    return _rows(doc, " AND superseded_at IS NOT NULL")


def _finding_citing_a_fact(doc: str) -> str:
    """A finding written the way production writes one, citing a real fact."""
    fact = dict(db.connect().execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ? LIMIT 1",
        (doc,)).fetchone())
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'completed',?,?)", (run, doc, NOW, NOW))
    requirement = {
        "id": str(uuid.uuid4()), "standard_document_id": doc,
        "chunk_id": fact["chunk_id"], "clause": "5.1", "page": 1,
        "requirement_text": "The design pressure shall not exceed 30 barg.",
        "operator": "<=", "raw_value": "30", "raw_unit": "barg",
        "field": "design pressure", "exceptions": [],
    }
    comparison.create_finding(
        review_run_id=run, submittal_document_id=doc, requirement=requirement,
        fact=fact, verdict=comparison.compare(requirement, fact))
    cited = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE fact_id = ?", (fact["id"],)).fetchone()[0]
    assert cited == 1, "precondition: a finding cites this fact"
    return fact["id"]


def _audit(action: str = SUPERSEDED_ACTION) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM audit_events WHERE action = ?", (action,))]


def _re_read(doc: str) -> dict:
    return datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}),
                                    replace=True)


def test_re_reading_a_cited_sheet_keeps_the_cited_fact_resolvable(tmp_path):
    doc = _datasheet(tmp_path)
    before = _current(doc)
    fact_id = _finding_citing_a_fact(doc)

    _re_read(doc)                       # no flag, no refusal, nothing deleted

    # The way comparison resolves a finding's fact: by id, unfiltered.
    row = db.connect().execute(
        "SELECT * FROM submittal_facts WHERE id = ?", (fact_id,)).fetchone()
    assert row is not None, "the cited fact was deleted"
    assert row["superseded_at"], "the cited fact is still read as current"
    assert db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE fact_id = ?",
        (fact_id,)).fetchone()[0] == 1, "the finding lost its citation"
    assert set(before) <= set(_rows(doc)), "old rows were deleted"
    assert sorted(_superseded(doc)) == sorted(before)
    assert _current(doc) and not set(_current(doc)) & set(before), \
        "the re-read wrote no new current facts"


def test_every_current_fact_reader_leaves_superseded_rows_out(tmp_path):
    doc = _datasheet(tmp_path)
    before = _current(doc)
    _re_read(doc)

    listed = {f["id"] for f in datasheets.list_facts(
        doc, allowed_document_ids=frozenset({doc}))}
    assert listed == set(_current(doc))
    assert not listed & set(before), "list_facts still returns superseded rows"

    by_run = {f["id"] for f in submittal_review.list_submittal_facts(
        allowed_document_ids=frozenset({doc}))}
    assert by_run == set(_current(doc))
    assert not by_run & set(before), "list_submittal_facts still returns superseded rows"


def test_the_has_no_facts_guard_reads_current_facts_only(tmp_path):
    """A sheet whose every fact was superseded has nothing a review can read;
    the shared guard must send it back to the extractor."""
    doc = _datasheet(tmp_path)
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET superseded_at = ?"
                     " WHERE submittal_document_id = ?", (NOW, doc))
    assert _current(doc) == []

    submittal_review.ensure_facts_extracted(doc, frozenset({doc}))

    assert _current(doc), "the guard read superseded rows as 'has facts'"


def test_equipment_tag_scoping_ignores_superseded_facts(tmp_path):
    doc = _datasheet(tmp_path)
    ids = _current(doc)
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET equipment_tag = 'P-101A' WHERE id = ?",
                     (ids[0],))
        conn.execute("UPDATE submittal_facts SET equipment_tag = 'P-101B' WHERE id = ?",
                     (ids[1],))
    assert comparison._document_is_tag_scoped(doc) is True, "precondition"

    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET superseded_at = ? WHERE id = ?",
                     (NOW, ids[1]))

    assert comparison._document_is_tag_scoped(doc) is False, \
        "a superseded row's tag still makes the sheet multi-tag"


def test_a_confirmed_fact_is_never_superseded(tmp_path):
    doc = _datasheet(tmp_path)
    fact_id = _finding_citing_a_fact(doc)
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,"
                     "created_at) VALUES ('eng','e@e.test','Eng','h',?)", (NOW,))
        conn.execute("UPDATE submittal_facts SET confirmed_by='eng', confirmed_at=?"
                     " WHERE id=?", (NOW, fact_id))

    _re_read(doc)

    assert fact_id in _current(doc), "the confirmed fact was superseded"
    assert fact_id in {f["id"] for f in datasheets.list_facts(
        doc, allowed_document_ids=frozenset({doc}))}
    assert len(_superseded(doc)) == len(ROWS) - 1


def test_a_re_read_of_cited_facts_is_recorded_without_refusing(tmp_path):
    doc = _datasheet(tmp_path)
    before = _current(doc)
    _finding_citing_a_fact(doc)

    _re_read(doc)

    [event] = _audit()
    assert event["outcome"] == "ok"
    assert event["resource_id"] == doc
    assert event["detail"] == f"facts_superseded={len(before)} findings_citing=1"
    assert _audit(OLD_GUARD_ACTION) == [], "the retired guard still writes rows"


def test_a_first_read_records_nothing(tmp_path):
    """The fixture's first read superseded nothing: no audit noise."""
    _datasheet(tmp_path)
    assert _audit() == []
    assert _audit(OLD_GUARD_ACTION) == []


def test_b19s_own_path_is_untouched(tmp_path):
    """A review reuses cached facts (replace=False behind the has-no-facts
    guard), so it supersedes nothing even when findings cite them."""
    doc = _datasheet(tmp_path)
    before = _current(doc)
    _finding_citing_a_fact(doc)

    run = submittal_review.create_review_run(
        submittal_document_id=doc, allowed_document_ids=frozenset({doc}))

    assert run
    assert _current(doc) == before
    assert _superseded(doc) == []
    assert _audit() == []
