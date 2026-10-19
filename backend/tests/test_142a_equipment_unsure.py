"""Order 142 A: what the datasheet says about itself outranks the type guess.

A sheet guessed to be one equipment type, whose own field VALUE states a
code that governs another type, and which names no code of the guessed type,
is read as UNSURE: nothing is ruled out by equipment type, and the engineer
is asked to confirm the type. Invented documents and values only.
"""

from __future__ import annotations

from app import applicability, classification, datasheets, subject_scope
from tests.test_applicability import _doc, _run, _scope, temp_storage  # noqa: F401

VESSEL_REQ = {
    "requirement_text": "The vessel shell shall be hydrotested.",
    "standard_document_id": "std_asme",
    "clause": "1.1",
}
DECLARED = [
    {"field_label": "Design code", "field_value": "ASME Sec VIII Div.1", "page": 1}
]


def _gate(cls, facts, requirements=(VESSEL_REQ,)):
    return subject_scope.gate(list(requirements), classification=cls, facts=facts)


def _fact(sub, label, value, page=1):
    datasheets.create_fact(
        submittal_document_id=sub,
        chunk_id=f"{sub}-c1",
        field_label=label,
        raw_value=value,
        page=page,
        review_run_id=_run(sub),
    )


def _assert_unsure(out):
    summary = out["summary"]
    assert out["kept"] == [VESSEL_REQ]
    assert summary["kept_equipment_unknown"] == 1
    assert summary["not_applied"] == 0
    assert summary["equipment_source"] == subject_scope.SOURCE_UNSURE == "unsure"
    reason = summary["equipment_unsure"]
    assert "engineer" in reason and "ASME Sec VIII Div.1" in reason
    assert "Design code" in reason and "page 1" in reason
    for word in ("compliant", "not applicable", "%"):
        assert word not in reason.lower()


def test_a_declared_vessel_code_on_a_sheet_read_as_an_exchanger_keeps_vessel_requirements():
    out = _gate({"equipment_type": "Heat Exchanger"}, DECLARED)
    _assert_unsure(out)
    assert out["not_applied"] == [] and out["not_applied_items"] == []


def test_the_same_with_the_db_record():
    _doc(
        "sub",
        "vessel-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Design code: ASME Sec VIII Div.1",
        equipment_type="Heat Exchanger",
    )
    _fact("sub", "Design code", "ASME Sec VIII Div.1")
    cls = classification.of_document("sub")
    facts = datasheets.list_facts("sub", allowed_document_ids=_scope("sub"))
    _assert_unsure(_gate(cls, facts))
    # The chunk-text path: the same sheet whose own text names an exchanger
    # code is a sure exchanger, so the vessel requirement is not applied.
    _doc(
        "sub2",
        "exchanger-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Design code: ASME Sec VIII Div.1. Construction per API 660.",
        equipment_type="Heat Exchanger",
    )
    _fact("sub2", "Design code", "ASME Sec VIII Div.1")
    out = _gate(
        classification.of_document("sub2"),
        datasheets.list_facts("sub2", allowed_document_ids=_scope("sub2")),
    )
    assert out["summary"]["not_applied"] == 1
    assert out["summary"]["equipment_unsure"] is None


def test_a_sheet_whose_declared_code_matches_its_type_is_unchanged():
    facts = [{"field_label": "Design code", "field_value": "API 660", "page": 1}]
    out = _gate({"equipment_type": "Heat Exchanger"}, facts)
    assert out["kept"] == []
    assert out["summary"]["not_applied"] == 1
    assert out["summary"]["submittal_equipment"] == ["heat exchanger"]
    assert out["summary"]["equipment_source"] == "classification"
    assert out["summary"].get("equipment_unsure") is None


def test_a_relief_valve_stating_asme_viii_is_not_unsure():
    cls = {"equipment_type": "Pressure Safety Valve"}
    facts = [{"field_label": "Code", "field_value": "ASME VIII Div 1", "page": 1}]
    vocab = subject_scope.vocabulary()
    equipment, source = subject_scope.submittal_equipment(cls, facts, vocab)
    assert (equipment, source) == ({"relief valve"}, "classification")
    turbine = {
        "requirement_text": "The steam turbine casing relief device shall be tested.",
        "standard_document_id": "std_j600",
        "clause": "8.7",
    }
    out = _gate(cls, facts, [turbine])
    assert out["kept"] == [] and out["summary"]["not_applied"] == 1
    opening = {
        "requirement_text": "Openings in the shell shall be reinforced.",
        "standard_document_id": "std_asme",
    }
    relief = {
        "requirement_text": "The pressure relief device shall be stamped.",
        "standard_document_id": "std_asme",
    }
    partial = subject_scope.partial_gate(
        [opening, relief],
        equipment=equipment,
        standard_labels={"std_asme": "ASME BPVC Section VIII Division 1"},
        partial_standards=applicability.governing_table()["partial_standards"],
    )
    assert partial["kept"] == [relief]
    assert [i["code"] for i in partial["items"]] == ["outside_partial_scope"]


