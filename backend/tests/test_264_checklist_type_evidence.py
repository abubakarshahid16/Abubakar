"""Order 264 / 2p gate on 216400C: a vessel or exchanger checklist runs only when the sheet's TITLE (or a person)
named the type. A drum sheet that mentions "heat exchanger" twice in its body was labelled "Heat Exchanger"
by the classifier (`body_phrase_match`) and was asked for tubes, TEMA type and heat duty: 12 false
"contractor to provide" rows. Invented sheets."""

from __future__ import annotations

import json

import pytest

from app import checklist_scope, comparison, db, submittal_review
from app import datasheet_checks as dc
from app.config import settings
from tests.test_746_relief_valve_checklist import fact
from tests.test_field_naming import _world

BODY = {"method": "body_phrase_match", "page": 4, "quote": "heat exchanger"}
TITLE = {"method": "title_phrase_match", "page": 1, "quote": "heat exchanger"}


def cls(equipment_type, evidence=None, confirmed=False):
    return {
        "equipment_type": equipment_type,
        "equipment_type_evidence": evidence,
        "confirmed": confirmed,
    }


@pytest.mark.parametrize(
    ("classification", "expected"),
    [
        (cls("Heat Exchanger", BODY), None),
        (cls("Pressure Vessel", BODY), None),
        (cls("Drum", BODY), None),
        (cls("Heat Exchanger", TITLE), "Heat Exchanger"),
        (cls("Pressure Vessel", TITLE), "Pressure Vessel"),
        (cls("Heat Exchanger", BODY, confirmed=True), "Heat Exchanger"),
        (
            cls("Heat Exchanger", None),
            "Heat Exchanger",
        ),  # set by hand: no classifier evidence
        # the other checklists are unchanged whatever read the type
        (cls("Centrifugal Pump", BODY), "Centrifugal Pump"),
        (cls("Pressure Safety Valve", BODY), "Pressure Safety Valve"),
        (cls("Compressor", BODY), "Compressor"),
        (cls(None, None), None),
        ({}, None),
        (None, None),
    ],
)
def test_a_title_only_checklist_is_chosen_from_a_title_or_a_person_never_a_body_mention(
    classification, expected
):
    assert checklist_scope.review_type(classification) == expected


def _hex_rows(evidence):
    facts = [fact("design pressure", "3.5", "barg", label="Design pressure")]
    return [
        r
        for r in checklist_scope.evaluate(
            facts, cls("Heat Exchanger", evidence), {1: "x"}
        )
        if str(r.get("rule_id", "")).startswith("HEX-")
    ]


def test_a_review_with_no_checklist_type_asks_no_exchanger_question_and_one_with_the_type_asks_all_19():
    assert len(_hex_rows(TITLE)) == 19
    assert _hex_rows(BODY) == []  # a weak type


def test_the_data_marks_exactly_the_two_new_drafts():
    table = dc.load_rules()["checklists"]
    marked = {
        k
        for k, v in table.items()
        if isinstance(v, dict) and v.get("type_from_title_only")
    }
    assert marked == {"Pressure Vessel", "Heat Exchanger"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "type_evidence.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _review(equipment_type, evidence):
    _req, _fact, run, scope = _world("Design pressure", "3.5 barg")
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = ?, equipment_type_evidence = ?"
            " WHERE document_id = 'sub-1'",
            (equipment_type, json.dumps(evidence) if evidence else None),
        )
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    return [
        f
        for f in result["findings"]
        if str(f.get("rule_id") or f.get("requirement_source_text") or "").find("HEX-")
        >= 0
    ]


def test_a_review_of_a_sheet_whose_body_mentions_an_exchanger_asks_no_exchanger_question(
    world,
):
    assert _review("Heat Exchanger", BODY) == []


def test_a_review_of_a_sheet_titled_an_exchanger_still_gets_the_exchanger_checklist(
    world,
):
    assert _review("Heat Exchanger", TITLE) != []


NO_REVISION_BLOCK = (
    "Design pressure 3.5 barg"  # a passing DS-R1 writes no row; a missing one does
)


def _whole_review(equipment_type, evidence):
    _req, _fact, run, scope = _world("Design pressure", "3.5 barg")
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = ?, equipment_type_evidence = ?"
            " WHERE document_id = 'sub-1'",
            (equipment_type, json.dumps(evidence)),
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES ('sub-1',1,?,?,0,0)",
            (NO_REVISION_BLOCK, len(NO_REVISION_BLOCK)),
        )
    return comparison.run_comparison(run, allowed_document_ids=scope)


@pytest.mark.parametrize("evidence", [BODY, TITLE])
def test_a_sheet_whose_type_is_withheld_from_the_checklist_still_gets_the_revision_check(
    world, evidence
):
    """cloud on 4c8f89c9: the withheld type must not switch DS-R1 off while the run says it ran."""
    result = _whole_review("Pressure Vessel", evidence)
    ds_r1 = [f for f in result["findings"] if "DS-R1" in json.dumps(f, default=str)]
    assert ds_r1, "DS-R1 did not run and the run does not say so"
