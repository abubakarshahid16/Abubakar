"""#913 (PF2): a requirement whose quantity is named at the END of the sentence.

"At normal flow the valve shall operate between 20 % and 80 % of its travel."
stores the subject "At normal flow the valve"; the sheet row is "Travel at
normal flow". Plain containment finds no row, so a real defect (88 %) got no
verdict. Rule A: made-up sentences, no AI, no database, runs in seconds.
"""

from __future__ import annotations

import pytest

from app import closing_noun, comparison

SENTENCE = "At normal flow the valve shall operate between 20 % and 80 % of its travel."


def _req(subject="At normal flow the valve", text=SENTENCE, **more):
    return {
        "id": "r1",
        "standard_document_id": "doc_std",
        "requirement_type": "range_limit",
        "operator": "between",
        "raw_value": "20 to 80",
        "raw_unit": "%",
        "value_low": 20.0,
        "value_high": 80.0,
        "subject": subject,
        "clause": "4.1",
        "requirement_text": text,
        "source_text": text,
        **more,
    }


def _fact(name, value="88", unit="%", **more):
    return {
        "id": f"f-{name}",
        "document_id": "doc_sheet",
        "submittal_document_id": "doc_sheet",
        "field_name": name,
        "field_value": f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "is_blank": 0,
        "page": 1,
        "extraction_method": "extracted",
        "equipment_tag": None,
        **more,
    }


def _paired(req, *facts):
    return comparison.match_by_containment(req, list(facts))["fact"]


def test_the_planted_defect_is_paired_and_does_not_meet():
    """THE CASE: the row is paired and 88 % against 20 to 80 % is a Does not meet."""
    row = _fact("Travel at normal flow")
    assert _paired(_req(), row) is row
    verdict = comparison._compare(_req(), row, submittal_facts=[row])
    assert verdict["status"] == comparison.NON_COMPLIANT


def test_the_same_shape_for_another_equipment_type():
    text = (
        "At full load the motor shall run between 60 % and 90 % of its rated current."
    )
    row = _fact("Rated current at full load", "95")
    assert _paired(_req("At full load the motor", text), row) is row


@pytest.mark.parametrize(
    "label",
    [
        "Travel",  # one word: never claims a clause that merely says it
        "Best efficiency flow",  # the reference of a ratio, not the quantity
        "Travel at maximum flow",  # another condition: not this clause's row
    ],
)
def test_a_label_that_does_not_straddle_the_join_never_pairs(label):
    text = "At normal flow the valve shall operate between 20 % and 80 % of the best efficiency flow."
    assert _paired(_req(text=text), _fact(label)) is None
    assert _paired(_req(), _fact(label)) is None


def test_a_condition_the_clause_opens_with_is_not_the_quantity_it_is_about():
    """"At normal flow the valve ... travel": "Normal flow" is the CONDITION the
    sentence opens with (it stands after "at"), not what the clause is about, so
    it no longer claims the clause (audit C5, #1290s pairing rule); the closing
    noun finds the travel row."""
    plain = _fact("Normal flow")
    other = _fact("Travel at normal flow")
    assert _paired(_req(), plain, other) is other


def test_a_plain_pairing_is_left_alone_when_the_label_heads_the_subject():
    """When the subject already holds the label as its head, the closing noun is
    not consulted."""
    plain = _fact("Normal flow")
    other = _fact("Travel at normal flow")
    assert _paired(_req(subject="Normal flow the valve"), plain, other) is plain


def test_two_rows_that_both_fit_are_a_tie_not_a_pick():
    one, two = (
        _fact("Travel at normal flow", equipment_tag="V-1"),
        _fact("Travel at normal flow", value="70"),
    )
    result = comparison.match_by_containment(_req(), [one, two])
    assert result["fact"] is None


def test_without_a_closing_noun_nothing_changes():
    req = _req("The valve", "The valve shall operate between 20 % and 80 %.")
    assert _paired(req, _fact("Travel at normal flow")) is None


@pytest.mark.parametrize(
    "text, phrase",
    [
        (SENTENCE, "travel"),
        (
            "The rated flow shall lie between 80 % and 110 % of the best efficiency flow.",
            "best efficiency flow",
        ),
        ("The pressure shall be at least 5 bar.", ""),
        ("", ""),
    ],
)
def test_the_closing_phrase(text, phrase):
    assert closing_noun.closing_phrase(text) == phrase


def test_a_blank_row_is_paired_only_when_no_number_answers():
    """Numbers first, a "vendor to advise" row only when no number row fits."""
    blank = _fact("Travel at normal flow", value="", unit="", is_blank=1)
    assert _paired(_req(), blank) is blank
    number = _fact("Travel at normal flow")
    assert _paired(_req(), blank, number) is number


def test_a_row_in_another_dimension_is_refused_by_the_same_match_rules():
    assert _paired(_req(), _fact("Travel at normal flow", "9", "mm")) is None
