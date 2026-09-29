"""Review conditions: the DATASHEET'S OWN FACTS decide whether a conditional
requirement applies.

A requirement that binds only "pipes larger than 2 inch", "Class 600 and
above", "sour service", "carbon steel" or "above 60 °C" is compared only when
the datasheet shows it is inside that condition. Clearly outside ->
NOT_APPLICABLE, quoting the condition and the datasheet value with its page.
Unknown, untrusted or unreadable -> an engineer's question, never a guess.

All data here is synthetic. Every test names the behaviour it pins; the
mutations in `scripts/mutations/review_conditions.py` (M1560-M1579) delete
each behaviour and prove the matching test fails.
"""

from __future__ import annotations

import pytest

from app import comparison, conditions, crs_mapping

DECIDED = {comparison.COMPLIANT, comparison.NON_COMPLIANT}


def req(condition, **over) -> dict:
    base = {
        "id": "req-rc", "requirement_type": "numeric_limit", "clause": "4.2",
        "page": 7, "subject": "wall thickness", "operator": ">=",
        "raw_value": "5", "raw_unit": "mm",
        "requirement_text": f"Minimum wall thickness shall be 5 mm {condition}.",
        "source_text": f"Minimum wall thickness shall be 5 mm {condition}.",
        "condition": condition, "exceptions": None,
    }
    base.update(over)
    return base


def wall(value="4", **over) -> dict:
    """The fact under test: a LENGTH. It must never establish a size."""
    base = {"id": "f-wall", "field_name": "wall thickness",
            "field_value": f"{value} mm", "raw_value": value, "raw_unit": "mm",
            "page": 3, "is_blank": False, "blank_marker": None}
    base.update(over)
    return base


def fact(name, value, fid=None, page=2, **over) -> dict:
    base = {"id": fid or f"f-{name}", "field_name": name, "field_value": value,
            "raw_value": None, "raw_unit": None, "page": page,
            "is_blank": False, "blank_marker": None}
    base.update(over)
    return base


def run(condition, facts, about=None):
    about = about or wall()
    return comparison.compare(req(condition), about, submittal_facts=[about, *facts])


# ------------------------------------------------------------------ size

SIZE = "for pipes larger than 2 inch"


def test_size_inside_the_condition_is_compared_as_today():
    out = run(SIZE, [fact("nominal size", '6"')])
    assert out["condition"]["state"] == conditions.SATISFIED
    assert out["status"] == comparison.NON_COMPLIANT, "4 mm < 5 mm and the clause applies"


@pytest.mark.parametrize("name,value", [("NPS", "1"), ("line size", "DN 25"),
                                        ("nominal size", '2"')])
def test_size_outside_the_condition_is_not_applicable_quoting_both(name, value):
    out = run(SIZE, [fact(name, value, page=9)])
    assert out["status"] == comparison.NOT_APPLICABLE
    assert out["status"] not in DECIDED
    why = out["rationale"]
    assert why.startswith(comparison.CONDITION_NOT_MET)
    assert "larger than 2 inch" in why, "the condition text must be quoted"
    assert repr(value) in why and "page 9" in why, "the datasheet value and page must be quoted"
    assert out["condition"]["evidence"]["field_name"] == name


def test_size_unknown_when_no_field_states_a_nominal_size():
    out = run(SIZE, [fact("service", "sour gas")])
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_a_wall_thickness_is_never_a_nominal_size():
    """By ROLE: a length labelled with a size word is still a length."""
    out = run(SIZE, [fact("line size wall thickness", '1"'),
                     fact("wall thickness", "12 mm")])
    assert out["condition"]["state"] == conditions.UNKNOWN
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW


def test_a_size_read_twice_differently_is_not_a_reading():
    """A reducer "6 x 4 inch" is two sizes; neither is picked."""
    out = run(SIZE, [fact("nominal size", '6" x 1"')])
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_the_size_of_another_nozzle_does_not_decide():
    """N1's size says nothing about N3's rating."""
    about = fact("N3 rating", "CL150", fid="f-n3r", raw_value="150", raw_unit=None)
    facts = [fact("N1 size", '1"', fid="f-n1"), fact("N3 size", '6"', fid="f-n3")]
    got = conditions.evaluate(req(SIZE), [about, *facts], about=about)
    assert got["state"] == conditions.SATISFIED
    assert got["evidence"]["submittal_facts_row_id"] == "f-n3"


def test_the_review_scopes_the_condition_to_the_compared_items_tag():
    """Through `compare`: the P-101A value is judged on P-101A's size."""
    about = wall(equipment_tag="P-101A")
    facts = [fact("NPS", "1", fid="f-b", equipment_tag="P-101B"),
             fact("NPS", "6", fid="f-a", equipment_tag="P-101A")]
    out = comparison.compare(req(SIZE), about, submittal_facts=[about, *facts])
    assert out["condition"]["state"] == conditions.SATISFIED
    assert out["status"] == comparison.NON_COMPLIANT


