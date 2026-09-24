"""Master order B4: the pump datasheet's layout defects, each on its real shape.

Measured on the pump regression document (disposable copy, 2026-09-24, owner's B4
rules): 175 facts, 58 garbled, 4 carrying a number. Each defect below is rebuilt
here as a real PDF with the words at the positions the sheet prints them, run
through `extract_facts`, and paired with a NEGATIVE test: where the layout gives
no reliable evidence, the value must stay UNKNOWN (no fact, or no column) rather
than land under a wrong label. Precision over recall - one wrong stored value
fails the owner's acceptance.

Synthetic PDFs only; no client document is read (CLAUDE.md rule 3).
"""
from __future__ import annotations

import pymupdf
import pytest

from app import datasheets, db, submittal_review
from app.config import settings

NOW = "2026-09-24T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "b4.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def sheet(tmp_path, items: list[tuple[float, float, str]], doc_id: str = "doc_pump") -> str:
    """One A4 page with each `(x, y, text)` written where the real sheet prints it,
    stored and chunked the way an upload leaves it (one retrievable chunk)."""
    path = tmp_path / f"{doc_id}.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    for x, y, text in items:
        page.insert_text((x, y), text, fontsize=7)
    pdf.save(str(path))
    text = pdf[0].get_text()
    pdf.close()
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", str(path), NOW))
        conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                     " VALUES (?,1,?,?,0,0)", (doc_id, text, len(text)))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,1,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"))
    datasheets.extract_facts(doc_id, allowed_document_ids=frozenset({doc_id}))
    return doc_id


def facts(doc: str) -> list[dict]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ?"
        " AND superseded_at IS NULL ORDER BY rowid", (doc,))]


def by_name(doc: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in facts(doc):
        out.setdefault(f["field_name"], []).append(f)
    return out


# ========================================== 1. clause numbers glued onto labels

class TestClauseReferencesLeaveTheName:
    """"CASING TYPE: (6.3.10)" was stored as the field "casing type 6 3 10": the
    printed API clause reference lost its dots and brackets and stayed in the
    name, so no requirement about the casing type could ever name it."""

    def test_the_clause_reference_is_not_part_of_the_field_name(self):
        assert datasheets.normalise_field_name("CASING TYPE: (6.3.10)") == "casing type"
        assert datasheets.normalise_field_name(
            "PERFORMANCE TEST (8.1.1 c, 8.3.3.5)") == "performance test"
        assert datasheets.normalise_field_name(
            "TEST WITH SUBSTITUTE SEAL (8.3.3.2 b)") == "test with substitute seal"

    def test_the_printed_label_keeps_it(self, tmp_path):
        doc = sheet(tmp_path, [(29, 100, "3"), (68, 100, "CASING TYPE:"),
                               (200, 100, "(6.3.10)"), (260, 100, "__________")])
        [fact] = by_name(doc)["casing type"]
        assert "(6.3.10)" in fact["field_label"], "the reader lost the printed label"
        assert fact["is_blank"] == 1

    def test_a_bracket_that_is_not_a_clause_stays(self):
        """NEGATIVE: units, locations and note numbers are part of what a field is."""
        assert datasheets.normalise_field_name(
            "PARTICULATE SIZE (DIA IN MICRONS)") == "particulate size dia in microns"
        assert datasheets.normalise_field_name("ELEVATION (MSL):") == "elevation msl"
        assert datasheets.normalise_field_name("CAPACITY (1)") == "capacity 1"
