"""#725 F6 (#734): a clause with an application condition applies only when the
datasheet matches.

On the 2 Oct PSV review, relief-valve clauses written for turbine exhaust,
pump discharge and thermal relief were applied to gas-analyser PSVs. Now such
a clause (marked by its wording, or by the heading of its clause or a parent
clause) does not apply when the datasheet's application fields state a value
naming none of the condition's terms, and the stated field is cited. If the
sheet states no application, the clause stays a check: unknown is never "does
not apply". Invented values only. The conditions are data
(`reference/service_conditions.json`).

Mutations: M7001-M7008 (scripts/mutations/f6_734_clause_conditions.py).
"""
from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, scope_ledger, service_scope
from tests.test_w5_677_scope_ledger import NOW, _chunk, _doc, temp_storage  # noqa: F401

TURBINE = {"id": "t", "standard_document_id": "saes", "clause": "8.7.2",
           "requirement_text": "The relief valve on a turbine exhaust shall be full bore."}
PUMP = {"id": "p", "standard_document_id": "saes", "clause": "8.8.1",
        "requirement_text": "Relief valves on pump discharge shall return to suction."}
UNDER_HEADING = {"id": "h", "standard_document_id": "saes", "clause": "8.9.3",
                 "requirement_text": "The set pressure shall not exceed the design pressure."}
GENERAL = {"id": "g", "standard_document_id": "saes", "clause": "6.1",
           "requirement_text": "Every relief valve shall carry a tag plate."}
HEADINGS = {"saes": {"8.9": "8.9 Thermal relief valves", "8.7": "8.7 Turbine exhaust"}}


def _gate(facts, reqs=(TURBINE, PUMP, UNDER_HEADING, GENERAL)):
    return service_scope.gate(list(reqs), facts=facts, standard_labels={"saes": "SAES-J-600"},
                              headings_by_standard=HEADINGS)


def _field(label, value, page=1):
    return {"field_label": label, "field_value": value, "page": page}


def test_an_application_the_sheet_states_otherwise_sets_the_clauses_aside():
    """THE MUTATION TARGET: a gas-analyser PSV gets no turbine, pump or thermal clause."""
    out = _gate([_field("Service", "Gas chromatograph sample line", page=1)])
    assert [r["id"] for r in out["kept"]] == ["g"]
    items = {i["requirement"]["id"]: i for i in out["items"]}
    assert set(items) == {"t", "p", "h"}
    assert all(i["code"] == "service_condition_not_met" for i in items.values())
    assert "turbine exhaust relief" in items["t"]["detail"]
    assert "Service: Gas chromatograph sample line, page 1" in items["t"]["detail"]


def test_a_matching_application_keeps_its_clauses():
    out = _gate([_field("Relieving case", "Steam turbine exhaust")])
    kept = {r["id"] for r in out["kept"]}
    assert "t" in kept
    assert "p" not in kept and "h" not in kept


def test_any_stated_field_naming_the_condition_keeps_it():
    out = _gate([_field("Service", "Gas"), _field("Governing case", "Thermal expansion of blocked-in liquid")])
    assert "h" in {r["id"] for r in out["kept"]}


@pytest.mark.parametrize("facts", [
    [],                                                    # nothing on the sheet
    [_field("Service", "TBA")],                            # a placeholder is not a statement
    [_field("Set pressure", "340 psig")],                  # no application field at all
])
def test_an_unstated_application_keeps_every_clause_a_check(facts):
    out = _gate(facts)
    assert [r["id"] for r in out["kept"]] == ["t", "p", "h", "g"]
    assert out["items"] == []


def test_a_clause_is_marked_by_its_parent_heading():
    out = _gate([_field("Service", "Gas")], reqs=(UNDER_HEADING,))
    assert out["kept"] == [] and "thermal relief" in out["items"][0]["detail"]
    no_headings = service_scope.gate([UNDER_HEADING], facts=[_field("Service", "Gas")],
                                     standard_labels={"saes": "SAES-J-600"}, headings_by_standard={})
    assert no_headings["kept"] == [UNDER_HEADING]


def test_the_conditions_are_data():
    names = {c["name"]: c for c in service_scope.conditions()}
    for name in ("turbine exhaust relief", "pump discharge relief", "thermal relief"):
        assert names[name]["mode"] == "value" and names[name]["satisfied_by"]


# ------------------------------------------------------------------ end to end


def test_a_review_run_records_the_clause_as_not_applying_with_the_cited_field():
    std = _doc("saes", "SAES-J-600.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "psv-sheet.pdf", "CONTRACTOR_SUBMITTAL", equipment_type="Pressure Safety Valve")
    sc, fc = _chunk("sc", std), _chunk("fc", sub)
    # The clause's own wording says nothing about thermal relief: only the
    # parent heading, read from the standard's chunks, marks it.
    with db.connect() as conn:
        conn.execute("UPDATE chunks SET section = '8.9 Thermal relief valves' WHERE id = ?", (sc,))
    from app import standards
    rid = standards.create_requirement(
        standard_document_id=std, chunk_id=sc, clause="8.9.3", page=1,
        requirement_text=UNDER_HEADING["requirement_text"], source_text=UNDER_HEADING["requirement_text"],
        structured={"requirement_type": "statement"})["id"]
    datasheets.create_fact(submittal_document_id=sub, chunk_id=fc, field_label="Service",
                           raw_value="Gas chromatograph sample line", page=1)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                     " VALUES (?,?,'pending',?,?)", (run, sub, NOW, NOW))
        conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
                     "selection_method,included,created_at) VALUES (?,?,?,'rule',1,?)",
                     (str(uuid.uuid4()), run, std, NOW))
    comparison.run_comparison(run, allowed_document_ids=frozenset({std, sub}))
    [decision] = [d for d in scope_ledger.decisions_for(run) if d["requirement_id"] == rid]
    assert (decision["state"], decision["reason_code"]) == (scope_ledger.DOES_NOT_APPLY,
                                                            "service_condition_not_met")
    assert "Gas chromatograph" in decision["reason"]
