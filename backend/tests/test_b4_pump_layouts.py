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


# =========================================== 2. a YES/NO answer on a numeric field

class TestCheckboxOnAQuantityField:
    """Page 5 prints a two-line question - "MAXIMUM DISCHARGE PRESSURE TO
    INCLUDE" / indented "MAX RELATIVE DENSITY" - answered YES. The second line
    was paired with the YES alone and stored "max relative density = YES": a
    density cannot be YES. The limit of a measurable quantity takes a number."""

    def test_a_yes_is_never_stored_as_a_quantity_limit(self):
        assert datasheets.checkbox_on_quantity("MAX RELATIVE DENSITY", "YES")
        assert datasheets.checkbox_on_quantity("RATED POWER", "NO")
        assert datasheets.checkbox_on_quantity("DESIGN PRESSURE", "REQUIRED")

    def test_the_page_five_shape_leaves_the_value_unknown(self, tmp_path):
        doc = sheet(tmp_path, [(29, 100, "38"), (69, 100, "MAXIMUM DISCHARGE PRESSURE TO INCLUDE"),
                               (29, 112, "39"), (165, 112, "MAX RELATIVE DENSITY"),
                               (280, 112, "YES")])
        assert "max relative density" not in by_name(doc), \
            "a YES was stored as the value of a density"

    def test_a_real_yes_no_question_keeps_its_answer(self, tmp_path):
        """NEGATIVE: 'variable speed required' is a question, not a limit."""
        assert not datasheets.checkbox_on_quantity("VARIABLE SPEED REQUIRED", "NO")
        assert not datasheets.checkbox_on_quantity("HARDNESS TEST REQUIRED", "YES")
        doc = sheet(tmp_path, [(29, 100, "44"), (68, 100, "VARIABLE SPEED REQUIRED"),
                               (320, 100, "_____NO______")])
        assert by_name(doc)["variable speed required"][0]["field_value"].strip("_") == "NO"

    def test_a_number_on_a_quantity_limit_is_kept(self):
        """NEGATIVE: the rule refuses the checkbox, never the quantity."""
        assert not datasheets.checkbox_on_quantity("MAX RELATIVE DENSITY", "1.02")


# ================================================= 3. values given in two units

class TestTwoUnitCells:
    """Page 2 prints the unit cell "m3/h" over "(USGPM)" beside "CAPACITY /
    FLOW:", and the value "24.8 (109)" - one flow given in two units. The unit
    cell was promoted to a field label and stored "m3/h usgpm = 24.8 (109)"
    with no number parsed."""

    def test_a_unit_cell_is_never_a_field_label(self):
        assert not datasheets.is_field_label("m3/h (USGPM)")
        assert not datasheets.is_field_label("bar g (psig)")
        assert not datasheets.is_field_label("m (ft)")

    def test_a_bare_unit_word_can_still_name_a_field(self):
        """NEGATIVE: "RPM ___*___" is the rated-speed slot on a pump sheet."""
        assert datasheets.is_field_label("RPM")

    def test_the_page_two_shape_stores_no_unit_named_field(self, tmp_path):
        """NEGATIVE: until the row is read under its own label (the grid
        reader), the value stays UNKNOWN - never filed under the unit."""
        doc = sheet(tmp_path, [(29, 288, "17"), (91, 288, "CAPACITY / FLOW:"),
                               (169, 281, "m3/h"), (162, 288, "(USGPM)"),
                               (246, 288, "24.8 (109)")])
        names = by_name(doc)
        assert not [n for n in names if "usgpm" in n or n.startswith("m3")], names

    def test_the_primary_unit_is_the_one_outside_the_brackets(self):
        assert datasheets.primary_unit("m3/h (USGPM)") == "m3/h"
        assert datasheets.primary_unit("bar (psi)") == "bar"
        assert datasheets.primary_unit("bar g (psig)") == "bar g"
        assert datasheets.primary_unit("kW") == "kW"

    def test_a_cell_that_names_no_unit_gives_none(self):
        """NEGATIVE: no guessing a unit from words that are not one."""
        assert datasheets.primary_unit("(USGPM)") is None
        assert datasheets.primary_unit("CAPACITY / FLOW:") is None
        assert datasheets.primary_unit("Top of Foundation") is None

    def test_a_two_unit_value_takes_the_primary_unit(self, tmp_path):
        sheet(tmp_path, [(68, 100, "RATED FLOW"), (246, 100, "24.8")])
        fact = datasheets.create_fact(
            submittal_document_id="doc_pump", chunk_id="doc_pump-c1",
            field_label="RATED FLOW:", raw_value="24.8 (109)", page=1,
            unit="m3/h")
        assert fact["raw_value"] == "24.8"
        assert fact["raw_unit"] == "m3/h"
        assert fact["field_value"] == "24.8 (109)", "the printed value must be kept"

    def test_a_unit_printed_in_the_value_is_not_overridden(self, tmp_path):
        """NEGATIVE: the value's own printed unit is closer evidence than a hint."""
        sheet(tmp_path, [(68, 100, "RATED FLOW"), (246, 100, "24.8")])
        fact = datasheets.create_fact(
            submittal_document_id="doc_pump", chunk_id="doc_pump-c1",
            field_label="DIFFERENTIAL PRESSURE:", raw_value="7.6 bar", page=1,
            unit="m3/h")
        assert fact["raw_unit"] == "bar"


# =============================================== 4. ranges written with a dash

class TestDashRanges:
    """Traced, and NOT a defect: "ELEVATION (MSL): 5 – 150 M" already stores
    min 5 and max 150 (the single-value column stays empty by design - two ends
    are two numbers, and averaging them would invent one). These tests lock
    that in, on the real shape, so a later change cannot quietly lose it."""

    @pytest.mark.parametrize("text", ["5 – 150 M", "5 — 150 M", "5 - 150 M"])
    def test_every_dash_spelling_keeps_both_ends(self, text):
        assert datasheets.parse_range(text) == ("5", "150", "M")

    def test_the_elevation_row_stores_min_and_max(self, tmp_path):
        # ONE printed line, as the real sheet has it (words contiguous, x 68-179).
        # ASCII hyphen HERE ONLY because the PDF's built-in font cannot draw an
        # en dash (it renders a middle dot); the en dash itself is proved at
        # create_fact below and at parse_range above.
        doc = sheet(tmp_path, [(29, 463, "31"),
                               (68, 463, "ELEVATION (MSL):   5 - 150 M_______")])
        [fact] = by_name(doc)["elevation msl"]
        assert (fact["value_min"], fact["value_max"]) == (5.0, 150.0)
        assert fact["raw_value"] is None, "a range was collapsed into one number"

    def test_an_en_dash_range_is_stored_as_two_ends(self, tmp_path):
        sheet(tmp_path, [(68, 100, "RATED FLOW"), (246, 100, "24.8")])
        fact = datasheets.create_fact(
            submittal_document_id="doc_pump", chunk_id="doc_pump-c1",
            field_label="ELEVATION (MSL):", raw_value="5 – 150 M", page=1)
        assert (fact["value_min"], fact["value_max"]) == (5.0, 150.0)
        assert fact["raw_unit"] == "M"

    @pytest.mark.parametrize("text", ["09-G-411 A/B", "EN 13463-1", "10-05-497"])
    def test_a_hyphenated_identifier_is_never_a_range(self, text):
        """NEGATIVE: a tag, a standard code or a drawing number stays what it
        is - UNKNOWN as a quantity - never min/max."""
        assert datasheets.parse_range(text) is None
