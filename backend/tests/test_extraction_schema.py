"""B50: a model row that fails the schema is refused, never coerced.

THE TWO MALFORMATIONS BELOW ARE REAL. They were returned by qwen3.5:9b on the
frozen Phase 0.5 packet and recorded verbatim in the run artifact: the string
"None" where a list was specified, and the string "page 4" where an integer
was. Neither was caught at the time, for the only reason that nothing read
them. They are the fixtures here because a schema tested only against
hypothetical malformations proves only that the author could imagine them.

No client content: every label, value and source span below is invented.
"""
from __future__ import annotations

import pytest

from app import extraction_schema, quotes

GOOD = {
    "label": "Design pressure",
    "column_header": "Rated",
    "value": "3.5",
    "unit": "bar (ga)",
    "is_blank": False,
    "page": 4,
    "source_text": "Design pressure : 3.5 bar (ga)",
}


def test_a_well_formed_row_is_accepted():
    """The control. Without it every test here could pass by refusing
    everything, which is the vacuous-test failure this project has shipped
    before."""
    row, reason = extraction_schema.validate_row(dict(GOOD))

    assert reason is None
    assert row is not None
    assert row.page == 4 and row.column_header == "Rated"


# ============================================ the two malformations, verbatim


def test_a_page_given_as_the_string_page_4_is_refused():
    """A-2 RETURNED EXACTLY THIS. `quotes.check_proposal` does an unguarded
    `int(expected_page)`, so "page 4" would raise ValueError rather than be
    refused - a malformation becoming a 500. It is refused here instead, before
    anything downstream can touch it."""
    row, reason = extraction_schema.validate_row({**GOOD, "page": "page 4"})

    assert row is None
    assert "page" in reason and extraction_schema.ROW_INVALID in reason


def test_the_string_none_is_never_read_as_an_absence():
    """A-2 RETURNED `missing_evidence: "None"` where a list was specified. The
    string "None" is TRUE and non-empty, so `if not value` reads it as evidence
    present - the value means its own opposite. Here the same shape is a
    `column_header` that is the string "None" while the field is genuinely
    unscoped: it must not pass as if a column had been determined."""
    row, _ = extraction_schema.validate_row({**GOOD, "column_header": "None"})

    assert row is not None, "a string column_header is structurally valid"
    assert row.column_header == "None", (
        "the schema must not silently turn the string 'None' into an absence - "
        "that is the coercion this module exists to refuse")
    assert row.column_header != "", "'None' is not the same as unscoped"


@pytest.mark.parametrize("page", ["4", 4.0, None, "", "four", 0, -1])
def test_a_page_that_is_not_a_real_integer_is_refused(page):
    """Including the string "4". Pydantic would accept it in lenient mode, and
    lenient parsing IS the coercion this module refuses: a model that returned
    a string did not follow the contract, whatever the string contains."""
    row, reason = extraction_schema.validate_row({**GOOD, "page": page})

    assert row is None, f"page={page!r} was accepted"
    assert extraction_schema.ROW_INVALID in reason


@pytest.mark.parametrize("field", ["label", "value", "source_text"])
def test_a_required_string_that_is_blank_is_refused(field):
    """Whitespace is not a value. A row with an empty source span cannot be
    checked by B23 against the page, so it can never be proven."""
    row, reason = extraction_schema.validate_row({**GOOD, field: "   "})

    assert row is None
    assert field in reason


def test_a_key_the_model_was_never_asked_for_is_refused():
    """`extra="forbid"`, for the same reason `PairChoice` uses it: a response
    carrying a key it was not offered did not follow the contract."""
    row, reason = extraction_schema.validate_row({**GOOD, "confidence": 0.9})

    assert row is None
    assert "confidence" in reason


def test_is_blank_must_be_a_boolean_not_a_word():
    """"true" is a string. A blank-by-design slot and a slot holding the word
    "true" are different claims about the sheet."""
    row, reason = extraction_schema.validate_row({**GOOD, "is_blank": "true"})

    assert row is None
    assert "is_blank" in reason


# ================================================== whole-page responses


def test_a_response_that_will_not_parse_is_a_page_refusal_with_a_reason():
    """Not an empty page. Those are different facts about the page, and only
    one of them is about the page at all - B44's distinction, applied to the
    model instead of the file."""
    rows, refusals = extraction_schema.validate_page_response("{not json at all")

    assert rows == []
    assert len(refusals) == 1
    assert extraction_schema.PAGE_UNPARSEABLE in refusals[0]


def test_an_empty_response_is_a_refusal_not_a_page_with_no_values():
    rows, refusals = extraction_schema.validate_page_response("")

    assert rows == []
    assert extraction_schema.PAGE_UNPARSEABLE in refusals[0]


def test_one_bad_row_does_not_discard_the_good_rows_beside_it():
    """A page is not all-or-nothing: the valid rows are kept, the invalid one
    is refused BY INDEX so it can be found in the response again."""
    body = ('[{"label": "A", "column_header": "", "value": "1", "unit": "mm",'
            ' "is_blank": false, "page": 1, "source_text": "A : 1 mm"},'
            ' {"label": "B", "column_header": "", "value": "2", "unit": "mm",'
            ' "is_blank": false, "page": "page 1", "source_text": "B : 2 mm"}]')

    rows, refusals = extraction_schema.validate_page_response(body)

    assert [r.label for r in rows] == ["A"]
    assert len(refusals) == 1 and refusals[0].startswith("row 1:")


def test_a_fenced_response_is_read_rather_than_refused():
    """Models fence JSON in markdown constantly. That is a formatting habit,
    not a contract breach, and refusing it would refuse correct rows."""
    body = '```json\n[{"label": "A", "column_header": "", "value": "1",' \
           ' "unit": "", "is_blank": false, "page": 2, "source_text": "A : 1"}]\n```'

    rows, refusals = extraction_schema.validate_page_response(body)

    assert refusals == []
    assert [r.page for r in rows] == [2]


def test_the_validated_page_is_safe_for_the_quote_validator():
    """THE POINT OF THE WHOLE MODULE, asserted end to end: what B23 receives
    has already been through the schema, so `"page 4"` cannot reach an int().

    The second half proves the danger is real rather than imagined - the same
    malformed value, passed directly, raises."""
    rows, _ = extraction_schema.validate_page_response(
        '[{"label": "A", "column_header": "", "value": "1", "unit": "",'
        ' "is_blank": false, "page": 3, "source_text": "A : 1"}]')

    report = quotes.validate_citation(
        rows[0].source_text, source_text="A : 1",
        expected_page=3, actual_page=rows[0].page)
    assert report["valid"], report

    with pytest.raises(ValueError):
        quotes.validate_citation("A : 1", source_text="A : 1",
                                 expected_page=3, actual_page="page 3")
