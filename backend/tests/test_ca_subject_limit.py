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
        "(5 mm), or the minimum nominal wall thickness shall be 0.154 in.",
        "For carbon steel, the maximum corrosion allowance shall be 3.2 mm.",  # a leading condition holds the limit
        "Where the service is sour, the minimum wall thickness shall be 6 mm.",
        "In case of brush application, the maximum brush size shall be 125 mm.",  # an alternative of two thresholds
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
    assert (
        proof.subject_reason("corrosion_allowance", req, other)
        == proof.SUBJECT_PHRASE_WHY
    )


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
        == proof.SUBJECT_PHRASE_WHY
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
            True,
        ),  # the label does not carry the name whole: an unknown, never a proof
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


# ---- the "c.a." spelling of the corrosion allowance collides with no other field ---------------------------------------------------------------------------


def test_no_other_registered_field_carries_the_two_letter_dotted_abbreviation():
    """ "c.a." was added to the corrosion allowance's spellings. A two-letter dotted abbreviation is the most collision-prone spelling there is, so: no other field
    group lists a spelling of two single letters, and the text "c.a." carries the words of no registry field except the corrosion allowance."""
    from app import agent_review_absence as absence
    from app import agent_review_pass_guards as guards

    two_letters = [
        (group, sp)
        for group, spellings in absence._synonym_groups().items()
        for sp in spellings
        if len(sp.replace(" ", "")) <= 2 and " " in sp
    ]
    assert two_letters == [("corrosion allowance", "c a")]
    carriers = [
        role
        for role, words in guards._all_fields()
        if guards._hit("the maximum c.a. shall be", words)
    ]
    assert carriers == ["corrosion_allowance"]


# ---- R74: the three blockers, the four mediums. Invented sentences; each fails on the head before this change -----------------------------------------------


def _item(field, op, raw, unit, clause, value=None, norm_unit=None, **over):
    return {
        "item_id": "R-r74", "source": "rule", "standard": "STD-1", "clause": "1.1", "rule_kind": "limit", "comparator": op, "value": value if value is not None else float(raw),
        "unit": norm_unit or unit, "raw_value": raw, "raw_unit": unit, "question": clause, "rule_version_id": "v9", "standard_document_id": "std1", "rule_label": {"tier": "AI approved"},
        "field_roles": [field], **over,
    }  # fmt: skip


def _verdict(item, label, raw, unit, clause):
    page = f"{label} : {raw} {unit}\n"
    fact = {
        "id": "f9",
        "field_label": label,
        "raw_value": raw,
        "raw_unit": unit,
        "unit": unit,
        "page": 1,
        "is_blank": False,
        "source_text": f"{label} : {raw} {unit}",
        "equipment_tag": "T1",
    }
    ln = calc.numeric_line(
        item,
        calc.requirement_from_item(item),
        fact,
        submittal_facts=[fact],
        page_text=page,
        clause_quote=clause,
        clause_text=clause,
        page_count=1,
    )
    return _exit(ln, item), ln


@pytest.mark.parametrize(
    "tail",
    [
        "of the support skirt",
        "for nozzles",
        "for piping",
        "per side",
        "of the shell",
        "at the inlet",
    ],
)
def test_b1_a_limit_on_another_component_or_scope_named_after_the_field_is_never_proven(
    tail,
):
    clause = f"The maximum corrosion allowance {tail} shall be 1 mm."
    assert subject_be(clause) is None  # not a number rule: the clause stays a statement
    item = _item(
        "corrosion_allowance", "<=", "1", "mm", clause, value=1000.0, norm_unit="um"
    )
    out, ln = _verdict(
        item, "Corrosion allowance", "5", "mm", clause
    )  # a rule row stored by an older parser, or by hand
    assert out["verdict_class"] != "Proven by code" and out["verdict"] == "Query"


def test_b1_the_subject_between_the_comparator_and_shall_be_must_be_the_fields_name_and_nothing_else():
    clause = "The maximum support skirt corrosion allowance shall be 1 mm."
    item = _item(
        "corrosion_allowance", "<=", "1", "mm", clause, value=1000.0, norm_unit="um"
    )
    assert (
        _verdict(item, "Corrosion allowance", "5", "mm", clause)[0]["verdict_class"]
        != "Proven by code"
    )
    req = calc.requirement_from_item(item)
    assert (
        proof.subject_reason("corrosion_allowance", req, clause)
        == proof.SUBJECT_PHRASE_WHY
    )
    ok = "The maximum corrosion allowance shall be 1 mm."
    assert proof.subject_reason("corrosion_allowance", req, ok) is None
    assert (
        _verdict(item, "Corrosion allowance", "5", "mm", ok)[0]["verdict_class"]
        == "Proven by code"
    )  # control: the plain name still proves


