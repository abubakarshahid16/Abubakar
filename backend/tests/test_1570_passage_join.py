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
    "The hydrostatic pressure test is carried out on every spool and shall\n"
    "be witnessed by the inspector and the site team before release, with\n"
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
        "The hydrostatic pressure test on each and every spool of the plant is wit-\n"
        "nessed by the inspector and the site team, and the records are kept there."
    )
    found = procedure_text.find_passage(REQ, [(2, text)])
    assert found is not None
    # the quote is still what the page says; the verifier finds it there
    assert found["quote"] in text
    row = procedure_text.verdict({"source_text": REQ}, [(2, text)])
    assert row["rationale"].startswith(procedure_text.FOUND)


def test_a_compound_hyphenated_at_a_line_end_still_matches_its_hyphenated_form(on):
    req = "The self-closing valve shall be tested."
    text = (
        "On every line of the plant the vendor fits one valve of the type self-\n"
        "closing, and it is run through the shop before it is tested on site."
    )
    assert procedure_text.find_passage(req, [(1, text)]) is not None


def test_two_sentences_on_one_wrapped_run_stay_two_sentences(on):
    text = (
        "On each spool of the plant the hydrostatic pressure was then finally\n"
        "checked.\n"
        "On each spool of the plant the test records were then finally signed and\n"
        "witnessed by the inspector."
    )
    parts = [" ".join(p.split()) for p in procedure_text.sentences(text)]
    assert (
        "On each spool of the plant the hydrostatic pressure was then finally checked."
        in parts
    )
    assert (
        "On each spool of the plant the test records were then finally signed and "
        "witnessed by the inspector." in parts
    )


# --- never joined: each of these would make a false passage ----------------------------------

#: Each line holds half of REQ's words, reaches the margin and has no table, heading or list shape,
#: so these two join. Each case below changes ONE thing, so it tests that one rule.
LINE = "The hydrostatic pressure test is carried out on every spool of the plant"
NEXT = "records witnessed by the inspector and the site team before release"


def test_the_two_plain_lines_do_join_so_the_cases_below_test_something(on):
    assert not _no_passage(f"{LINE}\n{NEXT}")


@pytest.mark.parametrize(
    "text",
    [
        # a paragraph break
        f"{LINE}\n\n{NEXT}",
        # the sentence ended on the line
        f"{LINE}.\n{NEXT}",
        # the next line starts a list item
        f"{LINE}\na) {NEXT}",
        f"{LINE}\na. {NEXT}",
        f"{LINE}\niv) {NEXT}",
        f"{LINE}\no {NEXT}",
        f"{LINE}\no\n{NEXT}",
        # either line is a heading
        f"{LINE.upper()}\n{NEXT}",
        f"{LINE.title()}\n{NEXT}",
        f"{LINE}\nthe {NEXT.title()}",
        # a capital never continues a line, even one that reached the margin (unsure: no join)
        f"{LINE}\n{NEXT.capitalize()}",
        # the line stopped short of the margin: a cell or a label
        f"{LINE} and on every vessel of it too\nthe hydrostatic pressure test\n{NEXT}",
        # a page too narrow to be prose: cells, though each line fills it
        "hydrostatic pressure test\nrecords witnessed by inspector",
        # only the LINE has table shape
        f"{LINE.replace('every spool', 'every  spool')}\n{NEXT}",
        f"{LINE.replace('every spool', 'every	spool')}\n{NEXT}",
        f"{LINE} | a\n{NEXT}",
        "hydrostatic pressure tested thoroughly 14 bar\nrecords witnessed inspector and the site team",
        # only the NEXT line has table shape
        f"{LINE}\n{NEXT.replace('the site', 'the  site')}",
        f"{LINE}\n{NEXT.replace('the site', 'the	site')}",
        f"{LINE}\n{NEXT} | b",
        f"{LINE}\nrecords witnessed inspector 12 bar",
    ],
)
def test_lines_that_are_not_one_sentence_are_not_joined(on, text):
    assert _no_passage(text)


@pytest.mark.parametrize(
    "last",
    [
        # short, no figure: a sentence's last line
        "records witnessed by the inspector",
        # short, with a figure, and it ends the sentence: not a label and a value
        "records witnessed by inspector, 12 copies.",
    ],
)
def test_a_short_last_line_of_a_sentence_still_joins(on, last):
    assert not _no_passage(f"{LINE}\n{last}")


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
    first = "the hydrostatic pressure test on all spools"
    text = f"{first}\n{filler}\nrecords witnessed by the inspector on site"
    assert _no_passage(text)
    # its lines are still searched, as they are with the switch off
    assert first in procedure_text.sentences(text)


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
SPEC = (
    "On each spool the hydrostatic test is carried out at the shop and shall\n"
    "be witnessed by the purchaser."
)
HYPHEN_SPEC = (
    "On each spool of the plant, at the shop, the test named here is the hydro-\n"
    "static test, and it shall be witnessed by the purchaser."
)
FACT = {
    "field_label": "Design pressure",
    "field_name": "design_pressure",
    "field_value": "10",
    "raw_unit": "bar",
    "unit": "bar",
    "page": 2,
}
SPEC_NUMBER = (
    "On each vessel of the plant the value called the design pressure of the vessel\n"
    "shall be 12 bar at the top."
)


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


@pytest.mark.parametrize(
    "text",
    [
        "design pressure\nnormal flow 12 bar\nmax",
        (
            "A long line of ordinary words that sets the width of this page and runs to the margin.\n"
            "design pressure\nnormal flow 12 bar\nmax"
        ),
    ],
)
def test_table_cells_do_not_make_a_number_the_specification_says(on, text):
    assert spec_kit.numeric_rows([(1, text)], [FACT], "datasheet D1", "doc_d1") == []


def test_a_long_title_case_heading_stays_alone(on):
    assert "The Hydrostatic Pressure Test Of Spools And Vessels On The Plant" in (
        procedure_text.sentences(
            "The Hydrostatic Pressure Test Of Spools And Vessels On The Plant\n"
            "records witnessed by the inspector and the team."
        )
    )
