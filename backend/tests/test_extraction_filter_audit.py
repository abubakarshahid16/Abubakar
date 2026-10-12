"""Owner order 2026-09-26: the extraction filter audit, on synthetic layouts.

A real 11-page vessel datasheet (aggregate only) recovered 10-44 label/value
pairs per page on 9 pages and kept none. The layouts that sheet uses are
rebuilt here with made-up values (tests/synthetic_vessel_sheet.py): cover,
contents, drawing with a ruled design-data box, nozzle schedule, data page
with a margin ruler. What this holds, each by a mutation (M1066-M1072):

  * the real pairs on every layout survive (docs/extraction-filter-audit.md
    names the rule that used to drop each, and what changed);
  * the revision block, the title block and the contents page stay out, and
    captions (people's names) are still refused - the guards the owner said
    to keep.
"""
from __future__ import annotations

import pymupdf
import pytest

from app import datasheets, db, page_ledger, submittal_review
from app.config import settings
from tests import synthetic_vessel_sheet as sv


@pytest.fixture(scope="module")
def sheet(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("audit")
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "data_dir", tmp)
    mp.setattr(settings, "db_path", tmp / "audit.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    path = tmp / "sheet.pdf"
    count = sv.build(path)
    with pymupdf.open(str(path)) as pdf:
        texts = [p.get_text() for p in pdf]
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES ('d','sheet.pdf','s',1,?,'ready',?,'2026')",
                     (str(path), count))
        for n, text in enumerate(texts, start=1):
            conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                         " VALUES ('d',?,?,?,0,0)", (n, text, len(text)))
            conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                         "section,kind,text,token_count,content_hash,retrievable)"
                         " VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)",
                         (f"c{n}", "d", "sheet.pdf", n, n, n, text, f"h{n}"))
    datasheets.extract_facts("d", allowed_document_ids=frozenset({"d"}))
    facts = datasheets.list_facts("d", allowed_document_ids=frozenset({"d"}))
    ledger = {r["page_no"]: r for r in page_ledger.rows("d")}
    yield facts, ledger
    db.reset_connection()
    mp.undo()


def _read(facts, page):
    return {f["field_name"]: (f["field_value"] or "").lower() for f in facts if f["page"] == page}


@pytest.mark.parametrize("page", sorted(sv.REAL_PAIRS))
def test_every_real_pair_on_each_layout_survives(sheet, page):
    facts, _ledger = sheet
    read = _read(facts, page)
    for label, value in sv.REAL_PAIRS[page].items():
        assert read.get(label) == value, f"page {page}: {label!r} read as {read.get(label)!r}"


def test_the_revision_block_title_block_and_contents_stay_out(sheet):
    """The guards the owner said to keep: revision history, title block,
    contents entries and people's names never become facts."""
    facts, ledger = sheet
    text = " ".join(f"{f['field_name']} {f['field_value']}".lower() for f in facts)
    for word in sv.NOT_FIELDS:
        assert word not in text, f"{word!r} became a fact"
    assert ledger[2]["facts_status"] == "no_facts", "the contents page was read as fields"


def test_the_pages_with_real_pairs_now_read_as_read(sheet):
    _facts, ledger = sheet
    assert [p for p in sv.REAL_PAIRS if ledger[p]["facts_status"] != "facts"] == []


def test_the_unit_before_the_value_is_paired_and_nothing_else_moves():
    assert datasheets.split_label_value(["OPERATING TEMPERATURE", "C", "90"]) == [
        ("OPERATING TEMPERATURE", "90 C")]
    # the existing value-then-unit shape, and a plain two-column row, as before
    assert datasheets.split_label_value(["DENSITY", "1020", "kg/m3"]) == [("DENSITY", "1020 kg/m3")]
    assert datasheets.split_label_value(["FLUID", "PRODUCED WATER"]) == [("FLUID", "PRODUCED WATER")]


@pytest.mark.parametrize("value", ["SA-516 GR.70", "A105", "ASME VIII DIV. 1", "API 610",
                                   "ASME B31.3", "EN 13445", "CL300", "Class 150", "300#"])
def test_a_designation_is_an_answer(value):
    assert datasheets.states_a_value(value), value


@pytest.mark.parametrize("value", ["A. Author", "Example Bay", "EX-100-DS-0001", "Engineer 1",
                                   "PRODUCED WATER", "HORIZONTAL SEPARATOR", "V-9001"])
def test_a_caption_a_name_or_a_document_number_is_still_not(value):
    assert not datasheets.states_a_value(value), value
