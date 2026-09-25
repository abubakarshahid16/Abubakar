"""Applicability v2 decision rule (owner order 2026-09-25, 4.5). Synthetic
lexicon and scope records - no client documents."""
import pytest

from app.applicability_v2 import (APPLICABLE, APPLICABLE_CANDIDATE, NOT_APPLICABLE, UNKNOWN,
                                  Profile, decide, nodes_for)

LEX = {
    "centrifugal pump": ("type", "Centrifugal Pump"),
    "pump": ("family", "Pumps"),
    "pressure vessel": ("family", "Pressure vessels"),
    "vessel": ("family", "Pressure vessels"),
    "heat exchanger": ("family", "Heat transfer"),
    "rotating equipment": ("class", "Rotating"),
    "static mechanical equipment": ("class", "Static / Mechanical"),
    "pressure relief valve": ("family", "Pressure relief devices"),
    "valve": ("class", "Pressure relief and valves"),
}
PUMP = Profile("Centrifugal Pump", "Pumps", "Rotating")
VESSEL = Profile("Pressure Vessel", "Pressure vessels", "Static / Mechanical",
                 numbers={"pressure": (0.35, 0.35, "MPa")})
PSV = Profile("Pressure Safety / Relief Valve", "Pressure relief devices", "Pressure relief and valves")


def item(term, quote=..., page=1, **kw):
    """`quote` defaults to the term itself (a quote must contain the phrase that
    names the equipment); pass None for an item with no quote."""
    quote = term if quote is ... else quote
    return {"term": term, "quote": quote, "page": page, **kw}


def rec(covered=(), exclusions=(), limits=(), generic=False):
    return {"covered_equipment": list(covered), "explicit_exclusions": list(exclusions),
            "explicit_limits": list(limits), "generic_scope": generic}


# ------------------------------------------------------------ term matching

def test_a_longer_phrase_is_not_also_counted_as_its_shorter_part():
    assert nodes_for("pressure relief valves", LEX) == {("family", "Pressure relief devices")}


def test_whole_words_only():
    assert nodes_for("pumping station", LEX) == set()


# ------------------------------------------------------------------ APPLICABLE

def test_covered_family_names_the_submittal():
    r = decide(rec(covered=[item("pressure vessels", "applies to pressure vessels", 3)]), VESSEL, LEX)
    assert r["decision"] == APPLICABLE and r["quote"] == "applies to pressure vessels" and r["page"] == 3


def test_covered_class_names_the_submittal_by_taxonomy_not_by_model():
    """The v1 error: the model called a pump static. Here code knows a pump
    is Rotating, so 'static mechanical equipment' does NOT cover it."""
    r = decide(rec(covered=[item("process static mechanical equipment")]), PUMP, LEX)
    assert r["decision"] == UNKNOWN
    assert decide(rec(covered=[item("process static mechanical equipment")]), VESSEL, LEX)["decision"] == APPLICABLE


# -------------------------------------------------- NOT_APPLICABLE needs evidence

def test_a_vessel_only_scope_does_not_make_a_pump_not_applicable_by_itself():
    """THE MUTATION TARGET (M560): listing other equipment is UNKNOWN."""
    r = decide(rec(covered=[item("pressure vessels")]), PUMP, LEX)
    assert r["decision"] == UNKNOWN


def test_a_pump_is_not_applicable_only_with_an_equipment_limit_quote():
    r = decide(rec(covered=[item("pressure vessels")],
                   limits=[item("pressure vessels", "applies only to pressure vessels", 2, kind="equipment")]),
               PUMP, LEX)
    assert r["decision"] == NOT_APPLICABLE
    assert r["quote"] == "applies only to pressure vessels" and r["page"] == 2


def test_an_exclusion_naming_the_family_is_not_applicable():
    r = decide(rec(covered=[item("rotating equipment")],
                   exclusions=[item("centrifugal pumps", "does not cover centrifugal pumps", 4)]), PUMP, LEX)
    assert r["decision"] == NOT_APPLICABLE and r["basis"].startswith("explicit exclusion")


def test_an_exclusion_of_something_else_does_not_exclude_the_submittal():
    r = decide(rec(covered=[item("pressure vessels")], exclusions=[item("heat exchangers")]), VESSEL, LEX)
    assert r["decision"] == APPLICABLE


def test_an_item_without_a_quote_never_decides():
    """THE MUTATION TARGET (M561). A NUMERIC limit reads no words from its
    quote, so only the quote gate keeps an unquoted one from deciding."""
    r = decide(rec(covered=[item("pressure vessels")],
                   limits=[item("design pressure", quote=None, kind="pressure", min=1.0, unit="MPa")]),
               VESSEL, LEX)
    assert r["decision"] == APPLICABLE


