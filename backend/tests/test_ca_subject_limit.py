"""A clause that states its limit as "The maximum/minimum <subject> shall be <value> <unit>" is a number rule, and code can prove a Pass or Fail on it
(owner, 16 Nov 2026, the corrosion allowance of a vessel). Invented sentences and values; no database, no model.

Each test names the risk it guards:
  * the parser reads the shape (the comparator word in front of the subject, the value after "shall be") and refuses what it cannot read safely;
  * a registered field NAME that starts with a comparator word ("maximum allowable working pressure") is not a limit on anything;
  * the rule item carries the limit as the clause PRINTS it (mm), so the clause quote can be asked for it, and a unit stored normalised (um) no longer
    makes every such proof fail;
  * the code proof shows the direction and the subject of that shape ("C.A." for the corrosion allowance), through the exit: Proven by code only then;
  * a wrong direction, a different value, a different subject, or a condition held still end as a Query.
"""

from __future__ import annotations

import pytest

from app import agent_review_calculator as calc
from app import agent_review_code_proof as proof
from app import agent_review_wording as W
from app import requirements_3b as r3b
from app.own_value_limit import subject_be
from tests import b1_pages

MAX_CLAUSE = "7.1.2.3 The maximum C.A. shall be 3.2 mm (1/8”)."
MIN_CLAUSE = "A minimum C.A. of at least 1.6 mm (1/16”) shall be used."


@pytest.mark.parametrize(
    ("sentence", "operator", "raw_value", "raw_unit"),
    [
        (MAX_CLAUSE, "<=", "3.2", "mm"),
        ('The maximum C.A. shall be 3.2 mm (1/8") .', "<=", "3.2", "mm"),
        ("The minimum wall thickness shall be 6 mm.", ">=", "6", "mm"),
        ("The max flow rate must be 40 m3/h.", "<=", "40", "m3/h"),
        ("The minimum C.A. shall be 1.5 mm, as a rule.", ">=", "1.5", "mm"),
    ],
)
def test_the_shape_is_read_as_a_limit_with_the_clauses_own_comparator(
    sentence, operator, raw_value, raw_unit
):
    got = subject_be(sentence)
    assert got is not None and (got["operator"], got["raw_value"], got["raw_unit"]) == (
        operator,
        raw_value,
        raw_unit,
    )
    assert (
        r3b.parse_limit(sentence)["operator"] == operator
    )  # the extractor reads it the same way
    assert r3b.classify(sentence, r3b.parse_limit(sentence)) == "numeric_limit"


@pytest.mark.parametrize(
    "sentence",
    [
        "The maximum C.A. shall not be 3.2 mm.",  # the other direction of a negation
        "The maximum C.A. shall be 3.2 mm or 5 mm.",  # a choice of values
        "The maximum C.A. shall be 3.2 mm (1/4”).",  # a bracket that is not the same figure
        "The maximum C.A. shall be 3.2 mm, minus 1 mm.",  # a phrase that moves the number
        "The maximum allowable working pressure shall be 12 barg.",  # a registered field name, not a limit on one
        "The maximum number of passes shall be 3.",  # no unit
        "The C.A. shall be 3.2 mm.",  # no comparator word: a nominal value, not this shape
        "Item 5 mm. The maximum C.A. shall be 3.2 mm of the lesser of two.",  # a word that chooses
        "(5 mm), or the minimum nominal wall thickness shall be 0.154 in.",  # an alternative of two thresholds
    ],
)
def test_what_cannot_be_read_safely_stays_a_statement(sentence):
    assert subject_be(sentence) is None


def test_a_clause_number_in_front_is_not_a_figure_before_the_comparator():
    assert subject_be("7.1.2.3 The maximum C.A. shall be 3.2 mm.") is not None
    assert (
        subject_be("Add 5 mm maximum C.A. shall be 3.2 mm.") is None
    )  # a figure right before the comparator is another quantity


ITEM = {
    "item_id": "R-7123",
    "source": "rule",
    "standard": "STD-1",
    "clause": "7.1.2.3",
    "rule_kind": "limit",
    "comparator": "<=",
    "value": 3200.0,
    "unit": "um",
    "raw_value": "3.2",
    "raw_unit": "mm",
    "question": MAX_CLAUSE,
    "rule_version_id": "v1",
    "standard_document_id": "std1",
    "rule_label": {"tier": "AI approved"},
    "field_roles": ["corrosion_allowance"],
}  # the stored row keeps the limit twice: normalised (3200 um) and as printed (3.2 mm)
PAGE = "Design data.\nCorrosion allowance : 3.2 mm\nDesign pressure : 10 bar\n"


