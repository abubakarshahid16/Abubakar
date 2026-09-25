"""B24 — a conditional requirement may not reach a verdict on an unevaluated condition.

The defect: SAES-A-133 7.1.2.1 requires a minimum corrosion allowance of 1.6 mm
"For carbon steel, low-alloy steel and alloy steel systems". P-1000001 submits 0 mm
and every one of its material fields reads "N/A". The engine did the arithmetic and
returned NON_COMPLIANT — a verdict on a clause nobody had shown applies.

These tests are numbered to the execution order. Test 8 is the mutation, run by
`scripts/mutation_check.py`; its verbatim output is in the report and in
CURRENT_STATE section 15.

Nothing here claims engineering accuracy. It asserts that the engine declines to
judge a requirement whose condition is not established.
"""

from __future__ import annotations

import pytest

from app import comparison, conditions

CLAUSE = ('For carbon steel, low-alloy steel and alloy steel systems, a minimum '
          'C.A. of at least 1.6 mm (1/16") shall be used.')

DECIDED = {comparison.COMPLIANT, comparison.NON_COMPLIANT}


def req(**over) -> dict:
    base = {
        "id": "req-b24",
        "requirement_type": "numeric_limit",
        "clause": "7.1.2.1",
        "page": 48,
        "subject": "minimum C.A",
        "operator": ">=",
        "raw_value": "1.6",
        "raw_unit": "mm",
        "requirement_text": CLAUSE,
        "source_text": CLAUSE,
        "condition": "carbon steel",
        "exceptions": None,
    }
    base.update(over)
    return base


def fact(**over) -> dict:
    base = {
        "id": "fact-b24",
        "field_name": "design corrosion allowance for welded internal parts",
        "field_value": "0 mm",
        "raw_value": "0",
        "raw_unit": "mm",
        "page": 4,
        "is_blank": False,
        "blank_marker": None,
    }
    base.update(over)
    return base


def material(value, **over) -> dict:
    base = {"id": "fact-mat", "field_name": "shell material",
            "field_value": value, "raw_value": None, "raw_unit": None,
            "page": 5, "is_blank": False, "blank_marker": None}
    base.update(over)
    return base


# ------------------------------------------------------- 1. missing material

def test_1_a_missing_material_condition_cannot_produce_non_compliant():
    """The exact Phase 0.5 case. 0 mm against >= 1.6 mm, material unknown."""
    out = comparison.compare(req(), fact(),
                             submittal_facts=[material("N/A")])
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert out["status"] not in DECIDED
    assert "carbon steel" in out["rationale"]
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_1b_omitting_the_facts_entirely_also_abstains():
    """The unsafe default must not exist. A caller that passes nothing gets no
    verdict, rather than the gate silently not running."""
    out = comparison.compare(req(), fact())
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_1c_a_material_field_that_does_state_carbon_steel_lets_it_proceed():
    """The control. Without this, every test here could pass by abstaining
    always — the vacuous-test failure mode this project has shipped before."""
    out = comparison.compare(
        req(), fact(), submittal_facts=[material("SA-516 Gr 70 carbon steel")])
    assert out["status"] == comparison.NON_COMPLIANT, (
        "with the material established as carbon steel the clause applies and "
        "0 mm really is below 1.6 mm")
    assert out["condition"]["state"] == conditions.SATISFIED
    assert out["condition"]["evidence"]["submittal_facts_row_id"] == "fact-mat"


# -------------------------------------------------------- 2. missing service

def test_2_a_missing_service_condition_cannot_produce_compliant():
    """A value that WOULD pass must not pass while the service is unknown."""
    out = comparison.compare(
        req(condition="sour service", operator="<=", raw_value="10",
            raw_unit="mm"),
        fact(raw_value="3", field_value="3 mm"),
        submittal_facts=[fact()])          # no service field at all
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert out["status"] != comparison.COMPLIANT
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_2b_a_stated_service_lets_a_passing_value_pass():
    out = comparison.compare(
        req(condition="sour service", operator="<=", raw_value="10",
            raw_unit="mm"),
        fact(raw_value="3", field_value="3 mm"),
        submittal_facts=[{"id": "f-svc", "field_name": "service",
                          "field_value": "sour service gas", "page": 3,
                          "is_blank": False}])
    assert out["status"] == comparison.COMPLIANT