# ---------------------------------------------------------- generic scope

def test_generic_scope_never_yields_not_applicable():
    """THE MUTATION TARGET (M562): a generic scope with a limit the
    submittal is outside of is still not NOT_APPLICABLE."""
    r = decide(rec(covered=[item("equipment")], generic=True,
                   limits=[item("pressure vessels", "applies only to pressure vessels", kind="equipment"),
                           item("pressure", kind="pressure", min=10, unit="MPa")]), PUMP, LEX)
    assert r["decision"] == APPLICABLE_CANDIDATE


def test_generic_scope_with_an_exclusion_naming_the_submittal_is_not_applicable():
    r = decide(rec(covered=[item("equipment")], generic=True,
                   exclusions=[item("pressure relief valves", "excluding pressure relief valves")]), PSV, LEX)
    assert r["decision"] == NOT_APPLICABLE


# ----------------------------------------------------------- numbers by code

@pytest.mark.parametrize("limit,expected", [
    ({"min": 1.0, "unit": "MPa"}, NOT_APPLICABLE),     # vessel 0.35 MPa is below
    ({"min": 15, "unit": "psig"}, APPLICABLE),         # 15 psig = 0.103 MPa, vessel above
    ({"max": 3, "unit": "bar"}, NOT_APPLICABLE),       # 0.3 MPa max, vessel 0.35 above
    ({"min": 1.0, "unit": "furlongs"}, APPLICABLE),    # unknown unit: no decision by number
])
def test_pressure_limits_are_compared_by_code(limit, expected):
    """THE MUTATION TARGET (M563) for the unit conversion."""
    r = decide(rec(covered=[item("pressure vessels")],
                   limits=[item("design pressure", kind="pressure", **limit)]), VESSEL, LEX)
    assert r["decision"] == expected


def test_an_unknown_submittal_number_never_decides():
    r = decide(rec(covered=[item("centrifugal pumps")],
                   limits=[item("design pressure", kind="pressure", min=10, unit="MPa")]), PUMP, LEX)
    assert r["decision"] == APPLICABLE


# ------------------------------ addendum 5 (B5): uncertain metadata never excludes

UNKNOWN_EQUIPMENT = Profile(None, None, None)


@pytest.mark.parametrize("record", [
    rec(covered=[item("pressure vessels")],
        limits=[item("pressure vessels", "applies only to pressure vessels", kind="equipment")]),
    rec(covered=[item("pressure vessels")], exclusions=[item("centrifugal pumps")]),
    rec(covered=[item("equipment")], generic=True,
        limits=[item("pressure vessels", kind="equipment")]),
    None,
], ids=["equipment-limit", "exclusion", "generic", "missing-scope"])
def test_unknown_equipment_type_never_yields_not_applicable(record):
    """THE MUTATION TARGET (M564): when the submittal's equipment type is
    unknown, nothing can show it falls outside the scope."""
    assert decide(record, UNKNOWN_EQUIPMENT, LEX)["decision"] != NOT_APPLICABLE


# --------------------------- M-03 run 2026-09-25: two measured wrong exclusions

def test_excluding_a_sub_kind_does_not_exclude_its_sibling():
    """THE MUTATION TARGET (M600): 'excluding submersible pumps' in the
    centrifugal-pump standard must not exclude a centrifugal pump."""
    r = decide(rec(covered=[item("centrifugal pumps", "requirements governing centrifugal pumps", 4)],
                   exclusions=[item("submersible pumps", "excluding submersible pumps that are covered", 4)]),
               PUMP, LEX)
    assert r["decision"] == APPLICABLE


def test_a_sentence_that_is_not_an_exclusion_does_not_exclude():
    """THE MUTATION TARGET (M601): a procurement instruction ('shall not be
    part of the package PO') read as a scope exclusion."""
    r = decide(rec(exclusions=[item("rotating equipment",
                                    "Rotating equipment standards shall not be part of the package PO", 7)]),
               PUMP, LEX)
    assert r["decision"] != NOT_APPLICABLE


def test_an_unqualified_family_exclusion_with_a_cue_still_excludes():
    r = decide(rec(exclusions=[item("all pumps", "This standard does not apply to all pumps", 2)]), PUMP, LEX)
    assert r["decision"] == NOT_APPLICABLE