@pytest.fixture(autouse=True)
def _pages(monkeypatch):
    return b1_pages.install(
        monkeypatch
    )  # the exit re-reads the page from the store: a test gives it the page


def _line(raw="3.2", unit="mm", clause=MAX_CLAUSE, page=PAGE, item=ITEM, **over):
    fact = {
        "id": "f1", "field_label": "Corrosion allowance", "raw_value": raw, "raw_unit": unit, "unit": unit, "page": 1, "is_blank": False,
        "source_text": f"Corrosion allowance : {raw} {unit}", "equipment_tag": "T1", **over,
    }  # fmt: skip
    return calc.numeric_line(
        item,
        calc.requirement_from_item(item),
        fact,
        submittal_facts=[fact],
        page_text=page,
        clause_quote=clause,
        clause_text=clause,
        page_count=1,
    )


def _exit(line, item=ITEM):
    return W.final_cap(line, item, None, skill_ids=frozenset())


def test_a_value_at_the_maximum_is_a_proven_pass_through_the_exit_and_above_it_a_proven_fail():
    ok, bad = (
        _exit(_line("3.2")),
        _exit(_line("4.0", page="Corrosion allowance : 4.0 mm\n")),
    )
    assert (ok["verdict"], ok["verdict_class"]) == ("Pass", "Proven by code")
    assert (bad["verdict"], bad["verdict_class"]) == ("Fail", "Proven by code")


def test_the_proof_asks_the_clause_quote_for_the_limit_as_printed_not_the_normalised_figure():
    """Before: raw_value "3200.0" / "um" was asked of a quote that prints "3.2 mm", so no rule stored in mm could ever be proven."""
    req = calc.requirement_from_item(ITEM)
    assert (req["raw_value"], req["raw_unit"]) == ("3.2", "mm")
    old = {k: v for k, v in ITEM.items() if k not in ("raw_value", "raw_unit")}
    assert (
        calc.requirement_from_item(old)["raw_value"],
        calc.requirement_from_item(old)["raw_unit"],
    ) == ("3200.0", "um")  # a row without them: as before


def test_the_direction_and_the_subject_of_the_shape_are_shown_by_the_clause_quote():
    req = calc.requirement_from_item(ITEM)
    assert proof.clause_reason(req, MAX_CLAUSE) is None
    assert proof.direction_reason(req, MAX_CLAUSE) is None
    assert proof.subject_reason("corrosion_allowance", req, MAX_CLAUSE) is None
    # the other direction, and the other quantity: still refused
    assert (
        proof.direction_reason({**req, "operator": ">="}, MAX_CLAUSE)
        == proof.DIRECTION_WHY
    )
    other = MAX_CLAUSE.replace("C.A.", "wall thickness")
    assert proof.subject_reason("corrosion_allowance", req, other) == proof.SUBJECT_WHY


def test_a_dotted_abbreviation_does_not_end_the_sentence_that_names_the_subject():
    assert proof._SENTENCE_BREAK.split("The maximum C.A. shall be 3.2 mm.") == [
        "The maximum C.A. shall be 3.2 mm."
    ]
    assert (
        len(
            proof._SENTENCE_BREAK.split(
                "Noise is low. The maximum C.A. shall be 3.2 mm."
            )
        )
        == 2
    )


def test_a_clause_that_names_another_field_before_the_figure_is_still_not_about_the_field():
    quote = "The design pressure is 10 bar. The maximum C.A. shall be 3.2 mm."
    assert (
        proof.subject_reason(
            "corrosion_allowance", calc.requirement_from_item(ITEM), quote
        )
        is None
    )
    wrong = "The maximum design pressure drop shall be 3.2 mm of the C.A."
    assert (
        proof.subject_reason(
            "corrosion_allowance", calc.requirement_from_item(ITEM), wrong
        )
        == proof.SUBJECT_WHY
    )


def test_a_different_value_a_blank_or_another_unit_family_is_never_proven():
    assert _exit(_line("3.2", unit="bar"))["verdict_class"] != "Proven by code"
    assert _exit(_line("", is_blank=True))["verdict_class"] != "Proven by code"
    swapped = _line(
        clause=MAX_CLAUSE.replace("3.2 mm", "5 mm")
    )  # the quote no longer states the limit that was compared
    assert _exit(swapped)["verdict_class"] != "Proven by code"


def test_the_minimum_clause_with_a_condition_is_held_not_proven_while_its_condition_is_not_established():
    from app import comparison

    row = {
        "requirement_type": "numeric_limit",
        "operator": ">=",
        "raw_value": "1.6",
        "raw_unit": "mm",
        "condition": "carbon steel",
        "value": 1600.0,
        "unit": "um",
    }
    got = comparison.compare(
        {**row, "field": "corrosion_allowance"},
        {
            "raw_value": "3.2",
            "raw_unit": "mm",
            "is_blank": False,
            "field_label": "Corrosion allowance",
        },
        submittal_facts=[],
    )
    assert (
        got["status"] == "NEEDS_ENGINEER_REVIEW"
    )  # the condition is not established by the sheet: no arithmetic