def test_a_pump_sheet_citing_its_own_code_somewhere_stays_a_pump():
    cls = {"equipment_type": "Pump"}
    vocab = subject_scope.vocabulary()
    facts = [
        {"field_label": "Motor", "field_value": "IEC 60034", "page": 2},
        {"field_label": "Pump code", "field_value": "API 610", "page": 1},
    ]
    assert subject_scope.submittal_equipment(cls, facts, vocab) == (
        {"pump"},
        "classification",
    )
    # A motor drives the pump: its code alone, or under a label that does not
    # name it, is about the driver and never a doubt (vocabulary `driver`).
    assert (
        subject_scope.submittal_equipment(cls, facts[:1], vocab)[1] == "classification"
    )
    driver = [
        {"field_label": "Driver standard", "field_value": "IEC 60034-1", "page": 2}
    ]
    assert subject_scope.submittal_equipment(cls, driver, vocab)[1] == "classification"


def test_a_code_under_a_label_naming_its_own_type_is_about_that_sub_item():
    """A vessel sheet listing its relief valve's code: the label names the
    type the code governs, so the fact is about the valve, not the sheet."""
    cls = {"equipment_type": "Pressure Vessel"}
    vocab = subject_scope.vocabulary()
    sub_item = [{"field_label": "Relief valve", "field_value": "API 526", "page": 2}]
    assert subject_scope.read_equipment(cls, sub_item, vocab)[2] is None
    plain = [{"field_label": "Design code", "field_value": "API 526", "page": 2}]
    assert subject_scope.read_equipment(cls, plain, vocab)[1] == "unsure"


def test_an_engineer_confirmed_type_is_never_unsure():
    _doc(
        "sub",
        "vessel-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text="Design code: ASME Sec VIII Div.1",
        equipment_type="Heat Exchanger",
    )
    _fact("sub", "Design code", "ASME Sec VIII Div.1")
    # The record as `classification.confirm` leaves it (confirmed_by is a
    # user foreign key, so the confirmation is set on the read record).
    cls = {
        **classification.of_document("sub"),
        "confirmed_by": "eng1",
        "confirmed": True,
    }
    facts = datasheets.list_facts("sub", allowed_document_ids=_scope("sub"))
    equipment, source, doubt = subject_scope.read_equipment(
        cls, facts, subject_scope.vocabulary()
    )
    assert (equipment, source, doubt) == ({"heat exchanger"}, "classification", None)
    out = _gate(cls, facts)
    assert out["summary"]["not_applied"] == 1
    assert out["summary"]["equipment_unsure"] is None


def test_a_title_alone_is_never_a_doubt():
    """A title often names the protected or driven equipment ("KO drum
    overpressure protection"): a relief valve stays a relief valve."""
    vocab = subject_scope.vocabulary()
    psv = {
        "equipment_type": "Pressure Safety Valve",
        "title": "Knockout drum relief data sheet",
    }
    assert subject_scope.read_equipment(psv, [], vocab) == (
        {"relief valve"},
        "classification",
        None,
    )
    hx = {"equipment_type": "Heat Exchanger", "title": "Knockout drum data sheet"}
    assert subject_scope.read_equipment(hx, [], vocab)[1] == "classification"


def test_stated_codes_reads_values_not_labels():
    facts = [
        {"field_label": "API 610 rev", "field_value": "", "page": 1},
        {"field_label": "Notes", "field_value": "API 610", "is_blank": True, "page": 1},
        {
            "field_label": "Design code",
            "field_value": "ASME VIII DIV. 1 / TEMA R",
            "page": 3,
        },
    ]
    stated = subject_scope.stated_codes(facts)
    assert [s["identifier"] for s in stated] == ["ASME VIII DIV. 1", "TEMA R"]
    assert all(s["label"] == "Design code" and s["page"] == 3 for s in stated)
