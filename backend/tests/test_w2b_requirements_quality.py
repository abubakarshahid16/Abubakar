"""W2b part 1: how requirements are CREATED (#594 #595 #596 #597).

Standards tables and junk text were turned into thousands of fake
requirements. Every test here is written against a synthetic standard (invented
text, no real document) and goes through the real extractors, and each one
fails when its fix is removed: `scripts/mutations/w2b_requirements_quality.py`
(M2501-M2512) proves it.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app import (claims, comparison, datasheets, db, requirement_quality,
                 requirements_3b, schemas, standards, submittal_review)
from app.config import settings

STD = "doc_std"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w2b.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _pdf(path, header, rows, pages=1) -> str:
    """A PDF whose every page carries the SAME ruled table."""
    import pymupdf
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=600, height=400)
        x0, y0, cw, rh = 40, 60, 130, 30
        for r, row in enumerate([header, *rows]):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(x0 + c * cw, y0 + r * rh,
                                    x0 + (c + 1) * cw, y0 + (r + 1) * rh)
                page.draw_rect(rect, color=(0, 0, 0), width=0.7)
                page.insert_text((rect.x0 + 4, rect.y0 + 19), str(cell), fontsize=9)
    doc.save(str(path)); doc.close()
    return str(path)


def _doc(doc_id: str = STD, stored_path: str = "x.pdf", role=None, pages: int = 3) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',?,'2026-09-18T00:00:00Z')""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", stored_path, pages))
        conn.execute("""INSERT INTO document_classification
            (document_id,suggested_by,document_role,discipline,document_number)
            VALUES (?,?,?,?,?)""",
            (doc_id, "test", role or standards.COMPANY_STANDARD, "Mechanical",
             f"NUM-{doc_id}"))
    return doc_id


def _chunk(chunk_id, doc_id, text="x", *, kind="prose", section=None, page=1, ordinal=0):
    with db.connect() as conn:
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
            (chunk_id, doc_id, "f.pdf", ordinal, page, page, section, kind,
             text, len(text.split()), f"h-{chunk_id}"))
    return chunk_id


def _scope(*ids): return frozenset(ids)


def _table_standard(tmp_path, header, rows, pages=3):
    path = _pdf(tmp_path / "t.pdf", header, rows, pages=pages)
    _doc(STD, path, pages=pages)
    for page in range(1, pages + 1):
        _chunk(f"t{page}", STD, "table", kind="table", page=page, ordinal=page)


def _rows():
    return standards.list_requirements(STD, allowed_document_ids=_scope(STD))


# ======================================================== #594 one per cell

def test_a_table_repeated_on_three_pages_and_extracted_twice_is_one_requirement_per_cell(tmp_path):
    """Test 1. 2 rows x 1 value column = 2 cells; 3 pages; 2 runs."""
    _table_standard(tmp_path, ["Category", "Retention (pcf)"],
                    [["Foundation", "12"], ["Marine", "20"]], pages=3)
    first = standards.extract_table_values(STD, allowed_document_ids=_scope(STD))
    standards.extract_table_values(STD, allowed_document_ids=_scope(STD))

    rows = _rows()
    assert first["values"] == 2          # positive first: cells WERE read
    assert len(rows) == 2, [r["requirement_text"] for r in rows]
    for row in rows:
        pages = sorted(e["page"] for e in row["evidence_pages"])
        assert pages == [1, 2, 3], "every source page stays as evidence"
        assert row["page"] == 1 and row["chunk_id"] == "t1"
        assert row["citation_resolves"] is True


def test_a_different_value_in_the_same_cell_position_is_a_different_requirement(tmp_path):
    """Identity includes the written value: two tables with one header and
    different numbers are not merged into one."""
    _table_standard(tmp_path, ["Category", "Retention (pcf)"], [["Foundation", "12"]], pages=1)
    standards.extract_table_values(STD, allowed_document_ids=_scope(STD))
    with db.connect() as conn:
        first = conn.execute("SELECT * FROM standard_requirements").fetchone()
    standards.create_requirement(
        standard_document_id=STD, chunk_id="t1", page=1, clause=None,
        requirement_text="Foundation - Retention (pcf): 14",
        source_text="Foundation | Retention (pcf) | 14", confidence=0.5,
        structured={"requirement_type": "table_value", "raw_value": "14",
                    "identity_key": first["identity_key"].replace("12", "14")})
    assert len(_rows()) == 2


def test_a_confirmed_table_row_is_not_duplicated_by_a_re_run(tmp_path):
    """The case replace cannot cover: a confirmed row survives, and the re-run
    must find it instead of writing an unconfirmed twin."""
    _table_standard(tmp_path, ["Category", "Retention (pcf)"], [["Foundation", "12"]], pages=1)
    standards.extract_table_values(STD, allowed_document_ids=_scope(STD))
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
                     "created_at) VALUES ('eng','e@example.test','e','h','2026-09-18T00:00:00Z')")
        conn.execute("UPDATE standard_requirements SET confirmed_by='eng'")
    standards.extract_table_values(STD, allowed_document_ids=_scope(STD))
    assert len(_rows()) == 1


# ================================================ #595 numparse, max/min, unit

@pytest.mark.parametrize("cell,expected", [
    ("0,030", 0.03), ("−5", -5.0), ("12", 12.0), ("1,200", 1200.0)])
def test_table_cells_are_parsed_by_numparse(cell, expected):
    number, _ = requirements_3b.cell_number(cell)
    assert number == expected


def test_a_max_column_gives_a_less_or_equal_operator_and_a_header_unit_is_carried(tmp_path):
    """Test 2, end to end through the extractor."""
    _table_standard(tmp_path, ["Size", "Max. clearance (mm)", "Min. wall (mm)"],
                    [["DN 50", "0,030", "2,5"]], pages=1)
    standards.extract_table_values(STD, allowed_document_ids=_scope(STD))
    by_field = {r["field"]: r for r in _rows()}
    maximum = by_field["Max. clearance"]
    assert maximum["raw_value"] == "0,030"
    # `value` is the NORMALISED number (this table's unit normalises mm to its
    # canonical unit): 0.03 mm, not the 30 mm numparse's thousands rule gives.
    expected = claims.normalise("0.03", "mm")
    assert maximum["value"] == pytest.approx(expected.normalized_value)
    assert maximum["unit"] == expected.normalized_unit
    assert maximum["value"] != pytest.approx(claims.normalise("30", "mm").normalized_value)
    assert maximum["operator"] == "<="
    assert maximum["raw_unit"] == "mm"
    assert maximum["unit_from"] == "column_header"
    minimum = by_field["Min. wall"]
    assert minimum["operator"] == ">="
    assert minimum["value"] == pytest.approx(claims.normalise("2.5", "mm").normalized_value)


def test_a_cell_with_no_unit_keeps_its_number_and_claims_no_unit(tmp_path):
    _table_standard(tmp_path, ["Size", "Max"], [["DN 50", "0,030"]], pages=1)
    standards.extract_table_values(STD, allowed_document_ids=_scope(STD))
    row = _rows()[0]
    assert row["value"] == pytest.approx(0.03)
    assert row["unit"] is None and row["unit_from"] is None
    assert row["operator"] == "<="


def test_a_header_naming_both_min_and_max_gives_no_operator():
    assert requirements_3b.header_operator("Min/Max") is None
    assert requirements_3b.header_operator("Size") is None


def test_a_range_cell_is_not_read_as_one_number():
    assert requirements_3b.cell_number("5-10") == (None, None)


# ===================================================== #596 definitions

SHALL_DEFINITION = "Shall: a verb that indicates a mandatory requirement of this document."
DEFINED_TERM = ("3.1 design pressure: the pressure that shall be used by the owner "
                "to size every component of the vessel.")
NORMAL = "The vessel shall be hydrostatically tested at 1.5 times the design pressure."


def _definitions_standard():
    _doc(STD, pages=3)
    _chunk("d1", STD, "3 Terms and definitions", section="3 Terms and definitions",
           page=1, ordinal=1)
    _chunk("d2", STD, DEFINED_TERM, section="3.1 design pressure", page=1, ordinal=2)
    _chunk("n1", STD, f"{NORMAL} {SHALL_DEFINITION}", section="4 Testing",
           page=2, ordinal=3)


def test_definitions_are_stored_as_definitions_not_requirements():
    """Test 3a. A clause in the definitions section, and a sentence that only
    defines 'shall' outside it, are `definition`; the test clause is not."""
    _definitions_standard()
    standards.extract_requirements(STD, allowed_document_ids=_scope(STD))
    types = {r["requirement_text"]: r["requirement_type"] for r in _rows()}
    assert types[NORMAL] == "numeric_limit" or types[NORMAL] == "statement"
    assert types[SHALL_DEFINITION] == "definition"
    assert types[DEFINED_TERM] == "definition"
    assert next(r for r in _rows() if r["requirement_text"] == DEFINED_TERM)["value"] is None


def test_the_definitions_section_ends_where_the_next_clause_begins():
    _definitions_standard()
    standards.extract_requirements(STD, allowed_document_ids=_scope(STD))
    normal = next(r for r in _rows() if r["requirement_text"] == NORMAL)
    assert normal["requirement_type"] != "definition"


def test_definitions_are_not_counted_as_requirements():
    _definitions_standard()
    standards.extract_requirements(STD, allowed_document_ids=_scope(STD))
    total = len(_rows())
    listed = next(s for s in standards.list_standards(
        allowed_document_ids=_scope(STD)) if s["id"] == STD)
    definitions = sum(1 for r in _rows() if r["requirement_type"] == "definition")
    assert definitions >= 2
    assert listed["requirement_count"] == total - definitions


def test_definition_is_a_valid_response_type():
    assert "definition" in requirements_3b.STORED_REQUIREMENT_TYPES
    from typing import get_args
    assert "definition" in get_args(schemas.RequirementType)


# ------------------------------------------------ review: nothing reaches it

def _review_with(requirements):
    """A run against STD, where `requirements` are created first."""
    _doc(STD)
    _chunk("sc", STD, "std")
    sub = _doc("sub", role="CONTRACTOR_SUBMITTAL", pages=1)
    _chunk("fc", sub, "sheet")
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (run, sub))
        conn.execute("""INSERT INTO review_applicable_standards
            (id,review_run_id,standard_document_id,selection_method,included,
             created_at) VALUES (?,?,?,'rule',1,?)""",
            (str(uuid.uuid4()), run, STD, "2026-09-18T00:00:00Z"))
    ids = {}
    for name, text, kind in requirements:
        row = standards.create_requirement(
            standard_document_id=STD, chunk_id="sc", clause="5.3.3", page=1,
            requirement_text=text, source_text=text, confidence=0.9,
            structured={"requirement_type": kind, "operator": "<=", "value": 90,
                        "unit": "dB(A)", "raw_value": "90", "raw_unit": "dB(A)",
                        "field": "noise level", "subject": "the noise level"})
        ids[name] = row["id"]
    datasheets.create_fact(submittal_document_id=sub, chunk_id="fc",
                           field_label="Noise level", raw_value="95 dB(A)", page=1)
    comparison.run_comparison(run, allowed_document_ids=_scope(STD, sub))
    cited = {f["requirement_id"] for f in comparison.list_findings(
        run, allowed_document_ids=_scope(STD, sub))}
    return ids, cited


def test_a_definition_never_reaches_a_review_run():
    """Test 3b. The control (a numeric_limit with the same field and limit) IS
    compared, so the absence of the definition is a real exclusion."""
    ids, cited = _review_with([
        ("control", "The noise level shall not exceed 90 dB(A).", "numeric_limit"),
        ("definition", "Noise level: the level shall not exceed 90 dB(A) as defined.",
         "definition")])
    assert ids["control"] in cited
    assert ids["definition"] not in cited


# ====================================================== #597 text quality

MIRRORED = "noitcurtsni eht ot dnuorg eht tnemec ni ro ni tsum eht lleh dna ssenisub"
NORMAL_TEXT = "10 % or less overpressure"


def test_garbled_and_mirrored_text_is_flagged_and_normal_text_is_not():
    """Test 4a."""
    assert requirement_quality.text_quality(MIRRORED) == "text_quality"
    assert requirement_quality.text_quality("ɘht ƨɘɘɿɘq ɒ ɘɿɘhw") == "text_quality"
    assert requirement_quality.text_quality(
        "xqzk wpfr tvbn qwrt lkjh mnbv gfds zxcv") == "text_quality"
    assert requirement_quality.text_quality(NORMAL_TEXT) is None
    assert requirement_quality.text_quality(
        "The austenitic stainless steel hydrostatic test shall be performed "
        "per ASME B31.3 using potable water.") is None


def test_flagged_text_is_kept_with_its_reason_and_listed_as_needing_verification():
    """Test 4b. Kept, not deleted; confidence capped; the reason is shown."""
    _doc(STD)
    _chunk("sc", STD, "std")
    garbled = standards.create_requirement(
        standard_document_id=STD, chunk_id="sc", clause="5.3.3", page=1,
        requirement_text=MIRRORED + " shall not exceed 90 dB(A)",
        source_text=MIRRORED, confidence=0.9)
    fine = standards.create_requirement(
        standard_document_id=STD, chunk_id="sc", clause="5.3.4", page=1,
        requirement_text=NORMAL_TEXT + " shall be allowed",
        source_text=NORMAL_TEXT, confidence=0.9)
    rows = {r["id"]: r for r in _rows()}
    assert rows[fine["id"]]["needs_verification"] is False   # positive first
    assert rows[fine["id"]]["needs_verification_reason"] is None
    bad = rows[garbled["id"]]
    assert bad["needs_verification"] is True
    assert bad["needs_verification_reason"] == "text_quality"
    assert bad["confidence"] < standards.VERIFICATION_THRESHOLD
    queue = standards.verification_queue(allowed_document_ids=_scope(STD))
    assert [q["needs_verification_reason"] for q in queue if q["id"] == garbled["id"]] == ["text_quality"]


def test_flagged_text_never_reaches_a_review_run():
    """Test 4c, with a control that is compared."""
    ids, cited = _review_with([
        ("control", "The noise level shall not exceed 90 dB(A).", "numeric_limit"),
        ("garbled", MIRRORED + " noise level shall not exceed 90 dB(A)", "numeric_limit")])
    assert ids["control"] in cited
    assert ids["garbled"] not in cited


def test_a_human_confirmation_returns_a_flagged_row_to_reviews():
    _doc(STD)
    _chunk("sc", STD, "std")
    row = standards.create_requirement(
        standard_document_id=STD, chunk_id="sc", clause="1", page=1,
        requirement_text=MIRRORED, source_text=MIRRORED, confidence=0.9)
    assert standards.is_reviewable(row) is False
    assert standards.is_reviewable({**row, "confirmed_by": "eng"}) is True
