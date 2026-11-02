"""#1570: a printed line is not a sentence. Wrapped lines are joined before the keyword search,
the page is kept, and the quote still verifies on that page's stored text.

Invented text only, built here (CLAUDE.md rule 3). No model, no socket.
"""

from __future__ import annotations

import pytest

from app import procedure_text, spec_kit
from app.config import settings

REQ = "The hydrostatic pressure test records shall be witnessed by the inspector."
WRAPPED = (
    "The hydrostatic pressure test shall\n"
    "be witnessed by the inspector and the\n"
    "records kept on site."
)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "pdf_passage_join_lines_enabled", True)


def _no_passage(text: str) -> bool:
    return procedure_text.find_passage(REQ, [(1, text)]) is None


# --- the fix -------------------------------------------------------------------------------


def test_a_wrapped_sentence_is_found_and_keeps_its_page(on):
    found = procedure_text.find_passage(REQ, [(1, "Other words."), (7, WRAPPED)])
    assert found["page"] == 7
    assert " ".join(found["quote"].split()) == " ".join(WRAPPED.split())


def test_a_wrapped_passage_verifies_on_the_stored_page_text(on):
    row = procedure_text.verdict({"source_text": REQ}, [(7, WRAPPED)])
    assert row["rationale"].startswith(procedure_text.FOUND)
    assert "found on page 7" in row["rationale"]
    assert " ".join(WRAPPED.split()) in row["rationale"]
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"


def test_the_returned_quote_is_a_true_slice_of_the_page(on):
    page = f"Scope of this plan.\n{WRAPPED}\nNext sentence here."
    found = procedure_text.find_passage(REQ, [(3, page)])
    assert found["quote"] in page


def test_a_word_hyphenated_at_a_line_end_is_read_as_one_word(on):
    text = (
        "The hydro-\nstatic pressure test shall be wit-\n"
        "nessed by the inspector and the records kept."
    )
    found = procedure_text.find_passage(REQ, [(2, text)])
    assert found is not None
    # the quote is still what the page says; the verifier finds it there
    assert found["quote"] in text
    row = procedure_text.verdict({"source_text": REQ}, [(2, text)])
    assert row["rationale"].startswith(procedure_text.FOUND)


def test_a_compound_hyphenated_at_a_line_end_still_matches_its_hyphenated_form(on):
    req = "The self-closing valve shall be tested."
    text = "The self-\nclosing valve shall be\ntested by the vendor on site."
    assert procedure_text.find_passage(req, [(1, text)]) is not None


def test_a_full_line_continues_onto_a_capitalised_word(on):
    # Proper nouns start lines in engineering prose: a line that ran to the margin is wrapped.
    text = (
        "The hydrostatic pressure test is run on every spool of the plant and is seen by\n"
        "Inspector staff, who have witnessed the records on site for the whole project."
    )
    assert not _no_passage(text)


def test_two_sentences_on_one_wrapped_run_stay_two_sentences(on):
    text = "Hydrostatic pressure was\nchecked.\nThe test records were\nwitnessed by the inspector."
    parts = [" ".join(p.split()) for p in procedure_text.sentences(text)]
    assert "Hydrostatic pressure was checked." in parts
    assert "The test records were witnessed by the inspector." in parts


# --- never joined: each of these would make a false passage ----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # a paragraph break
        "The hydrostatic pressure test\n\nrecords witnessed by the inspector",
        # sentence ended on the line
        "The hydrostatic pressure test.\nrecords witnessed by the inspector",
        # the next line is a list item, by bullet, number, letter or roman
        "The hydrostatic pressure test\n- records witnessed by the inspector",
        "The hydrostatic pressure test\n• records witnessed by the inspector",
        "The hydrostatic pressure test\n•\nrecords witnessed by the inspector",
        "The hydrostatic pressure test\no\nrecords witnessed by the inspector",
        "The hydrostatic pressure test\no records witnessed by the inspector",
        "The hydrostatic pressure test\n2. records witnessed by the inspector",
        "The hydrostatic pressure test\n4.1.2 records witnessed by the inspector",
        "The hydrostatic pressure test\na) records witnessed by the inspector",
        "The hydrostatic pressure test\n(iv) records witnessed by the inspector",
        # the next line, or this one, is a heading
        "THE HYDROSTATIC PRESSURE TEST\nrecords witnessed by the inspector",
        "The hydrostatic pressure test\nRECORDS WITNESSED BY THE INSPECTOR",
        # a short line before a capital is a title or a cell, not a wrapped line
        (
            "A long line of ordinary words that sets the width of this page of text.\n"
            "The hydrostatic pressure test\nRecords witnessed by the inspector"
        ),
        # a capital whose first word would have fitted: a list of references, not a wrapped line
        (
            "A long line of ordinary words that sets the width of this page and runs on to the margin.\n"
            "EN 100, Hydrostatic pressure test of steel flat product (method)\n"
            "EN 134, Records witnessed by the inspector"
        ),
        # an entry of a reference list, even after a line that did reach the margin
        (
            "EN 100, Hydrostatic pressure test of steel flat product of thickness over 6 mm (method)\n"
            "EN 134, Records witnessed by the inspector"
        ),
        # table rows
        "| hydrostatic pressure test |\n| records witnessed by the inspector |",
        "hydrostatic pressure test | a\nrecords witnessed by the inspector | b",
        "hydrostatic pressure   test\nrecords   witnessed by the inspector",
        "hydrostatic\tpressure test\nrecords\twitnessed by the inspector",
        "The hydrostatic pressure test\n10\nrecords witnessed by the inspector",
    ],
)
def test_lines_that_are_not_one_sentence_are_not_joined(on, text):
    assert _no_passage(text)


