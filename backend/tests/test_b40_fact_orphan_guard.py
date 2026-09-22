"""B40: re-reading a datasheet must not orphan the findings that cite its fields.

`extract_facts(replace=True)` deletes the document's unconfirmed
`submittal_facts`, and `review_findings.fact_id` points at them with no
foreign key and no guard - B38's guard covers `standard_requirements` only.
Measured on the laptop database, 2026-09-22: of 18 findings citing a fact, 6
already pointed at a row that was gone.

ONE LIVE PATH, and the sweep that establishes that is in the register (row
77): there is no fact re-extract route; the cascades are not orphaning paths
(deleting a submittal takes its findings AND its facts together); nothing
deletes `review_runs`. So this file guards `extract_facts(replace=True)`.

B19's own call is `replace=False` behind its "has no facts" guard and must
stay unaffected - asserted here too.

Mutations: M334-M336, `python scripts/mutation_check.py --phase 39`.
"""

from __future__ import annotations

import uuid

import pymupdf
import pytest

from app import comparison, datasheets, db, orphan_guard, submittal_review
from app.config import settings

NOW = "2026-09-22T00:00:00Z"
ROWS = [("Design pressure", "23.5 barg"), ("Set pressure", "340 psig"),
        ("Compressibility factor", "0.892")]


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
    assert _facts(doc_id), "precondition: the sheet was read into facts"
    return doc_id


def _facts(doc: str) -> list[str]:
    return [r[0] for r in db.connect().execute(
        "SELECT id FROM submittal_facts WHERE submittal_document_id = ? ORDER BY id",
        (doc,))]


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


def _audit() -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'findings.orphaning.re_extract_facts'")]


def test_re_reading_a_sheet_whose_fields_are_cited_is_recorded_and_refused(tmp_path):
    doc = _datasheet(tmp_path)
    before = _facts(doc)
    _finding_citing_a_fact(doc)

    with pytest.raises(orphan_guard.OrphaningRefused,
                       match=r"^Re-reading this datasheet's fields is blocked"):
        datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}),
                                 replace=True)

    assert _facts(doc) == before, "the refused re-read deleted facts anyway"
    [event] = _audit()
    assert event["outcome"] == "refused"
    assert event["detail"] == "findings_orphaned=1"
    assert event["resource_id"] == doc


def test_the_refusal_says_what_to_do_and_names_no_api_flag(tmp_path):
    doc = _datasheet(tmp_path)
    _finding_citing_a_fact(doc)

    with pytest.raises(orphan_guard.OrphaningRefused) as caught:
        datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}),
                                 replace=True)

    message = str(caught.value)
    assert "1 review finding cites this datasheet's fields" in message
    assert "A review reuses the fields already read" in message
    assert "acknowledge_orphaned_findings" not in message


def test_an_acknowledged_re_read_proceeds_and_is_recorded(tmp_path):
    doc = _datasheet(tmp_path)
    before = _facts(doc)
    _finding_citing_a_fact(doc)

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}),
                             replace=True, acknowledge_orphaned_findings=True)

    assert _facts(doc) != before, "nothing was re-read"
    [event] = _audit()
    assert event["outcome"] == "ok"
    assert event["detail"] == "findings_orphaned=1"


def test_a_sheet_no_finding_cites_is_re_read_freely(tmp_path):
    """The ordinary case: no refusal, and no audit noise."""
    doc = _datasheet(tmp_path)
    before = _facts(doc)

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}), replace=True)

    assert _facts(doc) != before
    assert _audit() == []


def test_a_confirmed_fact_is_not_a_reason_to_refuse(tmp_path):
    """replace=True never deletes a CONFIRMED fact, so a finding citing one is
    not at risk and must not block the re-read."""
    doc = _datasheet(tmp_path)
    fact_id = _finding_citing_a_fact(doc)
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,"
                     "created_at) VALUES ('eng','e@e.test','Eng','h',?)", (NOW,))
        conn.execute("UPDATE submittal_facts SET confirmed_by='eng', confirmed_at=?"
                     " WHERE id=?", (NOW, fact_id))

    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}), replace=True)

    assert fact_id in _facts(doc), "the confirmed fact was deleted"
    assert _audit() == []


def test_b19s_own_path_is_untouched(tmp_path):
    """A review reuses cached facts (replace=False behind the has-no-facts
    guard), so it never reaches this guard even when findings cite them."""
    doc = _datasheet(tmp_path)
    before = _facts(doc)
    _finding_citing_a_fact(doc)

    run = submittal_review.create_review_run(
        submittal_document_id=doc, allowed_document_ids=frozenset({doc}))

    assert run
    assert _facts(doc) == before
    assert _audit() == []