@pytest.mark.parametrize(
    ("clause_words", "label"),
    [
        ("design pressure at the inlet", "Design pressure at the outlet"),
        ("design pressure (external)", "Design pressure (internal)"),
        ("design pressure for the shell", "Design pressure for the tubes"),
        ("design pressure of the jacket", "Design pressure of the shell"),
        ("design pressure, hot,", "Design pressure, cold"),
        ("maximum design pressure", "Minimum design pressure"),
        ("rated design pressure", "Required design pressure"),
        ("nominal design pressure", "Allowable design pressure"),
        (
            "design pressure",
            "Design pressure (internal)",
        ),  # a qualifier on one side only
        ("design pressure (external)", "Design pressure"),
    ],
)
def test_b2_the_qualifier_sets_of_the_clause_and_of_the_label_must_be_equal(
    clause_words, label
):
    clause = f"The {clause_words} shall not exceed 15 psi."
    item = _item(
        "design_pressure", "<=", "15", "psi", clause, value=103421.4, norm_unit="Pa"
    )
    out, _ = _verdict(item, label, "3.5", "bar", clause)
    assert out["verdict_class"] != "Proven by code"


def test_b2_a_minimum_clause_against_a_maximum_label_and_normal_against_maximum_are_not_the_same_quantity():
    clause = "The minimum design temperature shall not be less than 10 C."
    item = _item(
        "design_temperature", ">=", "10", "C", clause, value=10.0, norm_unit="C"
    )
    assert (
        _verdict(item, "Maximum design temperature", "50", "C", clause)[0][
            "verdict_class"
        ]
        != "Proven by code"
    )
    op = "The maximum operating pressure shall not exceed 15 psi."
    item = _item(
        "operating_pressure", "<=", "15", "psi", op, value=103421.4, norm_unit="Pa"
    )
    assert (
        _verdict(item, "Normal operating pressure", "3.5", "bar", op)[0][
            "verdict_class"
        ]
        != "Proven by code"
    )


@pytest.mark.parametrize(
    ("clause_words", "label"),
    [
        ("design pressure", "Design pressure"),
        ("design pressure", "Design pressure :"),
        ("maximum design pressure", "Maximum design pressure"),
        (
            "maximum design pressure",
            "Design pressure",
        ),  # the clause's own comparator word is not a qualifier
    ],
)
def test_b2_control_equal_sets_still_prove(clause_words, label):
    clause = f"The {clause_words} shall not exceed 15 psi."
    item = _item(
        "design_pressure", "<=", "15", "psi", clause, value=103421.4, norm_unit="Pa"
    )
    out, _ = _verdict(item, label, "3.5", "bar", clause)
    assert (
        out["verdict_class"] == "Proven by code" and out["verdict"] == "Fail"
    )  # 3.5 bar is above 15 psi? 3.5 bar = 50.8 psi: a true breach


@pytest.mark.parametrize(
    "sentence",
    [
        "The maximum and minimum corrosion allowance shall be 3.2 mm.",
        "The maximum of the minimum corrosion allowance shall be 3.2 mm.",
        "The minimum or maximum corrosion allowance shall be 3.2 mm.",
    ],
)
def test_b3_two_comparator_words_in_the_subject_do_not_parse(sentence):
    assert subject_be(sentence) is None and r3b.parse_limit(sentence) is None


@pytest.mark.parametrize(
    "clause",
    [
        "For carbon steel, the maximum corrosion allowance shall be 3.2 mm.",
        "Unless the owner agrees otherwise, the maximum corrosion allowance shall be 3.2 mm.",
        "Where the service is sour, the maximum corrosion allowance shall be 3.2 mm.",
        "The maximum corrosion allowance shall be 3.2 mm, except for nozzles.",
        "If the vessel is clad, the maximum corrosion allowance shall be 3.2 mm.",
        "When the service is sour the maximum corrosion allowance shall be 3.2 mm.",
    ],
)
def test_m1_a_condition_in_the_clause_quote_holds_the_line_even_when_the_stored_row_has_none(
    clause,
):
    item = _item(
        "corrosion_allowance", "<=", "3.2", "mm", clause, value=3200.0, norm_unit="um"
    )
    assert "rule_condition" not in item
    out, ln = _verdict(item, "Corrosion allowance", "5", "mm", clause)
    assert out["verdict_class"] != "Proven by code"
    assert (
        proof.condition_reason(calc.requirement_from_item(item), clause)
        == proof.CONDITION_WHY
    )