def test_a_sentence_does_not_run_across_pages(on):
    pages = [
        (1, "The hydrostatic pressure test shall"),
        (2, "be witnessed by the inspector and the records kept."),
    ]
    assert procedure_text.find_passage(REQ, pages) is None


def test_a_run_too_long_to_quote_whole_is_not_a_passage(on):
    # No punctuation for many lines is not a sentence, it is a list or a column. Joined, it would
    # gather the requirement's words from unrelated lines, and the quote would be cut short.
    filler = "\n".join(
        f"and another plain line of words number {w}" for w in "abcdefghijkl"
    )
    text = (
        f"the hydrostatic pressure test\n{filler}\nrecords witnessed by the inspector"
    )
    assert _no_passage(text)
    # its lines are still searched, as they are with the switch off
    assert "the hydrostatic pressure test" in procedure_text.sentences(text)


# --- switch off ------------------------------------------------------------------------------


def test_switch_is_off_by_default():
    assert settings.pdf_passage_join_lines_enabled is False


def test_switch_off_finds_nothing_in_a_wrapped_sentence():
    assert _no_passage(WRAPPED)


@pytest.mark.parametrize(
    "text",
    [
        WRAPPED,
        "",
        "\n\n",
        "  One sentence.  Two sentences;\r\nthree lines\n\n four: five! six?\tseven ",
        "pro-\ncedure | cell\n•\nitem",
    ],
)
def test_switch_off_splits_exactly_as_before(text):
    assert procedure_text.sentences(text) == procedure_text._SENTENCE_END.split(text)


def test_switch_off_returns_the_same_passage_as_before():
    text = "Scope.\n  The inspector shall witness hydrostatic pressure test records.  \nEnd."
    assert procedure_text.find_passage(REQ, [(4, text)]) == {
        "page": 4,
        "quote": "The inspector shall witness hydrostatic pressure test records.",
    }


# --- the other homes of the split (rule 8) ---------------------------------------------------

ITEM = {"terms": [["hydrostatic", "witnessed"]]}
SPEC = "The hydrostatic test shall\nbe witnessed by the purchaser."
HYPHEN_SPEC = "The hydro-\nstatic test shall be witnessed by the purchaser."
FACT = {
    "field_label": "Design pressure",
    "field_name": "design_pressure",
    "field_value": "10",
    "raw_unit": "bar",
    "unit": "bar",
    "page": 2,
}
SPEC_NUMBER = "The design pressure of the vessel\nshall be 12 bar at the top."


def test_spec_kit_item_search_reads_a_wrapped_sentence(on):
    found = spec_kit.find_item(ITEM, [(5, SPEC)])
    assert found == {"page": 5, "quote": " ".join(SPEC.split())}


def test_spec_kit_item_search_off_is_as_before():
    assert spec_kit.find_item(ITEM, [(5, SPEC)]) is None


def test_spec_kit_item_search_reads_a_hyphenated_word_and_its_quote_verifies(on):
    found = spec_kit.find_item(ITEM, [(5, HYPHEN_SPEC)])
    assert found == {"page": 5, "quote": " ".join(HYPHEN_SPEC.split())}


def test_spec_kit_numeric_rows_read_a_wrapped_sentence(on):
    rows = spec_kit.numeric_rows([(1, SPEC_NUMBER)], [FACT], "datasheet D1", "doc_d1")
    assert len(rows) == 1 and "12 bar" in rows[0]["finding"]


def test_spec_kit_numeric_rows_off_is_as_before():
    assert (
        spec_kit.numeric_rows([(1, SPEC_NUMBER)], [FACT], "datasheet D1", "doc_d1")
        == []
    )
