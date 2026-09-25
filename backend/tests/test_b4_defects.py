"""Master order B4, 2026-09-25: the extraction defects left after #202, each
rebuilt as a synthetic PDF and paired with a NEGATIVE test.

Found by probing `extract_facts` with the six defect classes the owner named -
multi-unit values, ranges, clause numbers in labels, YES/NO on numeric fields,
process-data rows, title blocks - in spellings #202's tests did not cover.
Every positive test has a negative twin: the shape that LOOKS like the fix's
target and must stay refused. Precision over recall - one wrong stored value
fails the owner's acceptance.

Synthetic PDFs only; no client document is read (CLAUDE.md rule 3). Tags and
numbers are made up.
"""
from __future__ import annotations

import pymupdf
import pytest

from app import datasheets, db, row_noise, submittal_review
from app.config import settings

NOW = "2026-09-25T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "b4d.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def sheet(tmp_path, items, doc_id="doc_b4d"):
    """One A4 page with each `(x, y, text)` where a datasheet prints it,
    stored the way an upload leaves it, then extracted."""
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


def by_name(doc):
    out = {}
    for row in db.connect().execute(
            "SELECT * FROM submittal_facts WHERE submittal_document_id = ?"
            " AND superseded_at IS NULL ORDER BY rowid", (doc,)):
        out.setdefault(row["field_name"], []).append(dict(row))
    return out


def row(label, value, y=100):
    return [(40, y, label), (250, y, value)]


# ================================================= 1. two units with a slash

class TestSlashDualUnits:
    def test_one_quantity_in_two_systems_keeps_the_first(self, tmp_path):
        facts = by_name(sheet(tmp_path, row("DESIGN TEMPERATURE", "150 °C / 302 °F")))
        [fact] = facts["design temperature"]
        assert fact["field_value"] == "150 °C / 302 °F"
        assert fact["unit"] == "°C" and fact["normalized_value"] == 150.0

    def test_a_pressure_in_bar_and_psi(self, tmp_path):
        facts = by_name(sheet(tmp_path, row("DESIGN PRESSURE", "10 barg / 145 psig")))
        [fact] = facts["design pressure"]
        assert fact["unit"] == "bar" and fact["normalized_value"] == pytest.approx(1.0)
        assert fact["unit_reference"] == "gauge"

    @pytest.mark.parametrize("value", [
        "20 barg / 25 barg",    # two quantities in one unit (operating / design)
        "10 barg / 150 °C",     # two dimensions
        "150 °C / 400 °F",      # does not convert: two different temperatures
        "1.02 / 1.05",          # no unit on either side
    ])
    def test_two_different_quantities_are_never_one_value(self, tmp_path, value):
        facts = by_name(sheet(tmp_path, row("DESIGN CONDITIONS", value)))
        assert "design conditions" not in facts

    def test_a_compound_unit_with_a_slash_is_not_a_dual(self):
        assert datasheets.measure_value("120 m3/h")[:2] == ("120", "m3/h")


# ===================================================== 2. ranges and sizes

class TestRangesAndSizes:
    def test_a_tilde_range_keeps_both_ends(self, tmp_path):
        [fact] = by_name(sheet(tmp_path, row("OPERATING PRESSURE", "20~25 barg")))[
            "operating pressure"]
        assert (fact["value_min"], fact["value_max"]) == (20.0, 25.0)
        assert fact["normalized_value"] is None      # a range has no single value

    def test_a_descending_tilde_pair_is_not_a_range(self):
        assert datasheets.parse_range("25~20 barg") is None

    @pytest.mark.parametrize("text,value", [
        ("1-1/2 in", "1.5"), ("3/4 in", "0.75"), ("1 1/2 inch", "1.5"), ('2-1/4"', "2.25"),
    ])
    def test_an_inch_fraction_is_a_size(self, text, value):
        assert datasheets.inch_fraction(text) == value

    def test_a_nozzle_size_is_stored_in_inches(self, tmp_path):
        [fact] = by_name(sheet(tmp_path, row("NOZZLE SIZE", "1-1/2 in")))["nozzle size"]
        assert fact["unit"] == "in" and fact["normalized_value"] == pytest.approx(38100.0)
        assert fact["value_min"] is None                 # never read as 1 to 1/2

    @pytest.mark.parametrize("text", ["5/40 mm", "3/4", "1/2 A/B", "4/4 in", "2026/09"])
    def test_a_ratio_or_code_is_not_a_fraction(self, text):
        assert datasheets.inch_fraction(text) is None