def test_m1_a_clause_without_a_condition_is_not_held_by_it():
    assert (
        proof.condition_reason(
            {"raw_value": "3.2"}, "The maximum corrosion allowance shall be 3.2 mm."
        )
        is None
    )


def test_m2_a_full_stop_between_two_sentences_does_not_join_a_field_name():
    from app import agent_review_pass_guards as guards

    text = guards._fold("Follow the design. Pressure test shall be 10 bar.")
    assert guards._carries(text, ["design pressure"]) is False
    assert (
        guards._carries(
            guards._fold("The design pressure shall be 10 bar."), ["design pressure"]
        )
        is True
    )


def test_m3_the_dotted_abbreviation_needs_its_dots():
    from app import agent_review_pass_guards as guards

    assert (
        guards._carries(
            guards._fold("The maximum C.A. shall be 3.2 mm."), ["corrosion_allowance"]
        )
        is True
    )
    assert (
        guards._carries(
            guards._fold("Group C A fittings only."), ["corrosion_allowance"]
        )
        is False
    )


def test_m1_the_exit_asks_again_from_the_clause_quote_alone():
    """A line proven on a plain clause whose clause quote is then given a leading condition is not proven at the exit (every other guard still holds)."""
    plain = "The maximum corrosion allowance shall be 3.2 mm."
    item = _item(
        "corrosion_allowance", "<=", "3.2", "mm", plain, value=3200.0, norm_unit="um"
    )
    out, line = _verdict(item, "Corrosion allowance", "3.2", "mm", plain)
    assert out["verdict_class"] == "Proven by code" and proof.line_proven(line)
    assert not proof.line_proven(
        {
            **line,
            "clause_quote": "Unless the owner agrees otherwise, "
            + plain[0].lower()
            + plain[1:],
        }
    )


def test_m1_the_calculator_says_so_in_the_checks_of_the_line():
    clause = "For carbon steel, the maximum corrosion allowance shall be 3.2 mm."
    item = _item(
        "corrosion_allowance", "<=", "3.2", "mm", clause, value=3200.0, norm_unit="um"
    )
    _, line = _verdict(item, "Corrosion allowance", "3.2", "mm", clause)
    assert (
        line["quotes_checked"]["clause_subject"] is False and line["verdict"] == "Query"
    )


@pytest.mark.parametrize("header", ["Internal", "External", "Inlet", "Outlet"])
def test_a_table_header_that_says_internal_external_inlet_or_outlet_is_a_condition_column(
    header,
):
    """The qualifier of a whole column stands in its HEADER, not in the row label: with two such columns the value under one of them is not the rule's (a question)."""
    from app import table_cell
    from tests.test_b1_calculator_proof import _col

    assert table_cell.condition_words(header) == {header.lower()}
    base = {"rule_field": "pressure", "field": "Pressure"}
    assert (
        calc.column_not_the_rules(base, _col(header, conditions=2))
        == f"the table column is {header}; the rule does not say which"
    )
    assert (
        calc.column_not_the_rules(base, _col(header, conditions=1)) is None
    )  # the only value column of the label


# ---- R74b ------------------------------------------------------------------------------------------------------------------------------------------------


LIMIT = "The corrosion allowance shall not exceed 3.2 mm."


def _ca_item(clause):
    return _item(
        "corrosion_allowance", "<=", "3.2", "mm", clause, value=3200.0, norm_unit="um"
    )


@pytest.mark.parametrize(
    "more",
    [
        "Where the service is sour, 6 mm applies.",
        "For stainless steel 1 mm applies.",
        "This does not apply to nozzles.",
        "The owner may agree a higher value.",
        "Higher values are permitted for piping.",
        "The paragraph above is superseded by 7.4.",
        "In sour service the corrosion allowance shall be at least 6 mm.",
        "See note 3.",
        "Note 3: applies to shells only.",
    ],
)
def test_a_the_whole_clause_must_be_the_limit_another_sentence_with_a_condition_an_override_or_a_figure_makes_it_a_query(
    more,
):
    clause = f"{LIMIT} {more}"
    out, _ = _verdict(_ca_item(clause), "Corrosion allowance", "5", "mm", clause)
    assert out["verdict_class"] != "Proven by code" and out["verdict"] == "Query"
    assert (
        proof.single_limit_reason(calc.requirement_from_item(_ca_item(clause)), clause)
        == proof.MORE_WHY
    )
    plain, _ = _verdict(
        _ca_item(LIMIT), "Corrosion allowance", "5", "mm", LIMIT
    )  # control: the single limit sentence proves the breach
    assert (plain["verdict_class"], plain["verdict"]) == ("Proven by code", "Fail")