# ------------------------------------------------- 3. missing equipment class

@pytest.mark.parametrize("condition", [
    "low voltage cables",
    "relief valves with inlet size less than 1-inch",
    "Type K thermocouples",
])
def test_3_a_missing_equipment_class_condition_cannot_produce_a_verdict(condition):
    out = comparison.compare(req(condition=condition), fact(),
                             submittal_facts=[fact()])
    assert out["status"] not in DECIDED, (
        f"{condition!r} produced {out['status']}")


# ----------------------------------------- 4. table_value must NOT be gated

def test_4_a_table_value_row_with_condition_arsenic_does_not_trigger_the_gate():
    """`condition` on a `table_value` row is the TABLE'S ROW LABEL, not a
    condition. 4,246 rows carry one and 1,601 of those are bare numbers.

    Gating them would abstain on 4,246 rows because a table row is called
    "Arsenic" — B20's defect in mirror image.
    """
    gated = comparison.compare(req(requirement_type="table_value",
                                   condition="Arsenic"), fact())
    assert "condition" not in gated, "the gate must not have run at all"
    assert gated["status"] in DECIDED


@pytest.mark.parametrize("label", ["Arsenic", "100", "50", "BOD5",
                                   "Chromium (Hexavalent)", "Aluminum"])
def test_4b_table_value_behaviour_is_identical_to_having_no_condition(label):
    """Byte-identical: the gate is not merely tolerant of these rows, it is
    absent for them."""
    with_label = comparison.compare(
        req(requirement_type="table_value", condition=label), fact())
    without = comparison.compare(
        req(requirement_type="table_value", condition=None), fact())
    assert with_label == without


def test_4c_the_gate_is_scoped_by_type_at_the_evaluator_too():
    for rtype in ("table_value", "statement", "table_row", "relative_limit",
                  "applicability_trigger"):
        assert conditions.evaluate(req(requirement_type=rtype,
                                       condition="carbon steel"), []) is None, (
            f"{rtype} must be out of scope for the condition evaluator")
    assert conditions.evaluate(req(requirement_type="numeric_limit",
                                   condition="carbon steel"), []) is not None


# ------------------------------------- 5 and 6. mismatch, with and without proof

def test_5_a_mismatch_with_a_proving_fact_is_not_applicable():
    """The material IS established, and it is not what the clause binds."""
    out = comparison.compare(
        req(), fact(), submittal_facts=[material("316L stainless steel")])
    assert out["status"] == comparison.NOT_APPLICABLE
    assert out["condition"]["state"] == conditions.NOT_SATISFIED
    assert out["condition"]["evidence"] is not None, (
        "NOT_APPLICABLE must carry the fact that proves it")
    assert out["condition"]["evidence"]["field_value"] == "316L stainless steel"


def test_6_a_mismatch_without_a_proving_fact_is_needs_engineer_review():
    """No material field at all. Nothing proves the clause does not apply, so it
    may still apply — UNKNOWN never becomes NOT_APPLICABLE."""
    out = comparison.compare(req(), fact(), submittal_facts=[fact()])
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert out["status"] != comparison.NOT_APPLICABLE
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_6b_a_placeholder_material_is_absent_evidence_not_a_mismatch():
    """"N/A" does not establish that the material is not carbon steel."""
    for placeholder in ("N/A", "NA", "not applicable", "----", "BY VENDOR",
                        "TBD", "hold", ""):
        out = comparison.compare(req(), fact(),
                                 submittal_facts=[material(placeholder)])
        assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW, (
            f"{placeholder!r} produced {out['status']}")
        assert out["condition"]["state"] == conditions.UNKNOWN