# ======================================== 3. clause numbers attached to labels

class TestClauseNumbersLeaveTheName:
    @pytest.mark.parametrize("label,name", [
        ("6.1.2 MAX ALLOW WORKING PRESSURE", "max allow working pressure"),
        ("6.1 MAX PRESSURE", "max pressure"),
        ("CASING THICKNESS [6.3.10]", "casing thickness"),
        ("HYDROTEST [8.3.2.1 b]", "hydrotest"),
    ])
    def test_the_clause_is_not_part_of_the_name(self, label, name):
        assert datasheets.normalise_field_name(label) == name

    @pytest.mark.parametrize("label,name", [
        ("4.5 KW MOTOR", "4 5 kw motor"),       # a rating, not a clause
        ("2ND STAGE IMPELLER", "2nd stage impeller"),
        ("NOTE [A]", "note a"),                  # a bracket that is not a clause
    ])
    def test_a_number_that_is_not_a_clause_stays(self, label, name):
        assert datasheets.normalise_field_name(label) == name

    def test_the_stored_row_keeps_the_printed_label(self, tmp_path):
        [fact] = by_name(sheet(tmp_path, row("CASING THICKNESS [6.3.10]", "12 mm")))[
            "casing thickness"]
        assert fact["field_label"] == "CASING THICKNESS [6.3.10]"


# ============================================== 4. YES/NO on numeric fields

class TestYesNoOnAQuantity:
    @pytest.mark.parametrize("label", [
        "NUMBER OF STAGES", "NO. OF IMPELLERS", "QTY", "HYDROTEST PRESSURE", "SHUTOFF HEAD"])
    def test_a_yes_is_never_a_count_or_a_quantity(self, label):
        assert datasheets.checkbox_on_quantity(label, "YES")

    @pytest.mark.parametrize("label,value", [
        ("VARIABLE SPEED REQUIRED", "NO"),       # a question
        ("PRESSURE TEST WITNESSED", "YES"),      # a question about a test
        ("HYDROTEST PRESSURE", "N/A"),           # does not apply: a real answer
        ("NUMBER OF STAGES", "2"),               # a number is not a checkbox
    ])
    def test_a_real_answer_stands(self, label, value):
        assert not datasheets.checkbox_on_quantity(label, value)

    def test_the_sheet_keeps_counts_and_drops_impossible_answers(self, tmp_path):
        facts = by_name(sheet(tmp_path, [
            *row("NUMBER OF STAGES", "2", 100), *row("NO. OF IMPELLERS", "YES", 115),
            *row("HYDROTEST PRESSURE", "YES", 130), *row("PRESSURE TEST WITNESSED", "YES", 145)]))
        assert facts["number of stages"][0]["field_value"] == "2"
        assert "no of impellers" not in facts and "hydrotest pressure" not in facts
        assert facts["pressure test witnessed"][0]["field_value"] == "YES"

    def test_a_trailing_integer_on_a_non_count_label_is_still_a_line_number(self):
        assert datasheets.split_label_value(["DESIGN PRESSURE", "12"]) == [
            ("DESIGN PRESSURE", "")]

    def test_a_count_followed_by_another_field_is_a_line_number(self):
        assert datasheets.split_label_value(
            ["NUMBER OF STAGES", "12", "DESIGN PRESSURE", "5 barg"])[0] == (
            "NUMBER OF STAGES", "")


# ======================================== 5. process-data rows without Units

GRID = [
    (200, 60, "MIN"), (260, 60, "NORM"), (320, 60, "RATED"),
    (40, 75, "CAPACITY m3/h"), (200, 75, "50"), (260, 75, "100"), (320, 75, "120"),
    (40, 90, "SUCTION PRESSURE barg"), (200, 90, "1.2"), (260, 90, "1.5"), (320, 90, "1.8"),
    (40, 105, "NPSHA m"), (260, 105, "6.5"),
    (40, 130, "CORROSION ALLOWANCE"), (250, 130, "3 mm"),
]