def test_a_the_stored_clause_text_around_the_quote_is_read_too():
    """The clause continues after the part the reader quoted: the further sentences count (the row's own stored text, the same gated source)."""
    item = _ca_item(LIMIT)
    full = LIMIT + " Where the service is sour, 6 mm applies."
    fact = {
        "id": "f9",
        "field_label": "Corrosion allowance",
        "raw_value": "5",
        "raw_unit": "mm",
        "unit": "mm",
        "page": 1,
        "is_blank": False,
        "source_text": "Corrosion allowance : 5 mm",
        "equipment_tag": "T1",
    }
    ln = calc.numeric_line(
        item,
        calc.requirement_from_item(item),
        fact,
        submittal_facts=[fact],
        page_text="Corrosion allowance : 5 mm\n",
        clause_quote=LIMIT,
        clause_text=full,
        page_count=1,
    )
    assert (
        ln["verdict"] == "Query"
        and _exit(ln, item)["verdict_class"] != "Proven by code"
    )
    good = calc.numeric_line(
        item,
        calc.requirement_from_item(item),
        fact,
        submittal_facts=[fact],
        page_text="Corrosion allowance : 5 mm\n",
        clause_quote=LIMIT,
        clause_text=LIMIT,
        page_count=1,
    )
    assert proof.line_proven(good) and not proof.line_proven(
        {**good, "clause_text": full}
    )  # the exit asks again from the clause text the line carries


def test_a_a_heading_line_and_a_clause_number_are_not_more_than_the_limit():
    clause = "7.1.2 Corrosion allowance\n7.1.2.3 " + LIMIT
    out, _ = _verdict(_ca_item(clause), "Corrosion allowance", "5", "mm", clause)
    assert out["verdict_class"] == "Proven by code"


COND_LABEL = "Corrosion allowance unless otherwise agreed"
COND_CLAUSE = "The corrosion allowance shall not exceed 3.2 mm unless otherwise agreed."


def test_m1_the_calculator_holds_a_condition_of_the_limit_sentence_when_nothing_else_does():
    """The label carries the same extra words, so the qualifier sets are equal and the clause is no more than one sentence: only the condition read is left."""
    _, ln = _verdict(_ca_item(COND_CLAUSE), COND_LABEL, "5", "mm", COND_CLAUSE)
    assert (
        proof.qualifier_reason(
            "corrosion_allowance",
            calc.requirement_from_item(_ca_item(COND_CLAUSE)),
            COND_CLAUSE,
            COND_LABEL,
        )
        is None
    )
    assert ln["verdict"] == "Query" and ln["quotes_checked"]["clause_subject"] is False


def test_m1_the_exit_asks_again_for_the_condition_when_nothing_else_does(monkeypatch):
    item = _ca_item(COND_CLAUSE)
    with monkeypatch.context() as m:
        m.setattr(
            proof, "condition_reason", lambda *a, **k: None
        )  # a calculator that did not see the condition
        _, ln = _verdict(item, COND_LABEL, "5", "mm", COND_CLAUSE)
        assert ln["verdict"] == "Fail"
    assert not proof.line_proven(ln)


def test_each_any_and_all_are_quantity_words_not_joins():
    req = calc.requirement_from_item(_ca_item(LIMIT))
    for label in (
        "Each corrosion allowance",
        "Any corrosion allowance",
        "All corrosion allowance",
    ):
        assert (
            proof.qualifier_reason("corrosion_allowance", req, LIMIT, label)
            == proof.QUALIFIER_WHY
        )
    assert (
        proof.qualifier_reason("corrosion_allowance", req, LIMIT, "Corrosion allowance")
        is None
    )


def test_a_name_that_only_a_role_pattern_carries_is_still_found():
    import re

    from app import agent_review_absence as absence
    from app import agent_review_proof_words as pw

    words = absence.FieldWords(
        role="x",
        canonical=None,
        patterns=(re.compile("zz widget(?:s)?"),),
        spellings=("zz gadget",),
        source="t",
    )
    got = pw.qualifier_sets("the zz widgets shall not exceed", words, "zz gadget")
    assert got == (set(), set())  # found by the pattern, nothing else qualifies