# ----------------------------------------------------------------- class

CLASS = "for Class 600 and above"


def test_class_inside_and_outside():
    assert run(CLASS, [fact("flange rating", "900#")])["condition"]["state"] \
        == conditions.SATISFIED
    out = run(CLASS, [fact("flange rating", "CL150")])
    assert out["status"] == comparison.NOT_APPLICABLE
    assert "Class 600 and above" in out["rationale"] and "'CL150'" in out["rationale"]


def test_class_against_a_pn_rating_is_not_decided():
    out = run(CLASS, [fact("flange rating", "PN 16")])
    assert out["condition"]["state"] == conditions.UNKNOWN


# --------------------------------------------------------------- service

SOUR = "in sour service"


def test_service_inside_outside_and_unknown():
    assert run(SOUR, [fact("service", "sour gas")])["condition"]["state"] \
        == conditions.SATISFIED
    out = run(SOUR, [fact("sour service", "No")])
    assert out["status"] == comparison.NOT_APPLICABLE
    assert out["condition"]["evidence"]["field_value"] == "No"
    assert run(SOUR, [fact("service", "non-sour gas")])["status"] \
        == comparison.NOT_APPLICABLE


def test_a_service_outside_the_vocabulary_is_not_proof_of_not_sour():
    """"Crude oil" may be sour. Only a stated no excuses the clause."""
    out = run(SOUR, [fact("service", "crude oil")])
    assert out["condition"]["state"] == conditions.UNKNOWN
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW


# -------------------------------------------------------------- material

CS = "for carbon steel"


def test_material_inside_and_outside():
    assert run(CS, [fact("shell material", "SA-516 Gr 70 carbon steel")]
               )["condition"]["state"] == conditions.SATISFIED
    out = run(CS, [fact("shell material", "316L stainless steel")])
    assert out["status"] == comparison.NOT_APPLICABLE


def test_an_unrecognised_material_grade_is_unknown_not_outside():
    """"A106 Gr B" IS carbon steel. A grade the reader does not know is never
    read as "not carbon steel"."""
    out = run(CS, [fact("pipe material", "ASTM A106 Gr B")])
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_a_duplex_is_a_stainless_steel():
    got = conditions.evaluate(req("for stainless steel"),
                              [fact("body material", "super duplex")])
    assert got["state"] == conditions.SATISFIED


def test_unread_alternatives_may_satisfy_but_never_excuse():
    cond = "For carbon steel, low-alloy steel and alloy steel systems"
    assert conditions.evaluate(req(cond), [fact("shell material", "carbon steel")]
                               )["state"] == conditions.SATISFIED
    got = conditions.evaluate(req(cond), [fact("shell material", "316L stainless steel")])
    assert got["state"] == conditions.UNKNOWN, (
        "stainless IS an alloy steel - outside the two options read is not "
        "outside the condition")


# ----------------------------------------------------------- temperature

HOT = "above 60 °C"


def test_temperature_inside_outside_and_straddling():
    assert run(HOT, [fact("design temperature", "95 °C")])["condition"]["state"] \
        == conditions.SATISFIED
    out = run(HOT, [fact("design temperature", "45", raw_value="45", raw_unit="degC")])
    assert out["status"] == comparison.NOT_APPLICABLE
    assert "above 60 °C" in out["rationale"]
    straddle = run(HOT, [fact("design temperature", "-29 to 95 °C")])
    assert straddle["condition"]["state"] == conditions.UNKNOWN
    # "-29 / 95 °C": only "95 °C" carries a unit, and a reading that leaves a
    # stated number unaccounted for is not a reading.
    partial = run(HOT, [fact("design temperature", "-29 / 95 °C")])
    assert partial["condition"]["state"] == conditions.UNKNOWN


def test_temperature_is_read_from_the_design_field_by_role():
    """An operating temperature does not establish a design-temperature
    condition, and a temperature without a unit is not read."""
    assert run(HOT, [fact("operating temperature", "45 °C")])["condition"]["state"] \
        == conditions.UNKNOWN
    assert run(HOT, [fact("design temperature", "45")])["condition"]["state"] \
        == conditions.UNKNOWN
    assert run("at operating temperature above 60 °C",
               [fact("operating temperature", "45 °C")])["status"] \
        == comparison.NOT_APPLICABLE


def test_pressure_condition():
    out = run("design pressure above 10 barg", [fact("design pressure", "5 barg")])
    assert out["status"] == comparison.NOT_APPLICABLE


# ------------------------------------------------- unreadable conditions

