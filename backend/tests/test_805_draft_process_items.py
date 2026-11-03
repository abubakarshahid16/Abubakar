"""Part of #805: two DRAFT relief-valve process items (fluid phase PSV-D01, sour service PSV-D02) beside the
approved #746 ones. The governing relief case is already PSV-S05 (an approved item); it is covered here too.

What must hold: switch OFF, the checklist is as it was; ON, a draft item never decides: not stated is the
contractor's gap ("Not stated. ... Contractor to provide ..."), a stated value gives no verdict and no row,
sour service stated "yes" is a QUERY for materials (NACE MR0175 / ISO 15156), never a Pass or Fail; a draft
item does not make its standard "governed". Invented values only.
"""

from __future__ import annotations

import uuid

import pytest

from app import checklist_scope, db, submittal_review
from app import datasheet_checks as dc
from app import draft_items as di
from app.config import settings
from tests.test_746_relief_valve_checklist import PSV, SHEET, fact

NOW = "2026-11-03T00:00:00Z"
PAGES = {1: "x"}
BASE = [f for f in SHEET if f["field_name"] not in ("fluid phase",)]


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "draft_process_items_enabled", True)


def got(facts, pages=PAGES):
    return {
        r["rule_id"]: r
        for r in dc.evaluate(facts, equipment_type=PSV, page_texts=pages)
        if r.get("checklist")
    }


def test_switch_off_the_checklist_has_no_draft_item():
    ids = [i["id"] for i in dc.checklist_for(PSV, dc.load_rules())["items"]]
    assert "PSV-D01" not in ids and "PSV-D02" not in ids
    assert "PSV-D01" not in got(BASE) and "PSV-D02" not in got(BASE)


def test_the_draft_items_cite_a_clause_and_the_approved_items_are_unchanged(on):
    items = {i["id"]: i for i in dc.checklist_for(PSV, dc.load_rules())["items"]}
    assert (
        items["PSV-D01"]["source"]["standard"] == "API 520-I"
        and items["PSV-D01"]["clause_to_confirm"] is True
    )
    assert items["PSV-D02"]["source"] == {"standard": "ISO 15156-3", "clause": "6.1"}
    assert items["PSV-D02"]["answer"]["choices"] == ["yes", "no", "not stated"]
    drafts = {i for i, item in items.items() if di.is_draft(item)}
    assert drafts == {"PSV-D01", "PSV-D02"}
    assert items["PSV-S05"]["rule"] == {
        "kind": "required",
        "field": "relief_case",
    }  # the governing case, approved
    assert "status" not in items["PSV-S05"]


def test_not_stated_is_the_contractors_gap_not_a_verdict(on):
    r = got(BASE)
    for rule_id in ("PSV-D01", "PSV-D02"):
        assert r[rule_id]["status"] == "MISSING_INFORMATION"
        assert r[rule_id]["detail"].startswith("Not stated. ")
        assert "ontractor" in r[rule_id]["detail"] and "provide" in r[rule_id]["detail"]
        assert "draft item, engineer to approve" in r[rule_id]["text"]
        assert r[rule_id]["draft"] is True
    assert (
        "clause to confirm" in r["PSV-D01"]["text"]
        and "clause to confirm" not in r["PSV-D02"]["text"]
    )


@pytest.mark.parametrize("marker", ["TBA", "*"])
def test_a_placeholder_is_not_stated(on, marker):
    r = got(
        [
            *BASE,
            fact("fluid phase", marker, blank=marker),
            fact("sour service", marker, blank=marker),
        ]
    )
    assert r["PSV-D01"]["status"] == r["PSV-D02"]["status"] == "MISSING_INFORMATION"
    assert r["PSV-D01"]["detail"].startswith("Not stated.")


def test_a_stated_phase_gives_no_verdict(on):
    r = got([*BASE, fact("fluid phase", "Gas")])["PSV-D01"]
    assert r["status"] == di.STATED_NO_VERDICT != "COMPLIANT"
    assert "no verdict" in r["detail"] and "Gas" in r["detail"]


@pytest.mark.parametrize("value", ["Yes", "yes - H2S present", "Sour"])
def test_sour_service_yes_is_a_query_for_materials(on, value):
    r = got([*BASE, fact("sour service", value)])["PSV-D02"]
    assert r["status"] == "NEEDS_ENGINEER_REVIEW"
    assert (
        "Query for materials" in r["detail"]
        and "NACE MR0175 / ISO 15156" in r["detail"]
    )


@pytest.mark.parametrize("value", ["No", "None", "Not applicable", "non-sour"])
def test_sour_service_no_gives_no_verdict(on, value):
    r = got([*BASE, fact("sour service", value)])["PSV-D02"]
    assert r["status"] == di.STATED_NO_VERDICT


@pytest.mark.parametrize("value", ["Yes / No", "2 mol% H2S"])
def test_sour_service_unclear_is_the_engineers_to_read(on, value):
    r = got([*BASE, fact("sour service", value)])["PSV-D02"]
    assert (
        r["status"] == "NEEDS_ENGINEER_REVIEW" and "engineer to read it" in r["detail"]
    )


def test_the_other_ways_a_sheet_prints_the_labels_are_read(on):
    r = got([*BASE, fact("physical state", "Liquid"), fact("sour environment", "yes")])
    assert r["PSV-D01"]["status"] == di.STATED_NO_VERDICT
    assert r["PSV-D02"]["status"] == "NEEDS_ENGINEER_REVIEW"
    # a phase printed this way also reaches the approved items that depend on it
    assert (
        r["PSV-22"]["status"] == "MISSING_INFORMATION"
    )  # liquid: density at relieving conditions


def test_the_governing_relief_case_is_asked_by_the_approved_item(on):
    without = [f for f in BASE if f["field_name"] != "relief case"]
    assert got(without)["PSV-S05"]["status"] == "MISSING_INFORMATION"
    assert got(BASE)["PSV-S05"]["status"] == "COMPLIANT"


def test_a_draft_item_does_not_make_its_standard_governed(on):
    governed = checklist_scope.standards(dc.checklist_for(PSV, dc.load_rules()))
    assert "ISO 15156-3" not in governed and "SAES-J-600" in governed


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "d.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('sub','psv.pdf','s',1,'x','ready',2,?)",
            (NOW,),
        )
        run_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,'sub','completed',?,?)",
            (run_id, NOW, NOW),
        )
    yield run_id
    db.reset_connection()


def test_a_stated_value_writes_no_row_and_the_gaps_and_queries_are_rows(on, run):
    facts = [*BASE, fact("fluid phase", "Gas"), fact("sour service", "yes")]
    dc.store(
        run,
        "sub",
        dc.evaluate(
            facts,
            equipment_type=PSV,
            page_texts={1: "Rev Date Description\nPrepared Checked Approved"},
        ),
        pages_read={},
    )
    rows = [
        dict(r)
        for r in db.connect().execute(
            "SELECT * FROM review_findings WHERE review_run_id = ?", (run,)
        )
    ]
    d = [r for r in rows if "PSV-D0" in (r["requirement_source_text"] or "")]
    assert [r["compliance_status"] for r in d] == [
        "NEEDS_ENGINEER_REVIEW"
    ]  # sour yes only; the phase writes none
    assert "PSV-D02" in d[0]["requirement_source_text"]