def test_the_five_nominal_plate_thickness_rows_prove_only_against_that_exact_label():
    clause = "(2) The minimum nominal plate thickness shall be 0.249 in."
    item = _item(
        "nominal_plate_thickness",
        ">=",
        "0.249",
        "in",
        clause,
        value=6324.6,
        norm_unit="um",
    )
    assert (
        subject_be(clause) is not None
    )  # the row parses: the sentence names no component
    ok = _verdict(item, "Nominal plate thickness", "0.3", "in", clause)[0]
    assert (ok["verdict_class"], ok["verdict"]) == ("Proven by code", "Pass")
    for label in (
        "Plate thickness",
        "Nominal plate thickness (shell)",
        "Nominal plate thickness for heads",
        "Maximum nominal plate thickness",
    ):
        assert (
            _verdict(item, label, "0.3", "in", clause)[0]["verdict_class"]
            != "Proven by code"
        ), label


# ---- the end of a clause: the stored text of a clause may run on into the following clauses ------------------------------------------------------------------


def _own(text, clause="7.1.2.3"):
    from app.agent_review_proof_words import clause_own_text

    return clause_own_text(text, clause)


LIM_LINE = "7.1.2.3 The corrosion allowance shall not exceed 3.2 mm."


def test_the_clause_text_ends_at_the_next_clause_number_at_the_start_of_a_line():
    for nxt in ("7.1.2.4", "7.1.3", "7.2", "8"):
        if (
            nxt == "8"
        ):  # a one-component number is a section number: it ends the clause only when written as a heading line of its own words
            continue
        text = f"{LIM_LINE}\n{nxt} Where the service is sour, 6 mm applies.\n"
        assert _own(text) == LIM_LINE + "\n", nxt


@pytest.mark.parametrize(
    "inside",
    [
        "7.1.2.3.1 For stainless steel 1 mm applies.",  # a sub-clause is part of the clause
        "1. Where the service is sour, 6 mm applies.",  # a list item: earlier in order, one component
        "2. Where the service is sour, 6 mm applies.",
        "(a) Where the service is sour, 6 mm applies.",
        "See 7.1.2.4 where the service is sour.",  # a cross-reference in a sentence
        "7.5 mm applies for piping.",  # a line that starts with a figure and a unit
        "7.5 12 mm applies for piping.",  # a table row that starts with a number and a figure
        "7.1.1 Where the service is sour, 6 mm applies.",  # an EARLIER clause number
    ],
)
def test_what_is_not_a_clause_boundary_stays_inside_the_clause_text(inside):
    text = f"{LIM_LINE}\n{inside}\n"
    assert _own(text) == text


def test_when_no_end_can_be_established_the_whole_text_is_read_today_s_behaviour():
    text = LIM_LINE + "\nWhere the service is sour, 6 mm applies.\n"
    assert _own(text) == text
    assert (
        _own(text, "Appendix A") == text and _own(text, None) == text
    )  # not a plain clause number: nothing is cut


def test_a_clause_that_continues_into_the_next_clause_proves_on_its_own_text_and_not_on_the_next_clauses():
    nxt = "7.1.2.4 Where the service is sour, 6 mm applies."
    item = _ca_item(LIM_LINE)
    fact = {
        "id": "f9",
        "field_label": "Corrosion allowance",
        "raw_value": "5",
        "raw_unit": "mm",
        "unit": "mm",
        "page": 1,
        "is_blank": False,
        "source_text": "Corrosion allowance : 5 mm",
        "equipment_tag": "T1",
    }

    def build(text):
        return calc.numeric_line(
            {**item, "clause": "7.1.2.3"},
            calc.requirement_from_item(item),
            fact,
            submittal_facts=[fact],
            page_text="Corrosion allowance : 5 mm\n",
            clause_quote=LIM_LINE,
            clause_text=text,
            page_count=1,
        )

    cut = build(f"{LIM_LINE}\n{nxt}\n")
    assert cut["verdict"] == "Fail" and proof.line_proven(
        cut
    )  # the next clause is not this clause
    inside = build(f"{LIM_LINE}\nWhere the service is sour, 6 mm applies.\n{nxt}\n")
    assert inside["verdict"] == "Query" and not proof.line_proven(
        {
            **cut,
            "clause_text": f"{LIM_LINE}\nWhere the service is sour, 6 mm applies.\n{nxt}\n",
        }
    )
