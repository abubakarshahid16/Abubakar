"""Order 307 (extension of 307.1): a held row whose field WAS read on the sheet never says "Not read from the
datasheet"; it says where the value was read and that it is not tied to the row. Invented sheets only."""

from __future__ import annotations

import uuid

import pytest

from app import crs_mapping, crs_page_words, db, submittal_review
from tests.test_228_page_column import (  # noqa: F401 - fixture and helpers
    NOW,
    _finding,
    _sheet,
    temp_storage,
)

pytestmark = pytest.mark.usefixtures("temp_storage")


@pytest.fixture(autouse=True)
def _review_tables(request):
    request.getfixturevalue("temp_storage")
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()


TAGS = [f"PSV-{n}" for n in range(1, 6)]


def _fact(doc, name, page, value="12", *, label=None, blank=0, superseded=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO submittal_facts (id, review_run_id, submittal_document_id, field_name, field_label,"
            " field_value, raw_value, page, is_blank, extraction_method, created_at, updated_at, superseded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,'extracted',?,?,?)",
            (
                str(uuid.uuid4()),
                None,
                doc,
                name,
                label or name,
                value,
                None if blank else value,
                page,
                blank,
                NOW,
                NOW,
                NOW if superseded else None,
            ),
        )


def _cell(doc, label="Overpressure"):
    group = [
        _finding(doc, tag, crs_field_label=label, contractor_section=label)
        for tag in TAGS
    ]
    return crs_mapping._page_section(group)


def test_a_field_read_on_other_pages_is_never_called_not_read():
    doc = _sheet(5)
    for page in (1, 2, 3, 4):
        _fact(doc, "overpressure", page, "21")
    cell = _cell(doc)
    assert "Not read" not in cell
    assert cell == (
        "Overpressure: A value was read on pages 1, 2, 3, 4, "
        "not tied to this row (PSV-1, PSV-2, PSV-3 and 2 more); engineer to confirm"
    )


def test_the_label_is_matched_the_way_pairing_matches_it():
    doc = _sheet(5)
    _fact(doc, "over pressure", 2, "21", label="Over pressure %")
    assert "was read on page 2," in _cell(doc, "Overpressure")


def test_a_field_never_read_still_says_not_read():
    doc = _sheet(5)
    _fact(doc, "set pressure", 1)
    assert _cell(doc).startswith("Not read from the datasheet (5 pages) - Overpressure")


def test_a_blank_value_is_not_a_value_that_was_read():
    doc = _sheet(5)
    _fact(doc, "overpressure", 1, "*", blank=1)
    assert _cell(doc).startswith("Not read from the datasheet")


def test_a_probable_match_is_said_as_one():
    doc = _sheet(5)
    _fact(doc, "viscosity at inlet conditions", 4, "0.01")
    cell = _cell(doc, "Viscosity inlet")
    assert (
        "A value that may be this field was read on page 4," in cell
        and "Not read" not in cell
    )


def test_one_word_names_are_never_matched_by_containment():
    doc = _sheet(5)
    _fact(doc, "set pressure tolerance", 1, "3")
    assert _cell(doc, "Pressure").startswith("Not read from the datasheet")


def test_a_row_that_has_its_own_page_is_untouched():
    doc = _sheet(5)
    _fact(doc, "overpressure", 3, "21")
    group = [
        _finding(
            doc, "V-1", crs_field_label="Overpressure", contractor_page=2, fact_id="f1"
        )
    ]
    assert crs_mapping._page_section(group) == "p.2 - Overpressure (V-1)"


def test_facts_of_another_submittal_are_not_counted():
    doc, other = _sheet(5), _sheet(5)
    _fact(other, "overpressure", 1, "21")
    assert _cell(doc).startswith("Not read from the datasheet")


def test_a_database_without_review_tables_falls_back_to_the_old_cell(monkeypatch):
    doc = _sheet(5)
    with db.connect() as conn:
        conn.execute("DROP TABLE submittal_facts")
    assert _cell(doc).startswith("Not read from the datasheet (5 pages)")


def test_where_without_a_label_behaves_as_before():
    doc = _sheet(5)
    assert (
        crs_page_words.where([], "", "Size", [], {doc}, False)
        == "Not read from the datasheet (5 pages) - Size"
    )


def test_a_value_a_later_pass_replaced_is_not_the_final_read():
    """cloud-2's pin: the cell counts the final read only. A replaced value is not "was read"; the row keeps the
    old words (the reader's gap is the engineer's question, not a claim the final read cannot support)."""
    doc = _sheet(5)
    _fact(doc, "overpressure", 1, "21", superseded=True)
    assert _cell(doc).startswith("Not read from the datasheet (5 pages)")


def test_a_value_read_with_no_page_recorded_never_prints_page_none():
    doc = _sheet(5)
    _fact(doc, "overpressure", None, "21")
    cell = _cell(doc)
    assert "None" not in cell and "was read on a page that was not recorded" in cell
    _fact(doc, "overpressure", 2, "21")
    assert "pages" not in _cell(
        doc
    ) and "page 2 and a page that was not recorded" in _cell(doc)
