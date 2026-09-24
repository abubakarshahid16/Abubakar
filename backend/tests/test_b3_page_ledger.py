"""Master order B3: every page accounted for, and an unread page is never an omission.

Two defects, one root. `datasheets.extract_facts` computed which pages yielded
no fields, and why, and threw the answer away; `comparison.compare` then wrote
"the submittal states no value for this requirement" for any requirement no
field answered - including when the value could sit on a page nobody had read
into fields. NORTH-STAR 2.2: "not retrieved" never means "not present", and an
omission finding preserves the exact contractor pages searched.

Proved here, each against real PDFs and the real code path:

  - extraction records each page's outcome, with its reason, in the ledger;
  - a page no retrievable chunk covers is accounted for (never silently absent);
  - the ledger keeps extraction's record across a refresh;
  - a requirement with no value, on a sheet with an unread page, is
    NEEDS_ENGINEER_REVIEW naming the unread page - not MISSING_INFORMATION;
  - on a sheet whose every page was read, it stays MISSING_INFORMATION and
    names the pages searched; with no page accounted for, never an omission;
  - the run keeps its page coverage; ingestion builds the ledger; the route
    returns it and hides an out-of-scope document.

Datasheets are built here, never the client's files (CLAUDE.md rule 3).
Mutations: M450-M459, `python scripts/mutation_check.py --phase 57`.
"""

from __future__ import annotations

import uuid

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import (access, classification, comparison, datasheets, db, page_ledger,
                 standards, states, submittal_review)
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

NOW = "2026-09-24T00:00:00Z"
ROWS = [("Design pressure", "23.5 barg"), ("Set pressure", "340 psig"),
        ("Compressibility factor", "0.892")]
NOTE = ("All materials and workmanship remain subject to inspection by the "
        "purchaser before shipment")


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "b3.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _ruled_page(pdf, rows) -> None:
    page = pdf.new_page(width=600, height=400)
    y = 60
    for i, (label, value) in enumerate(rows, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7)
        page.insert_text((44, y), str(i), fontsize=9)
        page.insert_text((64, y), label, fontsize=9)
        page.insert_text((304, y), value, fontsize=9)
        y += 26


def _sheet(tmp_path, doc_id="doc_sheet", *, notes_page=True, extra_pages=0,
           chunk_pages=None) -> str:
    """A real datasheet: page 1 ruled fields, page 2 a prose note with no field
    in it, then `extra_pages` blank pages. Stored and chunked as an upload
    leaves it; `chunk_pages` limits which pages get a retrievable chunk."""
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    _ruled_page(pdf, ROWS)
    if notes_page:
        pdf.new_page(width=600, height=400).insert_text((40, 60), NOTE, fontsize=9)
    for _ in range(extra_pages):
        pdf.new_page(width=600, height=400)
    pdf.save(str(path))
    texts = [p.get_text() for p in pdf]
    count = pdf.page_count
    pdf.close()
    wanted = chunk_pages or [p for p in range(1, count + 1) if texts[p - 1].strip()]
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", str(path), count, NOW))
        for n, text in enumerate(texts, start=1):
            conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,"
                         "needs_ocr,batch_no) VALUES (?,?,?,?,0,0)",
                         (doc_id, n, text, len(text)))
        for n in wanted:
            conn.execute("""INSERT INTO chunks
                (id,document_id,filename,ordinal,page_start,page_end,section,kind,
                 text,token_count,content_hash,retrievable)
                VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)""",
                (f"{doc_id}-c{n}", doc_id, f"{doc_id}.pdf", n, n, n,
                 texts[n - 1], f"h-{doc_id}-{n}"))
    return doc_id


def _ledger(doc: str) -> dict[int, dict]:
    return {r["page_no"]: r for r in page_ledger.rows(doc)}