def test_not_applicable_needs_three_agreeing_rereads():
    """THE MUTATION TARGET (M602)."""
    na = {"decision": NOT_APPLICABLE, "quote": "does not apply to pumps"}
    from app.applicability_v2 import confirm_not_applicable
    assert confirm_not_applicable([na, na, na])
    assert not confirm_not_applicable([na, na, {"decision": UNKNOWN, "quote": None}])
    assert not confirm_not_applicable([na, na])
    assert not confirm_not_applicable([na, na, {"decision": NOT_APPLICABLE, "quote": ""}])


def test_no_record_is_unknown():
    assert decide(None, PUMP, LEX)["decision"] == UNKNOWN


# ------------------------- inclusion strength (owner 2026-09-25, 3-sheet run)

NEW_VESSEL = Profile("Pressure Vessel", "Pressure vessels", "Static / Mechanical", stage="new")


def test_a_qualified_sub_kind_inclusion_is_only_a_candidate():
    """THE MUTATION TARGET (M606): a well 'subsurface' valve standard matched
    'valve' and was included for a PSV."""
    r = decide(rec(covered=[item("subsurface valves", "subsurface valves for wells", 2)]), PSV, LEX)
    assert r["decision"] == APPLICABLE_CANDIDATE and "qualified" in r["basis"]


def test_in_service_is_a_qualifier_not_two_neutral_words():
    r = decide(rec(covered=[item("in-service pressure vessels", "repair of in-service pressure vessels", 3)]),
               NEW_VESSEL, LEX)
    assert r["decision"] == APPLICABLE_CANDIDATE


def test_a_repair_only_scope_is_a_candidate_for_a_new_item():
    """THE MUTATION TARGET (M607)."""
    record = rec(covered=[item("pressure vessels", "pressure vessels", 3)])
    # quotes free of cue words, so ONLY the activity tags can trigger (M607)
    record["covered_activities"] = [{"activity": "repair", "quote": "restoration work", "page": 3},
                                    {"activity": "maintenance", "quote": "periodic upkeep", "page": 3}]
    assert decide(record, NEW_VESSEL, LEX)["decision"] == APPLICABLE_CANDIDATE
    assert decide(record, VESSEL, LEX)["decision"] == APPLICABLE          # stage unknown: no downgrade
    record["covered_activities"].append({"activity": "design", "quote": "design", "page": 3})
    assert decide(record, NEW_VESSEL, LEX)["decision"] == APPLICABLE      # design covers new items


def test_an_existing_equipment_quote_makes_a_new_item_a_candidate():
    """THE MUTATION TARGET (M608): the model tagged an in-service standard
    'repair, inspection, testing' - the verified quote says in-service."""
    record = rec(covered=[item("pressure vessels", "repair and re-rating of in-service pressure vessels", 5)])
    record["covered_activities"] = [{"activity": "inspection", "quote": "inspection", "page": 5},
                                    {"activity": "testing", "quote": "testing", "page": 5}]
    assert decide(record, NEW_VESSEL, LEX)["decision"] == APPLICABLE_CANDIDATE
    record["covered_equipment"][0]["quote"] = "design and fabrication of new pressure vessels and their repair"
    assert decide(record, NEW_VESSEL, LEX)["decision"] == APPLICABLE


def test_context_words_do_not_weaken_an_inclusion():
    r = decide(rec(covered=[item("process pressure vessels", "process pressure vessels", 3)]), NEW_VESSEL, LEX)
    assert r["decision"] == APPLICABLE


# ------------------- v4 record (b5-quality 2026-09-25): cues, quotes, stage, new build

LEX_RV = {**LEX, "relief valve": ("family", "Pressure relief devices")}


def test_a_list_item_under_an_exclusion_intro_excludes():
    """THE MUTATION TARGET (M665): the cue is in the list intro the code cut
    from the page, not in the short quote."""
    excl = item("relief valves", "safety-relief, relief and pilot valves", 6,
                cue_context="Specifically excluded from the scope are: ... a) Control,")
    assert decide(rec(exclusions=[excl]), PSV, LEX_RV)["decision"] == NOT_APPLICABLE
    excl["cue_context"] = "This standard covers"
    assert decide(rec(exclusions=[excl]), PSV, LEX_RV)["decision"] != NOT_APPLICABLE


def test_a_term_its_own_quote_does_not_contain_never_decides():
    """THE MUTATION TARGET (M666): the model wrote 'centrifugal pumps' for
    the quote 'excluding submersible pumps'."""
    r = decide(rec(exclusions=[item("centrifugal pumps", "excluding submersible pumps", 4)]), PUMP, LEX)
    assert r["decision"] != NOT_APPLICABLE
    r = decide(rec(covered=[item("pressure vessels", "covers heat exchangers", 3)]), VESSEL, LEX)
    assert r["decision"] != APPLICABLE


