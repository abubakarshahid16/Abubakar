"""What is not a fact, and what a pressure's reference is worth.

TWO RULES, BOTH COUNTED RATHER THAN RECOGNISED, which is what makes them work
on a form this system has never seen:

  FURNITURE is a label that appears on three or more PAGES. A title block, a
  document number and a revision box repeat; a field appears where the form
  asks for it. Nothing here holds a list of known header strings - such a list
  is a description of one vendor's template.

  A VALUE must be a quantity, an explicit blank, or a closed categorical
  answer. "Prepared by: A. Engineer" has exactly the shape of a filled-in
  field and states nothing about the equipment.

AND THE REFERENCE ON A PRESSURE. `3.5 bar (ga)` and `3.5 bar` differ by an
atmosphere, in the direction that makes a vessel look compliant. The reference
is split off so `bar` reaches the conversion table, and kept so the difference
is not silently lost.

Every fixture here is synthetic and generic.
"""

from __future__ import annotations

import pytest

from app import claims, datasheets


# ------------------------------------------------------------- furniture

def test_a_label_on_three_pages_is_furniture():
    """The threshold, from the side that must be caught."""
    pairs = {
        1: [("Document number", "216400C"), ("Design pressure", "3.5 barg")],
        2: [("Document number", "216400C"), ("Shell thickness", "12 mm")],
        3: [("Document number", "216400C")],
    }

    furniture = datasheets.furniture_labels(pairs)

    assert "document number" in furniture
    # AND THE REAL FIELDS ARE NOT SWEPT UP. Without this the test would pass
    # against a rule that called everything furniture.
    assert "design pressure" not in furniture
    assert "shell thickness" not in furniture


def test_a_label_on_two_pages_is_kept():
    """THREE, NOT TWO, and this is the case that decides it.

    A multi-section datasheet legitimately asks for "Design pressure" twice -
    once for a shell and once for a jacket. At a threshold of two those become
    furniture and a real requirement disappears.
    """
    pairs = {
        1: [("Design pressure", "3.5 barg")],
        2: [("Design pressure", "8.0 barg")],
    }

    assert datasheets.furniture_labels(pairs) == set()


def test_a_label_repeated_many_times_on_one_page_is_not_furniture():
    """Counted per PAGE, not per occurrence. Five rows in one section is a
    section, not a running header."""
    pairs = {1: [("Nozzle size", "2 NPS")] * 5}

    assert datasheets.furniture_labels(pairs) == set()


# ------------------------------------------------------------ value gate

@pytest.mark.parametrize("value", ["yes", "No", "N/A", "not applicable",
                                   "Not Required", "none"])
def test_a_closed_categorical_answer_is_a_fact(value):
    """A tick-box question answered "Yes" carries no number and is still an
    answer about the equipment."""
    assert datasheets.is_categorical_value(value) is True


@pytest.mark.parametrize("value", [
    "Emad Kishta",                    # a signature
    "Al Khafji",                      # a place
    "Sour Water Drums",               # a description
    "SA 516 Gr 70N",                  # a material, which is free text here
    "",
    None,
])
def test_free_text_is_not_a_categorical_answer(value):
    """THE LIST IS CLOSED, and this is why.

    Anything open lets free text back in, and free text beside a label is what
    produced fields called "emad kishta" and "al khafji onshore facility" - a
    person and a place, recorded as properties of a pressure vessel.
    """
    assert datasheets.is_categorical_value(value) is False


# ----------------------------------------- a value, or this form's line number

def test_a_small_integer_followed_by_a_unit_is_a_value_not_a_line_number():
    """THE ROW THIS LOST, MEASURED: 4 facts recovered from 15 numeric rows.

    A numbered form writes `17 | Operating volume : | 10 | m3 | 00`, and a
    small integer is exactly what its line numbers look like AND exactly what a
    temperature in °C or a design life in years looks like. Discarding every
    one of them as a line number threw away most of a page.

    A unit in the next cell is the discriminator, because a line number is
    never followed by one.
    """
    pairs = datasheets.split_label_value(["Operating volume :", "10", "m3"])

    assert pairs == [("Operating volume :", "10 m3")]