class TestProcessDataWithoutUnitsColumn:
    def test_each_value_is_under_its_column_with_the_labels_unit(self, tmp_path):
        facts = by_name(sheet(tmp_path, GRID))
        cap = {f["value_column"]: f["field_value"] for f in facts["capacity"]}
        assert cap == {"MIN": "50", "NORM": "100", "RATED": "120"}
        assert {f["unit"] for f in facts["capacity"]} == {"m3/h"}
        [npsh] = facts["npsha"]
        assert npsh["value_column"] == "NORM" and npsh["unit"] == "m"

    def test_the_flat_reader_does_not_also_store_the_row(self, tmp_path):
        facts = by_name(sheet(tmp_path, GRID))
        assert "suction pressure barg" not in facts and "capacity m3 h" not in facts
        assert len(facts["suction pressure"]) == 3

    def test_the_grid_ends_where_its_rows_end(self, tmp_path):
        facts = by_name(sheet(tmp_path, GRID))
        [ca] = facts["corrosion allowance"]
        assert ca["value_column"] is None and ca["field_value"] == "3 mm"

    def test_prose_with_column_words_is_not_a_header(self):
        """A sentence line - "Normal and rated maximum" - has three column
        words and a fourth that is not one. Laid out where a header would be,
        with a labelled number under "rated", it would otherwise be read as a
        grid and the number filed under RATED."""
        words = [(200, 60, 230, 67, "Normal"), (260, 60, 275, 67, "and"),
                 (320, 60, 350, 67, "rated"), (380, 60, 410, 67, "maximum"),
                 (40, 75, 70, 82, "FLOW"), (322, 75, 332, 82, "10")]
        assert datasheets.grid_facts(words) == []
        # The same page with a real header IS a grid - the rule above refuses
        # the sentence, not the layout.
        header = [w for w in words if w[4] != "and"]
        assert [(f["label"], f["column"]) for f in datasheets.grid_facts(header)] == [
            ("FLOW", "rated")]

    @pytest.mark.parametrize("label,expected", [
        ("CAPACITY m3/h", ("CAPACITY", "m3/h")),
        ("NPSHA (m)", ("NPSHA", "m")),
        ("PUMP TYPE OH2", ("PUMP TYPE OH2", None)),
        ("SPEED", ("SPEED", None)),
    ])
    def test_a_unit_is_split_off_a_label_only_when_it_is_a_unit(self, label, expected):
        assert datasheets.label_unit(label) == expected


# ===================================================== 6. title blocks

class TestTitleBlockIsNotAFact:
    @pytest.mark.parametrize("label,value", [
        ("JOB NO.", "21087"), ("P.O. NO.", "4500012345"), ("REQUISITION NO", "7710"),
        ("ITEM NUMBER", "12"), ("TAG #", "301"),
        # Not a bare integer, so only the title-block label list can say so.
        ("JOB NO.", "J-21087"), ("P.O. NO.", "PO-4500012345"),
    ])
    def test_an_identifier_number_is_noise(self, label, value):
        assert row_noise.noise_reason(label, value) is not None

    @pytest.mark.parametrize("label,value", [
        ("NUMBER OF STAGES", "2"), ("DESIGN PRESSURE", "16"),
        ("ITEM NO.", "09-G-411 A/B"),            # a tag, not a bare integer
        ("NO. OF IMPELLERS", "3"),
    ])
    def test_a_count_or_a_quantity_is_not_noise(self, label, value):
        assert row_noise.noise_reason(label, value) is None

    def test_the_default_path_drops_the_title_block_and_keeps_the_field(self, tmp_path):
        assert settings.geometry_reader_enabled is False
        facts = by_name(sheet(tmp_path, [
            *row("JOB NO.", "21087", 60), *row("P.O. NO.", "4500012345", 75),
            *row("DESIGN PRESSURE", "16 barg", 90)]))
        assert set(facts) == {"design pressure"}