# ---- the qualifier of the field's name: a clause about ANOTHER KIND of the field is not proof for the paper's field ----------------------------------------

EXTERNAL = "(2) The maximum external design pressure shall not exceed 15 psi (100 kPa)."
PRESSURE_ITEM = {
    "item_id": "R-ext", "source": "rule", "standard": "STD-1", "clause": "2.5", "rule_kind": "limit", "comparator": "<=", "value": 0.1034214, "unit": "MPa", "raw_value": "15",
    "raw_unit": "psi", "question": EXTERNAL, "rule_version_id": "v2", "standard_document_id": "std1", "rule_label": {"tier": "AI approved"}, "field_roles": ["design_pressure"],
}  # fmt: skip


def _pressure_line(label, quote, clause=EXTERNAL):
    fact = {
        "id": "f2",
        "field_label": label,
        "raw_value": "3.5",
        "raw_unit": "bar",
        "unit": "bar",
        "page": 1,
        "is_blank": False,
        "source_text": quote,
        "equipment_tag": "T1",
    }
    return calc.numeric_line(
        PRESSURE_ITEM,
        calc.requirement_from_item(PRESSURE_ITEM),
        fact,
        submittal_facts=[fact],
        page_text=quote + "\n",
        clause_quote=clause,
        clause_text=clause,
        page_count=1,
    )


def test_a_clause_about_the_external_pressure_is_not_proof_against_the_internal_design_pressure():
    """Found on the vessel copy: with the limit asked as printed (15 psi), the rule 'maximum external design pressure' was proven FAIL against 'Internal design pressure : 3.5 bar'."""
    wrong = _exit(
        _pressure_line(
            "Internal design pressure", "Internal design pressure : 3.5 bar"
        ),
        PRESSURE_ITEM,
    )
    assert wrong["verdict_class"] != "Proven by code" and wrong["verdict"] == "Query"
    req = calc.requirement_from_item(PRESSURE_ITEM)
    assert (
        proof.qualifier_reason(
            "design_pressure", req, EXTERNAL, "Internal design pressure"
        )
        == proof.QUALIFIER_WHY
    )


@pytest.mark.parametrize(
    ("clause", "label", "refused"),
    [
        (
            "(2) The maximum external design pressure shall not exceed 15 psi.",
            "External design pressure",
            False,
        ),  # the same qualifier on both sides
        (
            "The design pressure shall not exceed 15 psi.",
            "Design pressure",
            False,
        ),  # none on either side
        (
            "The maximum design pressure shall not exceed 15 psi.",
            "Design pressure",
            False,
        ),  # a comparator word qualifies nothing
        (
            "The design pressure shall not exceed 15 psi.",
            "Internal design pressure",
            True,
        ),  # the paper's label qualifies, the clause does not
        (
            "The maximum external design pressure shall not exceed 15 psi.",
            "Design pressure",
            True,
        ),  # the clause qualifies, the label does not
        (
            "The maximum external design pressure shall not exceed 15 psi.",
            "MAWP",
            False,
        ),  # the label does not carry the name: not compared here
    ],
)
def test_the_qualifier_words_in_front_of_the_field_name_must_be_the_same_on_both_sides(
    clause, label, refused
):
    req = {"raw_value": "15", "raw_unit": "psi", "operator": "<="}
    got = proof.qualifier_reason("design_pressure", req, clause, label)
    assert (got is not None) is refused


def test_the_checks_of_the_line_say_the_clause_is_not_about_that_field_when_the_qualifiers_differ():
    line = _pressure_line(
        "Internal design pressure", "Internal design pressure : 3.5 bar"
    )
    assert (
        line["quotes_checked"]["clause_subject"] is False
        and line["reason_code"] == "clause_subject_not_the_field"
    )


def test_a_proven_line_whose_clause_is_changed_to_another_kind_of_the_field_is_refused_at_the_exit_too():
    """The exit asks again from the line's own texts: only the qualifier differs here, every other guard still holds."""
    same = EXTERNAL.replace("(2) ", "")
    line = _pressure_line(
        "External design pressure", "External design pressure : 3.5 bar", clause=same
    )
    assert line["verdict"] in ("Pass", "Fail") and proof.line_proven(line)
    changed = {**line, "clause_quote": same.replace("external", "internal")}
    assert not proof.line_proven(changed)