def test_a_small_integer_followed_by_a_label_is_still_a_line_number():
    """THE GUARD. A KOC sheet is two forms side by side - "5 | Design pressure
    | 23.5 barg | 46 | Bonnet material | CS" - and 46 there really is the next
    pair's line number. It is not followed by a unit, so it still reads as one.
    """
    pairs = datasheets.split_label_value(
        ["Design pressure", "23.5 barg", "46", "Bonnet material", "CS"])

    assert ("Design pressure", "23.5 barg") in pairs
    assert ("Bonnet material", "CS") in pairs
    assert not any(label == "46" for label, _v in pairs)


# ------------------------------------------------------------ a date

@pytest.mark.parametrize("value", [
    "2024.08.27", "2024-08-27", "27/08/2024", "27.08.2024",
])
def test_a_date_is_not_a_quantity(value):
    """A signature block's timestamp parsed as a number, so the signatory's
    name became a field and the date became its value. Nothing downstream can
    tell that from a specific gravity: a number with no unit."""
    assert datasheets.is_date_value(value) is True


@pytest.mark.parametrize("value", ["3.5", "8300", "1.114", "25", "2.2"])
def test_a_measurement_is_not_mistaken_for_a_date(value):
    """The guard: real values with dots and digits must survive."""
    assert datasheets.is_date_value(value) is False


# ------------------------------------------------- gauge and absolute

@pytest.mark.parametrize("spelling", ["bar(ga)", "bar (ga)", "bar(g)", "barg"])
def test_every_gauge_spelling_yields_bar_plus_a_gauge_flag(spelling):
    assert claims.split_reference(spelling) == ("bar", "gauge")


@pytest.mark.parametrize("spelling,base", [
    ("kPaa", "kpa"), ("kPa(a)", "kPa"), ("kPa (a)", "kPa"),
    ("psia", "psi"),
])
def test_every_absolute_spelling_yields_the_base_plus_an_absolute_flag(spelling, base):
    assert claims.split_reference(spelling) == (base, "absolute")


def test_psig_is_split_rather_than_returned_whole():
    """`psig` is itself in the recognised list, so a "already a unit" check
    placed before the suffix rule would return it whole and lose the gauge
    reference. The order of those two checks is the test."""
    assert claims.split_reference("psig") == ("psi", "gauge")


def test_db_a_is_never_split_into_decibels_absolute():
    """THE REGRESSION THIS RULE COULD HAVE CAUSED, and did in a first draft.

    `dB(A)` ends in a bracketed "A". The A is a weighting curve and part of the
    unit's identity - phase 5B exists because it was once dropped. A reference
    splitter that saw "(A)" as absolute would have re-opened that defect from a
    third direction.
    """
    assert claims.split_reference("dB(A)") == ("dB(A)", None)
    # And the split still works on the same shape when it IS a reference, so
    # this is not passing because splitting stopped happening altogether.
    assert claims.split_reference("kPa(a)") == ("kPa", "absolute")


def test_a_plain_unit_has_no_reference():
    assert claims.split_reference("kPa") == ("kPa", None)
    assert claims.split_reference("Nm") == ("Nm", None)


def test_a_parenthetical_that_is_not_a_reference_is_left_alone():
    """"0.42 (6.09)" is a dual-unit value and "Design pressure (a)" is not a
    pressure in absolute."""
    assert claims.split_reference("0.42 (6.09)") == ("0.42 (6.09)", None)
    assert claims.split_reference("Design pressure (a)") == ("Design pressure (a)", None)


