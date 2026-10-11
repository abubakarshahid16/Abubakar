"""#725 F5 (#733): standards chosen by equipment type; a materials standard only
for material fields; including reasons outrank candidate-only ones.

Before: a relief-valve datasheet that did not cite API 520 by a spelling the
library knew got no API 520 at all ("no citation, equipment, discipline,
service or project match"), while NACE MR0175 (cited once) was applied to
every alloy-composition table row. Invented documents and values only.

Mutations: M6901-M6912 (scripts/mutations/f5_733_governing_standards.py).
"""
from __future__ import annotations

import json

import pytest

from app import applicability, scope_ledger, subject_scope
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401


def _psv(**meta):
    return _doc("sub", "psv-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
                text="Set pressure 340 psig. Body material SA-216 WCB.", **meta)


def _rows(result):
    return {s["standard_document_id"]: s for s in result["selected"]}


# ------------------------------------------------------------- governing standards


def test_a_relief_valve_datasheet_gets_api_520_without_citing_it():
    """THE MUTATION TARGET."""
    std = _doc("std_520", "API-520-I.pdf", "COMPANY_STANDARD", document_number="API 520 Part I")
    sub = _psv(equipment_type="relief valve")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    row = _rows(result).get(std)
    assert row is not None, "API 520 Part I was not selected for a relief valve"
    assert row["method"] == applicability.METHOD_GOVERNING
    assert row["included"] is True
    assert "relief valve" in row["reason"] and "classification" in row["reason"]


def test_governing_standards_the_library_does_not_hold_are_listed_never_met():
    sub = _psv(equipment_type="relief valve")
    result = applicability.select(sub, allowed_document_ids=_scope(sub), persist=False)
    names = {g["identifier"] for g in result["governing_not_held"]}
    assert {"API 520 Part I", "API 526", "SAES-J-600"} <= names
    assert all("not present in the library" in g["reason"] for g in result["governing_not_held"])
    assert result["missing_references"] == [] and result["selected"] == []


def test_the_type_can_come_from_the_title_and_the_reason_says_so():
    std = _doc("std_526", "API-526.pdf", "COMPANY_STANDARD", document_number="API 526")
    sub = _psv(title="Pressure relief valve data sheet")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert "read from the submittal's title" in _rows(result)[std]["reason"]


def test_an_unknown_equipment_type_selects_nothing_by_this_rule():
    std = _doc("std_526", "API-526.pdf", "COMPANY_STANDARD", document_number="API 526")
    sub = _doc("sub", "misc.pdf", "CONTRACTOR_SUBMITTAL", text="General notes only.")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert std not in _rows(result)
    assert result["governing_not_held"] == []


def test_a_governing_standard_also_cited_is_reported_once():
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL", text="Sizing per API 526.",
               equipment_type="relief valve")
    result = applicability.select(sub, allowed_document_ids=_scope(sub), persist=False)
    assert [m["identifier"] for m in result["missing_references"]] == ["API 526"]
    assert "API 526" not in {g["identifier"] for g in result["governing_not_held"]}


def test_the_table_is_data_and_a_broken_table_raises(tmp_path):
    table = applicability.governing_table()
    assert "API 520 Part I" in table["equipment_types"]["relief valve"]
    bad = tmp_path / "g.json"
    bad.write_text(json.dumps({"format": "governing-standards/1", "equipment_types": {"pump": "API 610"},
                               "materials_standards": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        applicability.governing_table(bad)


def test_every_equipment_type_in_the_table_is_in_the_shared_vocabulary():
    vocab = json.loads(subject_scope.VOCABULARY_PATH.read_text(encoding="utf-8"))["types"]
    assert set(applicability.governing_table()["equipment_types"]) <= set(vocab)


# ------------------------------------------------------------- reason priority


def test_an_including_reason_beats_a_candidate_only_one():
    for strong in applicability.INCLUDING_METHODS:
        for weak in set(applicability.CANDIDATE_ONLY_REASON) | {"semantic"}:
            assert applicability._PRIORITY[strong] < applicability._PRIORITY[weak], (strong, weak)


def test_a_service_match_is_kept_over_a_shared_discipline():
    std = _doc("std_sv", "sour.pdf", "COMPANY_STANDARD", service="sour", discipline="Mechanical")
    sub = _doc("sub", "s.pdf", "CONTRACTOR_SUBMITTAL", service="sour", discipline="Mechanical")
    row = _rows(applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False))[std]
    assert row["method"] == applicability.METHOD_SERVICE and row["included"] is True


# ------------------------------------------------------------- materials standards


def _cell(row, sid="nace", rtype="table_value"):
    return {"standard_document_id": sid, "requirement_type": rtype, "condition": row,
            "requirement_text": f"{row} - Ni %: 58"}


LABELS = {"nace": "NACE MR0175 ISO 15156-3", "api": "API-526.pdf"}


def _gate(reqs, facts):
    return subject_scope.materials_gate(reqs, facts=facts, standard_labels=LABELS,
                                        is_materials_standard=applicability.is_materials_standard)


def _material(value):
    return {"field_name": "body material", "field_label": "Body material", "field_value": value,
            "raw_value": value, "is_blank": False}


def test_a_materials_standard_does_not_apply_when_no_material_is_stated():
    sentence = {"standard_document_id": "nace", "requirement_type": "numeric_limit", "condition": None,
                "requirement_text": "Hardness shall not exceed 22 HRC."}
    out = _gate([_cell("UNS N06625"), sentence, _cell("Grade X", sid="api")], [])
    assert [r["standard_document_id"] for r in out["kept"]] == ["api"]
    assert {i["code"] for i in out["items"]} == {"not_material_field"}
    assert all("states no material" in i["detail"] for i in out["items"])


def test_only_the_rows_naming_a_stated_material_are_kept():
    out = _gate([_cell("316L"), _cell("UNS N06625")], [_material("316L stainless steel")])
    assert [r["condition"] for r in out["kept"]] == ["316L"]
    [item] = out["items"]
    assert "UNS N06625" in item["detail"]


def test_a_materials_sentence_stays_a_check_while_a_material_is_stated():
    sentence = {"standard_document_id": "nace", "requirement_type": "numeric_limit", "condition": None,
                "requirement_text": "Hardness shall not exceed 22 HRC."}
    out = _gate([sentence], [_material("SA-216 WCB")])
    assert out["kept"] == [sentence] and out["items"] == []


def test_a_placeholder_material_is_not_a_stated_material():
    sentence = {"standard_document_id": "nace", "requirement_type": "numeric_limit", "condition": None,
                "requirement_text": "Hardness shall not exceed 22 HRC."}
    out = _gate([sentence], [_material("TBA")])
    assert out["kept"] == []
    assert "states no material" in out["items"][0]["detail"]


def test_the_reason_code_is_a_ledger_reason():
    assert scope_ledger.REASONS["not_material_field"][0] == scope_ledger.DOES_NOT_APPLY


def test_materials_standards_are_recognised_by_label_and_entry():
    assert applicability.is_materials_standard("NACE MR0175 ISO 15156-2")
    assert not applicability.is_materials_standard("API-526.pdf")
    assert applicability.is_materials_standard({"id": "n", "filename": "x.pdf", "document_number": "ISO 15156-3"})