# ----------------------------------------- 7. unconditional is untouched

@pytest.mark.parametrize("value,expected", [
    ("0", comparison.NON_COMPLIANT),
    ("3", comparison.COMPLIANT),
])
def test_7_requirements_with_no_condition_behave_exactly_as_before(value, expected):
    for cond in (None, "", "   "):
        out = comparison.compare(req(condition=cond),
                                 fact(raw_value=value,
                                      field_value=f"{value} mm"))
        assert out["status"] == expected
        assert "condition" not in out, (
            "an unconditional requirement must carry no condition record")


def test_7b_missing_information_is_not_weakened_by_the_gate():
    """The gate sits AFTER the MISSING_INFORMATION branches. A conditional
    requirement with no value is still "the submittal does not say", which is a
    truer statement than "the condition is unestablished"."""
    assert comparison.compare(req(), None,
                              submittal_facts=[material("N/A")]
                              )["status"] == comparison.MISSING_INFORMATION
    blank = fact(raw_value=None, is_blank=True, blank_marker="BY VENDOR")
    assert comparison.compare(req(), blank, submittal_facts=[material("N/A")]
                              )["status"] == comparison.MISSING_INFORMATION


# -------------------------- 11. existing comparisons, including B20's cases

def test_11_the_abd391b_dimension_cases_still_hold_through_the_gate():
    """B20 must keep working with B24 in the path, for conditional and
    unconditional requirements alike."""
    out = comparison.compare(req(condition=None),
                             fact(raw_value="60", raw_unit="degC",
                                  field_value="60 degC"))
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "cannot be compared" in out["rationale"]

    out = comparison.compare(
        req(), fact(raw_value="60", raw_unit="degC", field_value="60 degC"),
        submittal_facts=[material("SA-516 Gr 70 carbon steel")])
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW

    converted = comparison.compare(req(condition=None),
                                   fact(raw_value="0.003", raw_unit="m",
                                        field_value="0.003 m"))
    assert converted["status"] == comparison.COMPLIANT


# ------------------- 12. CRS / disposition unchanged for unconditional rows

def test_12_required_action_and_status_set_are_unchanged():
    """The gate adds no status and changes no action string. Every status it can
    return already existed and already had one."""
    for status in (comparison.COMPLIANT, comparison.NON_COMPLIANT,
                   comparison.MISSING_INFORMATION, comparison.NOT_APPLICABLE,
                   comparison.NEEDS_ENGINEER_REVIEW):
        assert comparison._required_action(status) is not None


def test_12b_the_gate_returns_only_statuses_that_already_existed():
    produced = set()
    for facts in ([material("N/A")], [material("316L stainless steel")],
                  [material("SA-516 Gr 70 carbon steel")], [], None):
        produced.add(comparison.compare(req(), fact(),
                                        submittal_facts=facts)["status"])
    assert produced <= {comparison.NEEDS_ENGINEER_REVIEW,
                        comparison.NOT_APPLICABLE, comparison.NON_COMPLIANT}


def test_12c_the_dead_conditional_status_is_still_never_produced():
    """CONDITIONAL is declared, labelled in the UI, counted in a tally, and
    assigned by nothing. B24 did not wire it, because no state in B24's approved
    outcome table is "a verdict that holds only if something else is true" —
    established/not-established/unknown are the three, and none of them is that.

    Asserted rather than left implicit, so the claim in the report is enforced and
    a future change that starts producing it has to come past this test.
    """
    produced = set()
    for cond in (None, "carbon steel", "sour service", "low voltage cables",
                 "greater than 50 mm"):
        for facts in ([material("N/A")], [material("316L stainless steel")],
                      [material("SA-516 Gr 70 carbon steel")], [], None):
            produced.add(comparison.compare(req(condition=cond), fact(),
                                            submittal_facts=facts)["status"])
    assert comparison.CONDITIONAL not in produced