def test_the_reference_is_stored_on_the_fact_row():
    """THROUGH `create_fact`, WHICH IS WHERE THE FEATURE ACTUALLY LIVES.

    The test below exercises `measure_value` and `claims.split_reference`
    directly, and mutation M108 - which removes the split from `create_fact` -
    left it passing. Splitting the unit in a helper nothing calls would store
    exactly the same wrong row.

    So this one writes a fact and reads the columns back: the raw spelling as
    the sheet wrote it, the base unit the table understands, and the reference
    that is worth an atmosphere.
    """
    from app import db, submittal_review
    from app.config import settings
    from app.db import connect

    settings.db_path = settings.data_dir / "reference.sqlite"
    db.reset_connection()
    db.init_db()
    # `review_run_id` is NOT NULL in the created schema and nullable after the
    # per-document migration - facts outlive the run that first produced them.
    # `main.lifespan` runs this at startup; a test that writes a fact has to.
    submittal_review.migrate_facts_to_per_document()
    now = "2026-09-19T00:00:00Z"
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES ('sub','s.pdf','sha',1,'/tmp/s','ready',?)",
            (now,))
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
            "page_end,text,token_count,content_hash,retrievable,kind)"
            " VALUES ('sub:c0','sub','s.pdf',0,1,1,'x',1,'h',1,'prose')")

    row = datasheets.create_fact(
        submittal_document_id="sub", chunk_id="sub:c0",
        field_label="Internal design pressure :", raw_value="3.5 bar (ga)",
        page=1)

    stored = connect().execute(
        "SELECT raw_unit, unit, unit_reference, normalized_value"
        " FROM submittal_facts WHERE id = ?", (row["id"],)).fetchone()
    assert stored["raw_unit"] == "bar (ga)", "the sheet's own spelling was lost"
    assert stored["unit"] == "bar", "the base unit did not reach the table"
    assert stored["unit_reference"] == "gauge", (
        "the gauge reference was dropped - this value differs from an absolute "
        "3.5 bar by about one atmosphere")
    assert stored["normalized_value"] is not None, (
        "the base unit was not normalised, so the value cannot be compared")
    db.reset_connection()


def test_the_reference_survives_into_the_measured_cell():
    """End to end through `measure_value`, which is what the extractor calls.

    The cell keeps its spelling, the base unit reaches the table, and the
    reference is recoverable - the three things that were previously one.
    """
    value, unit, _measure = datasheets.measure_value("3.5 bar (ga)")
    base, reference = claims.split_reference(unit)

    assert value == "3.5"
    assert unit == "bar (ga)", "the raw spelling was not preserved"
    assert (base, reference) == ("bar", "gauge")


# --------------------------------------------------- units added by measurement

@pytest.mark.parametrize("cell,unit", [
    ("-10 Deg C", "Deg C"),
    ("5 wt %", "wt %"),
    ("120 ppmw", "ppmw"),
    ("2 NPS", "NPS"),
    ("50 m3/hr", "m3/hr"),
    ("5 g/litre", "g/litre"),
])
def test_a_unit_written_with_a_space_is_read_whole(cell, unit):
    """"Deg C" is two tokens and one unit. The value pattern stops at the
    space, so the cell used to be read as value `-10`, unit `Deg`, remainder
    `C` - and thrown away as prose."""
    assert datasheets.measure_value(cell)[1] == unit


@pytest.mark.parametrize("cell", [
    "2nd Stage Desalter",
    "10-05-498 & 556-05-513",
    "0.974 @ 170 OF",
])
def test_prose_beginning_with_a_digit_is_still_refused(cell):
    """THE GUARD on the rule above. Absorbing a second token only happens when
    the two together are a unit `claims` knows, so a location and a drawing
    number are still not measurements."""
    assert datasheets.measure_value(cell)[0] is None


# ------------------------------------------------------------- section

@pytest.mark.parametrize("heading", ["::", "ok", "- -", "7"])
def test_a_section_that_is_not_a_label_is_null(heading):
    """Inputs that are NOT measurements, so they reach the label test.

    The measurement cases below return None one line earlier, which means they
    never exercise the `is_field_label` guard at all - mutation M111 removed
    that guard and every one of them still passed. Species four, again: the
    test was not standing where the feature could fail it.
    """
    assert datasheets.section_heading(heading) is None


@pytest.mark.parametrize("heading", ["3.5 bar (ga)", "3 Mark", "12200", ""])
def test_a_section_that_is_not_a_heading_is_null(heading):
    """NEVER A WRONG VALUE. `chunks.section` on a ruled two-column form is
    routinely another column's text, and a wrong section tells a reader the
    value came from a part of the document it did not come from."""
    assert datasheets.section_heading(heading) is None


@pytest.mark.parametrize("heading", [
    "Process data", "Materials of construction",
    "5.7 Extent of positive material identification (PMI) :",
])
def test_a_heading_that_reads_like_a_heading_is_kept(heading):
    assert datasheets.section_heading(heading) == heading