def test_an_equipment_limit_must_say_it_restricts():
    """THE MUTATION TARGET (M667): 'design of pressure vessels' lists; only
    'only / limited to' restricts (owner rule: listing other equipment is
    UNKNOWN)."""
    listing = item("pressure vessels", "design and installation of pressure vessels", 2, kind="equipment")
    assert decide(rec(limits=[listing]), PUMP, LEX)["decision"] == UNKNOWN
    listing["cue_context"] = "This standard is limited to the"
    assert decide(rec(limits=[listing]), PUMP, LEX)["decision"] == NOT_APPLICABLE


def test_an_in_service_stage_limit_excludes_a_new_item_only():
    """THE MUTATION TARGET (M668): a repair / re-rating standard for
    in-service vessels does not govern a NEW vessel - with a verified quote,
    and never when the stage is unknown or new build is also covered."""
    stage = item("in-service", "repair, alteration and re-rating of in-service pressure vessels", 5, kind="stage")
    record = rec(covered=[item("pressure vessels", "in-service pressure vessels", 5)], limits=[stage])
    assert decide(record, NEW_VESSEL, LEX)["decision"] == NOT_APPLICABLE
    assert decide(record, VESSEL, LEX)["decision"] != NOT_APPLICABLE              # stage unknown
    assert decide(record, Profile(None, None, None, stage="new"), LEX)["decision"] != NOT_APPLICABLE
    record["new_construction"] = [{"quote": "design of new pressure vessels", "page": 5}]
    assert decide(record, NEW_VESSEL, LEX)["decision"] != NOT_APPLICABLE
    both = item("in-service", "new and in-service pressure vessels", 5, kind="stage")
    assert decide(rec(limits=[both]), NEW_VESSEL, LEX)["decision"] != NOT_APPLICABLE
    repair_only = item("repair", "as a repair or field modification", 5, kind="stage")
    assert decide(rec(limits=[repair_only]), NEW_VESSEL, LEX)["decision"] != NOT_APPLICABLE


def test_a_verified_new_construction_quote_keeps_an_inclusion():
    """THE MUTATION TARGET (M669): 'repair welds' tagged the welding
    standard existing-only although it covers new fabrication."""
    record = rec(covered=[item("pressure vessels", "on-plot pipes, pressure vessels and", 5)])
    record["covered_activities"] = [{"activity": "repair", "quote": "production and repair welds", "page": 12}]
    assert decide(record, NEW_VESSEL, LEX)["decision"] == APPLICABLE_CANDIDATE
    record["new_construction"] = [{"quote": "welding of new pressure vessels", "page": 5}]
    assert decide(record, NEW_VESSEL, LEX)["decision"] == APPLICABLE


def test_a_negated_existing_equipment_sentence_is_not_a_stage_limit():
    """THE MUTATION TARGET (M674). MEASURED 2026-09-25: 'not applied
    retroactively to ... existing facilities' was read as a stage limit by
    three agreeing re-reads, and a welding standard for NEW vessels was
    excluded - a wrong NOT_APPLICABLE."""
    stage = item("existing facilities", "not applied retroactively to the repair of existing facilities", 6,
                 kind="stage", cue_context="This standard is generally")
    record = rec(covered=[item("pressure vessels", "welding of pressure vessels", 6)], limits=[stage])
    assert decide(record, NEW_VESSEL, LEX)["decision"] == APPLICABLE


def test_a_listed_kind_under_an_exclusion_intro_excludes_whatever_the_model_called_the_item():
    """THE MUTATION TARGET (M675): a valve-selection standard excludes
    'Control, safety-relief, relief, surge relief, solenoid, pilot, and other
    valves'; the model tagged the item 'control valves'. Code reads the list:
    'relief' is an item, so relief valves are excluded - but 'surge relief'
    alone, or 'other valves', would not exclude a relief valve."""
    quote = "Control, safety-relief, relief, surge relief, solenoid, pilot, and other valves"
    intro = "1.2 Specifically excluded from the scope are: a)"
    excl = item("control valves", quote, 6, cue_context=intro)
    assert decide(rec(exclusions=[excl]), PSV, LEX_RV)["decision"] == NOT_APPLICABLE
    for other in ("Control, safety-relief, surge relief, solenoid and pilot valves",
                  "Control, solenoid, pilot, and other valves"):
        assert decide(rec(exclusions=[item("control valves", other, 6, cue_context=intro)]),
                      PSV, LEX_RV)["decision"] != NOT_APPLICABLE
    no_intro = item("control valves", quote, 6, cue_context="This standard covers")
    assert decide(rec(exclusions=[no_intro]), PSV, LEX_RV)["decision"] != NOT_APPLICABLE