def _review(sub: str, **req_fields) -> tuple[str, frozenset]:
    """A run whose one applicable standard asks for a value the sheet lacks."""
    std = "doc_std"
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,'x','ready',1,?)""", (std, "std.pdf", "sha-std", NOW))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES ('sc',?, 'std.pdf',1,1,1,NULL,'prose',
                    'The noise level shall not exceed 90 dB(A).',1,'h-sc',1)""", (std,))
    scope = frozenset({std, sub})
    run = submittal_review.create_review_run(
        submittal_document_id=sub, allowed_document_ids=scope)
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_reason,
             selection_method,included,created_at)
            VALUES (?,?,?,'cited','referenced',1,?)""",
            (str(uuid.uuid4()), run, std, NOW))
    standards.create_requirement(
        standard_document_id=std, chunk_id="sc", clause="5.3.3", page=1,
        requirement_text="The noise level shall not exceed 90 dB(A).",
        source_text="The noise level shall not exceed 90 dB(A).",
        structured={"requirement_type": "numeric_limit", "operator": "<=",
                    "value": 90, "unit": "dB(A)", "raw_value": "90",
                    "raw_unit": "dB(A)", "field": "noise level",
                    "subject": "the noise level", **req_fields})
    return run, scope


def _finding(run: str) -> dict:
    [row] = [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ?", (run,))]
    return row


# ============================================================ the ledger itself

def test_extraction_records_each_pages_outcome_with_its_reason(tmp_path):
    doc = _sheet(tmp_path)
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))

    rows = _ledger(doc)
    assert set(rows) == {1, 2}
    assert rows[1]["facts_status"] == "facts" and rows[1]["facts_count"] >= 3
    assert rows[1]["facts_recorded_by"] == "extraction"
    assert rows[2]["facts_status"] == "no_facts"
    assert rows[2]["facts_recorded_by"] == "extraction"
    assert rows[2]["facts_reason"], "the page's parse outcome was thrown away again"
    assert rows[1]["native_status"] == "text"
    assert rows[1]["index_status"] == "retrievable"
    assert rows[1]["vision_status"] == "not_attempted"


def test_a_page_no_retrievable_chunk_covers_is_accounted_for(tmp_path):
    """Page 3 exists in the file and in no chunk: it must still have a row,
    saying extraction never saw it and why."""
    doc = _sheet(tmp_path, extra_pages=1, chunk_pages=[1, 2])
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))

    rows = _ledger(doc)
    assert set(rows) == {1, 2, 3}, "a page disappeared from the ledger"
    assert rows[3]["index_status"] == "no_chunk"
    assert rows[3]["facts_status"] == "not_reached"
    assert "never saw it" in rows[3]["facts_reason"]
    assert page_ledger.coverage(doc)["pages_not_read_into_fields"] == [2, 3]


def test_an_excluded_page_names_the_rule_that_excluded_it(tmp_path):
    doc = _sheet(tmp_path, extra_pages=1, chunk_pages=[1, 2])
    with db.connect() as conn:
        conn.execute("""INSERT INTO exclusions (document_id,scope,page_start,page_end,
                        rule,reason,text_sample,text_length,created_at)
                        VALUES (?,'page',3,3,'page_classified_toc','toc','',0,?)""",
                     (doc, NOW))
    page_ledger.refresh(doc)

    row = _ledger(doc)[3]
    assert row["index_status"] == "excluded"
    assert row["index_reason"] == "page_classified_toc"


def test_a_refresh_keeps_extractions_own_record(tmp_path):
    doc = _sheet(tmp_path)
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    reason = _ledger(doc)[2]["facts_reason"]

    page_ledger.refresh(doc, as_submittal=True)
    page_ledger.refresh(doc, as_submittal=True)

    row = _ledger(doc)[2]
    assert row["facts_recorded_by"] == "extraction"
    assert row["facts_reason"] == reason


# ============================================== what a review may then claim

def test_no_value_with_an_unread_page_is_not_called_the_contractors_omission(tmp_path):
    sub = _sheet(tmp_path)
    run, scope = _review(sub)

    comparison.run_comparison(run, allowed_document_ids=scope)

    finding = _finding(run)
    assert finding["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW, (
        "a value that could sit on an unread page was reported as the "
        "contractor's omission")
    assert finding["ai_rationale"].startswith(comparison.UNREAD_PAGES)
    assert "page 2" in finding["ai_rationale"]
    assert "page 1 of 2" in finding["ai_rationale"]


def test_no_value_when_every_page_was_read_stays_missing_and_names_the_pages(tmp_path):
    sub = _sheet(tmp_path, notes_page=False)
    run, scope = _review(sub)

    comparison.run_comparison(run, allowed_document_ids=scope)

    finding = _finding(run)
    assert finding["compliance_status"] == comparison.MISSING_INFORMATION
    assert "fields were read from every page (page 1 of 1)" in finding["ai_rationale"]


def test_no_page_accounted_for_is_never_an_omission():
    """A document the ledger holds nothing about: "every page was read" is
    exactly the claim that cannot be made."""
    verdict = {"status": comparison.MISSING_INFORMATION,
               "rationale": "the submittal states no value for this requirement"}

    none = comparison.qualify_by_pages(verdict, page_ledger.coverage("doc_unknown"))
    read = comparison.qualify_by_pages(verdict, {
        "pages_total": 2, "fact_pages": [1, 2], "pages_not_read_into_fields": []})

    assert none["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert none["rationale"].startswith(comparison.UNREAD_PAGES)
    assert read["status"] == comparison.MISSING_INFORMATION
    assert read["rationale"].endswith("(pages 1-2 of 2)")


def test_the_run_keeps_the_page_coverage_it_was_decided_on(tmp_path):
    sub = _sheet(tmp_path)
    run, scope = _review(sub)

    comparison.run_comparison(run, allowed_document_ids=scope)

    outcome = comparison.run_outcome(run, allowed_document_ids=scope)
    pages = outcome["page_coverage"]
    assert pages["pages_total"] == 2
    assert pages["fact_pages"] == [1]
    assert pages["pages_not_read_into_fields"] == [2]
    assert pages["not_read_reasons"]["2"]


def test_the_unread_page_decides_the_code_not_an_approval(tmp_path):
    """Before B3 a sheet whose only gap was 'no value found' could be
    recommended With Comments - telling the contractor to supply values that
    may already be on a page nobody read."""
    sub = _sheet(tmp_path)
    run, scope = _review(sub)

    result = comparison.run_comparison(run, allowed_document_ids=scope)

    assert result["by_status"][comparison.MISSING_INFORMATION] == 0
    assert result["recommended_code"]["code"] == comparison.CODE_MANUAL


# ========================================================== ingestion and API

#: The rows `test_ingest_fact_extraction` uses: known to clear the chunker's
#: quality gate, so the document reaches READY rather than no-searchable.
READY_ROWS = [("Set pressure", "340 psig By Contractor"),
              ("Density at relieving temper.", "23.55 Kg/m3"),
              ("Design pressure", "23.5 barg"), ("Compressibility factor", "0.892")]


def _ingest(tmp_path, rows, name) -> tuple[str, str]:
    """Upload through the real route, role it a standard (so fact extraction
    never runs - only the ingest hooks can write ledger rows), and drive the
    real worker until the document settles."""
    path = tmp_path / name
    pdf = pymupdf.open()
    _ruled_page(pdf, rows)
    pdf.save(str(path))
    pdf.close()
    with open(path, "rb") as fh:
        doc = TestClient(app).post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    classification.set_role(doc, "COMPANY_STANDARD")
    worker = IngestionWorker()
    status = None
    for _ in range(10):
        worker.process(doc)
        status = db.connect().execute(
            "SELECT status FROM documents WHERE id = ?", (doc,)).fetchone()["status"]
        if status in (states.READY, states.FAILED, states.NO_SEARCHABLE_CONTENT):
            break
    return doc, status


def test_a_document_with_nothing_searchable_still_has_its_pages_accounted_for(tmp_path):
    """The other terminal state: every chunk excluded, nothing searchable.
    Those pages are exactly the ones that must not vanish."""
    doc, status = _ingest(tmp_path, ROWS, "THIN.pdf")
    assert status == states.NO_SEARCHABLE_CONTENT, f"fixture reached {status}"

    rows = _ledger(doc)
    assert set(rows) == {1}, "a document with nothing searchable lost its page"
    assert rows[1]["index_status"] in ("not_retrievable", "excluded", "no_chunk",
                                       "not_chunked")


def test_ingestion_builds_the_ledger_for_every_finished_document(tmp_path):
    doc, status = _ingest(tmp_path, READY_ROWS, "STD-TEST.pdf")
    assert status == states.READY, f"fixture did not reach READY: {status}"

    rows = _ledger(doc)
    assert set(rows) == {1}, "ingestion finished without accounting for the page"
    # Whatever the extractor decided about this small page, the ledger says it
    # and says it consistently with `pages` - it is never left unknown.
    flagged = db.connect().execute(
        "SELECT needs_ocr FROM pages WHERE document_id = ? AND page_no = 1",
        (doc,)).fetchone()["needs_ocr"]
    assert rows[1]["native_status"] == ("needs_ocr" if flagged else "text")
    assert rows[1]["index_status"] != "unknown"
    assert rows[1]["facts_status"] == "not_applicable"


def test_the_route_returns_the_ledger(tmp_path):
    doc = _sheet(tmp_path)
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))

    body = TestClient(app).get(f"/api/documents/{doc}/page-ledger").json()

    assert [p["page_no"] for p in body["pages"]] == [1, 2]
    assert body["coverage"]["pages_not_read_into_fields"] == [2]
    assert "text" not in body["pages"][0], "page text must never be in the ledger"


def test_the_route_hides_a_document_outside_the_callers_scope(tmp_path, monkeypatch):
    doc = _sheet(tmp_path)
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="someone", allowed_document_ids=frozenset())
    try:
        resp = TestClient(app).get(f"/api/documents/{doc}/page-ledger")
    finally:
        app.dependency_overrides.pop(access.current_scope, None)

    assert resp.status_code == 404


def test_the_crs_names_the_unread_pages_the_run_stored(tmp_path):
    """End to end: a real review, then the real CRS preview route. The
    unread-page findings are one plain row naming the page the run recorded."""
    sub = _sheet(tmp_path)
    run, scope = _review(sub)
    comparison.run_comparison(run, allowed_document_ids=scope)

    body = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview").json()

    rows = body.get("rows") or body.get("findings") or []
    summary = [r for r in rows if "Pages not yet readable" in (r.get("comment") or "")]
    assert len(summary) == 1, rows
    assert "page 2 of this submittal" in summary[0]["comment"]
    assert not [r for r in rows if (r.get("comment") or "").startswith("Requirement:")
                and "UNREAD_PAGES" in (r.get("comment") or "")], \
        "an unread-page finding reached the CRS as its own row"