@pytest.mark.parametrize("cond", [
    "for pipes larger than 2 inch in hydrocarbon service",   # part not read
    "for pipes larger than 2 inch unless galvanised",         # an exception
    "for pipes larger than 2 inch or in sour service",       # 'or' across kinds
    "for pipes larger than 2 inch and smaller than 24 inch",  # two bounds
])
def test_a_condition_read_only_in_part_goes_to_an_engineer(cond):
    """Every fact here is clearly OUTSIDE the part that was read - and still
    nothing is excused, because the part not read could change the answer."""
    out = run(cond, [fact("NPS", "1"), fact("service", "sour gas")])
    assert out["condition"]["state"] == conditions.UNKNOWN, out["condition"]["reason"]
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW


def test_a_condition_the_reader_reads_nothing_in_keeps_the_v1_gate():
    out = run("for critical service", [fact("service", "sour gas")])
    assert out["condition"]["state"] == conditions.UNKNOWN
    assert out["condition"]["shape"] == conditions.SHAPE_UNRECOGNISED


# ------------------------------------------------------- low-trust values

@pytest.mark.parametrize("trust", [{"validation_state": "needs_engineer_review"},
                                   {"validation_state": "conflict"},
                                   {"extraction_method": "model"}])
def test_a_low_trust_value_cannot_excuse_a_requirement(trust):
    out = run(SIZE, [fact("NPS", "1", **trust)])
    assert out["condition"]["state"] == conditions.UNKNOWN
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "not yet trusted" in out["condition"]["reason"]


def test_an_engineer_confirmed_value_is_trusted():
    out = run(SIZE, [fact("NPS", "1", extraction_method="model", confirmed_by="u-1")])
    assert out["status"] == comparison.NOT_APPLICABLE


def test_an_untrusted_reading_that_would_change_the_answer_blocks_it():
    out = run(SIZE, [fact("NPS", "1", fid="a"),
                     fact("line size", '6"', fid="b", validation_state="conflict")])
    assert out["condition"]["state"] == conditions.UNKNOWN


def test_a_low_trust_material_does_not_decide_the_v1_gate_either():
    got = conditions.evaluate(req("titanium"),
                              [fact("shell material", "carbon steel",
                                    validation_state="needs_engineer_review")])
    assert got["state"] == conditions.UNKNOWN


# ------------------------------------------------ table_value row labels

@pytest.mark.parametrize("label", ["larger than 2 inch", "Class 600", "above 60 °C",
                                   "sour service", "carbon steel", "100"])
def test_table_value_row_labels_are_never_conditions(label):
    row = req(label, requirement_type="table_value")
    assert conditions.evaluate(row, [fact("NPS", "1")]) is None
    with_label = comparison.compare(row, wall(), submittal_facts=[fact("NPS", "1")])
    without = comparison.compare(req(None, requirement_type="table_value"), wall(),
                                 submittal_facts=[fact("NPS", "1")])
    assert with_label == without


# ------------------------------------------------------------------ CRS

def _finding(verdict, fid="fd-1") -> dict:
    return {"id": fid, "compliance_status": verdict["status"],
            "ai_rationale": verdict["rationale"], "fact_id": "f-wall",
            "contractor_page": 3, "contractor_evidence_text": "4 mm",
            "standard_name": "XYZ-STD-001.pdf", "standard_clause": "4.2",
            "standard_page": 7, "matched_phrase": "wall thickness",
            "requirement_source_text": req(SIZE)["source_text"]}


def test_the_crs_lists_not_applicable_with_condition_and_value_not_as_a_breach():
    verdict = run(SIZE, [fact("NPS", "1", page=9)])
    assert verdict["status"] == comparison.NOT_APPLICABLE
    finding = _finding(verdict)

    rows = crs_mapping.build_crs_rows([finding], [], "DS-001")
    assert rows == [], "an excused requirement is not a contractor comment"

    [note] = [n for n in crs_mapping.build_review_notes([finding], [])
              if n["note"] == crs_mapping.NOTE_CONDITION_NOT_MET]
    assert note["standard"] == "XYZ-STD-001 cl. 4.2 (p.7)"
    assert "larger than 2 inch" in note["detail"]
    assert "'1'" in note["detail"] and "page 9" in note["detail"]
    assert "condition_not_met" not in note["detail"], "no machine code on the sheet"


def test_the_crs_note_is_only_for_condition_not_met():
    """A NOT_APPLICABLE without the condition marker, or any other status,
    gets no such note - the note never re-decides a verdict."""
    other = _finding({"status": "NOT_APPLICABLE", "rationale": "some other reason"})
    breach = _finding({"status": "NON_COMPLIANT",
                       "rationale": "condition_not_met: planted"}, fid="fd-2")
    notes = crs_mapping.build_review_notes([other, breach], [])
    assert not [n for n in notes if n["note"] == crs_mapping.NOTE_CONDITION_NOT_MET]