# ======================================================================= B49
#
# The gate answered NOT_APPLICABLE on a real datasheet - it EXCUSED the clause
# using the very fields the clause was being tested against. `_candidate_facts`
# selected on the substring "material" in a field NAME, and two corrosion
# allowances carried that substring while holding a length. Two stated values
# that were not "carbon steel" met the only route to NOT_SATISFIED.
#
# The structure is reproduced below synthetically. No value, label or
# identifier from any client document appears here: what matters is the SHAPE -
# material-named fields that state nothing, beside length-valued fields whose
# labels also contain the word.


def _named_material_fields(value="N/A") -> list[dict]:
    """Six fields that genuinely state a material, none of which states one."""
    return [material(value, id=f"fact-mat-{n}", field_name=name)
            for n, name in enumerate((
                "lining material", "gasket material", "fastener material",
                "nozzle forging material", "support material",
                "internals material"))]


def _length_valued_but_material_named() -> list[dict]:
    """Fields under test, not evidence: a length whose label says "material"."""
    return [fact(id=f"fact-len-{n}", field_name=name, field_value="0 mm",
                 raw_value="0", raw_unit="mm")
            for n, name in enumerate((
                "design thickness margin for liner material B",
                "design thickness margin for cover material B"))]


def test_b49_a_length_cannot_establish_a_material_however_it_is_labelled():
    """THE DEFECT. Six material fields state nothing; two length fields carry
    the word "material" in their labels. The material is NOT established, so
    the only honest answer is UNKNOWN - and the requirement stays open."""
    facts = _named_material_fields() + _length_valued_but_material_named()

    out = comparison.compare(req(), fact(), submittal_facts=facts)

    assert out["condition"]["state"] == conditions.UNKNOWN, (
        "a corrosion-allowance length was accepted as proof of a material: "
        f"{out['condition']['reason']}")
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW, (
        "the clause was excused on evidence that says nothing about material")


def test_b49_excusing_a_requirement_needs_a_material_that_is_actually_stated():
    """The control in the direction that matters. A real material outside the
    clause's scope still excuses it - the fix makes NOT_APPLICABLE harder to
    reach, not unreachable."""
    facts = _named_material_fields("316L stainless steel") \
        + _length_valued_but_material_named()

    out = comparison.compare(req(), fact(), submittal_facts=facts)

    assert out["condition"]["state"] == conditions.NOT_SATISFIED
    assert out["status"] == comparison.NOT_APPLICABLE
    assert out["condition"]["evidence"]["field_value"] == "316L stainless steel", (
        "the decision must cite the material that proves it, never a length")


def test_b49_a_stated_carbon_steel_still_lets_the_comparison_proceed():
    """The anti-vacuity control: the fix must not turn every case into UNKNOWN.
    With carbon steel stated, the clause binds and 0 mm is still below 1.6 mm,
    even with the length-valued impostors present."""
    facts = _named_material_fields("SA-516 Gr 70 carbon steel") \
        + _length_valued_but_material_named()

    out = comparison.compare(req(), fact(), submittal_facts=facts)

    assert out["condition"]["state"] == conditions.SATISFIED
    assert out["status"] == comparison.NON_COMPLIANT


def test_b49_the_role_test_reads_the_unit_even_when_only_the_value_carries_it():
    """Extraction populates the unit columns unevenly. A fact whose unit lives
    only inside its value ("0 mm", no raw_unit) must be recognised as a
    measurement too, or the defect returns for every unparsed row."""
    inline = fact(id="fact-inline", field_name="thickness margin material C",
                  field_value="0 mm", raw_value=None, raw_unit=None)

    out = comparison.compare(req(), fact(),
                             submittal_facts=[*_named_material_fields(), inline])

    assert out["condition"]["state"] == conditions.UNKNOWN
