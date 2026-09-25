"""#183: a submittal's title block is evidence, even after the chunker strips it.

Root cause, measured on the regression datasheets (disposable DB copy,
2026-09-24; the issue's own suspicion - the front-matter rule - was wrong):
a short datasheet reprints its title block at the top of every page, so the
chunker's running-line stripping (`chunker.detect_running_lines`, built for a
book's page headers) removes it from EVERY page, page 1 included; on the PSV
sheet what survives page 1 then fails the quality gate. The equipment-type
classifier read retrievable chunks only, so it took its evidence from a later
page's body - or, on the pump sheet, never saw "CENTRIFUGAL PUMP DATA SHEET".

The fix reads the title block from page text in the classifier and leaves the
chunker alone, so a STANDARD's cover page stays excluded (the negative case).

Sheets are built here with real PDF text, never the client's files.
Mutations: M461-M463, `python scripts/mutation_check.py --phase 57`.
"""

from __future__ import annotations

import json

import pymupdf
import pytest

from app import chunker, classification, db
from app.config import settings

NOW = "2026-09-24T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t183.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _texts(tmp_path, pages: list[list[str]]) -> list[str]:
    """Real PDF text for pages given as lists of lines, top to bottom."""
    pdf = pymupdf.open()
    for lines in pages:
        page = pdf.new_page(width=600, height=800)
        for i, line in enumerate(lines):
            page.insert_text((40, 40 + 18 * i), line, fontsize=9)
    path = tmp_path / "sheet.pdf"
    pdf.save(str(path))
    texts = [p.get_text() for p in pdf]
    pdf.close()
    return texts


def _submittal(tmp_path, pages: list[list[str]], *, body_chunk_page: int | None = None,
               role: str = "CONTRACTOR_SUBMITTAL", doc_id: str = "doc_sub") -> str:
    """Stored as the chunker leaves a short datasheet: page text intact in
    `pages`, but no retrievable chunk carries the title block."""
    texts = _texts(tmp_path, pages)
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,'x','ready',?,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", len(texts), NOW))
        for n, text in enumerate(texts, start=1):
            conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,"
                         "needs_ocr,batch_no) VALUES (?,?,?,?,0,0)",
                         (doc_id, n, text, len(text)))
        if body_chunk_page:
            conn.execute("""INSERT INTO chunks
                (id,document_id,filename,ordinal,page_start,page_end,section,kind,
                 text,token_count,content_hash,retrievable)
                VALUES ('c1',?,?,1,?,?,NULL,'prose','Operating conditions as listed.',
                        1,'h1',1)""", (doc_id, f"{doc_id}.pdf", body_chunk_page,
                                        body_chunk_page))
    classification.set_role(doc_id, role)
    return doc_id


def _rows(n: int, prefix: str) -> list[str]:
    return [f"{i} {prefix} field {i}   value {i}" for i in range(1, n + 1)]


def _evidence(doc: str) -> dict:
    row = db.connect().execute(
        "SELECT equipment_type, equipment_type_evidence FROM document_classification"
        " WHERE document_id = ?", (doc,)).fetchone()
    return {"equipment_type": row["equipment_type"],
            **json.loads(row["equipment_type_evidence"] or "{}")}


# ============================================================ the PSV shape

def test_a_title_block_the_chunker_stripped_is_still_the_title_evidence(tmp_path):
    title = ["EXAMPLE OPERATING COMPANY", "DATA SHEET FOR", "PRESSURE SAFETY VALVES (PSVs)"]
    doc = _submittal(tmp_path, [title + _rows(14, f"p{p}") for p in range(1, 6)],
                     body_chunk_page=2)

    classification.classify_equipment_type_for_submittal(doc)

    ev = _evidence(doc)
    assert ev["equipment_type"] == "Pressure Safety Valve"
    assert ev["page"] == 1, f"evidence taken from page {ev.get('page')}, not the title block"
    assert ev["method"] == "title_phrase_match"
    assert ev["classifier_version"] == classification.EQUIPMENT_TYPE_CLASSIFIER_VERSION


# ============================================================ the pump shape

def test_the_reprinted_header_names_the_sheet_when_page_one_is_less_specific(tmp_path):
    """Page 1 says '... PUMPS DATA SHEET'; every later page reprints
    'CENTRIFUGAL PUMP DATA SHEET'. That running header is the sheet naming
    itself, and it is the more specific name."""
    first = ["RECYCLE BRINE PUMPS DATA SHEET"] + _rows(14, "p1")
    later = [["CENTRIFUGAL PUMP DATA SHEET"] + _rows(14, f"p{p}") for p in range(2, 8)]
    doc = _submittal(tmp_path, [first, *later])

    classification.classify_equipment_type_for_submittal(doc)

    ev = _evidence(doc)
    assert ev["equipment_type"] == "Centrifugal Pump"
    assert ev["page"] == 2
    assert ev["method"] == "title_phrase_match"


# ================================================================ negatives

def test_a_body_sentence_naming_other_equipment_is_not_the_title(tmp_path):
    """In the MIDDLE OF PAGE 1 - the only page whose every edge line counts as
    title - a row mentions a PSV, the highest-priority pattern. The title block
    says pump. The title block wins: it is the document naming itself, and a
    row on the same page is not."""
    title = ["PUMP DATA SHEET"]
    pages = [title + _rows(14, f"p{p}") for p in range(1, 6)]
    body = _rows(14, "p1")
    body[7] = "Discharge is protected by the pressure safety valve on the header"
    pages[0] = title + body
    doc = _submittal(tmp_path, pages)

    classification.classify_equipment_type_for_submittal(doc)

    assert _evidence(doc)["equipment_type"] == "Pump"


def _chunk_state(doc: str) -> list[tuple]:
    return [tuple(r) for r in db.connect().execute(
        "SELECT ordinal, page_start, page_end, kind, retrievable, text FROM chunks"
        " WHERE document_id = ? ORDER BY ordinal", (doc,))]


def test_a_standards_chunks_are_exactly_what_they_were(tmp_path):
    """THE NEGATIVE CASE. #183 is fixed in the classifier, not the chunker, so
    a standard's cover page is as excluded - or as retrievable - as it was:
    chunking the same pages gives the same chunks, and the equipment
    classifier does not run for a standard at all. (The measured corpus has
    both kinds of cover: 240 excluded as TOC or front matter, 28 retrievable.)"""
    cover = ["COMPANY STANDARD", "PRESSURE SAFETY VALVES", "Issue 3", "2024"]
    body = [f"{c}.{s} The valve shall be tested to the stated pressure before "
            f"shipment and the certificate retained for inspection."
            for c in range(1, 4) for s in range(1, 5)]
    doc = _submittal(tmp_path, [cover, body, body, body, body, body],
                     role="COMPANY_STANDARD", doc_id="doc_std")
    chunker.chunk_document(doc)
    before = _chunk_state(doc)
    assert before, "precondition: the standard was chunked"

    assert classification.classify_equipment_type_for_submittal(doc) is None
    chunker.chunk_document(doc, force=True)

    assert _chunk_state(doc) == before
    assert _evidence(doc)["equipment_type"] is None
