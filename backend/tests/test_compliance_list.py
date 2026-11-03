"""Owner 3 Nov 11:40 (b): a value only a draft rule checks, with nothing found, is no CRS row; it is on the internal
sheet "Compliance list". Invented findings only."""

from __future__ import annotations

import io

import openpyxl

from app import compliance_list as cl
from app import crs_export, crs_mapping, rule_trust
from app.config import settings


def held_pass(**over):
    base = {
        "id": "f1",
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "rule_said": "COMPLIANT",
        "trust_label": "UNPROVEN",
        "contractor_evidence_text": "12 barg",
        "contractor_page": 1,
        "contractor_section": "Design pressure",
        "standard_clause": "4.1",
        "finding": "Design pressure 12 barg (page 1) is stated.",
    }
    return {**base, **over}


def on(monkeypatch, value=True):
    monkeypatch.setattr(settings, "crs_compliance_list_enabled", value)


def test_the_label_words_are_the_trust_modules(monkeypatch):
    assert cl.UNPROVEN == rule_trust.UNPROVEN
    people = {
        rule_trust.OWNER_APPROVED,
        rule_trust.OWNER_NOTE_CONTEXT,
        rule_trust.ENGINEER_CONFIRMED,
    }
    assert people <= set(cl.PERSON_LABELS)


def test_a_given_value_a_draft_rule_passed_is_listed_only_with_the_switch_on(
    monkeypatch,
):
    on(monkeypatch, False)
    assert not cl.is_listed(held_pass())
    on(monkeypatch)
    assert cl.is_listed(held_pass())


def test_a_value_not_read_a_failure_or_a_person_decided_rule_is_never_listed(
    monkeypatch,
):
    on(monkeypatch)
    assert not cl.is_listed(held_pass(contractor_evidence_text=""))
    assert not cl.is_listed(held_pass(rule_said="NON_COMPLIANT"))
    assert not cl.is_listed(held_pass(trust_label="OWNER_APPROVED"))
    assert not cl.is_listed(held_pass(confirmed_by="user-1"))
    assert not cl.is_listed(held_pass(approval_status="rejected"))
    assert not cl.is_listed(held_pass(compliance_status="NON_COMPLIANT"))


def test_a_safety_field_leaves_the_crs_but_is_never_no_issue_and_keeps_its_open_tick(
    monkeypatch,
):
    on(monkeypatch)
    tick = held_pass(
        compliance_status="COMPLIANT",
        rule_said=None,
        trust_label="TESTED_CARD",
        show_for_engineer_tick=True,
    )
    plain = held_pass(contractor_section="Plain")
    safe = held_pass(tier="SAFETY", contractor_section="Safe")
    lines = cl.sheet_rows([plain, tick, safe])
    assert len(lines) == 3
    status = {line[1]: line[4] for line in lines}
    assert status["Safe"] == cl.SAFETY_STATUS
    assert status["Plain"] == cl.STATUS
    assert [line[4] for line in lines].count("No issue found (draft rule)") == 1
    assert [line[4] for line in lines[:2]] == [cl.SAFETY_STATUS] * 2  # grouped on top
    assert "tick still open" in cl.SAFETY_STATUS
    assert not cl.is_listed({**tick, "confirmed_by": "user-1"})  # a ticked one is a row
    assert "2 safety fields" in cl.count_line(2, 3)


def test_a_listed_finding_makes_no_crs_group_and_the_switch_off_keeps_it(monkeypatch):
    on(monkeypatch)
    assert crs_mapping.crs_groups([held_pass()]) == []
    on(monkeypatch, False)
    assert len(crs_mapping.crs_groups([held_pass()])) == 1


def test_the_sheet_lines_carry_the_status_and_the_value(monkeypatch):
    on(monkeypatch)
    lines = cl.sheet_rows([held_pass(), held_pass(contractor_evidence_text="")])
    assert len(lines) == 1
    assert lines[0][1] == "Design pressure" and lines[0][2] == "12 barg"
    assert lines[0][4] == "No issue found (draft rule)"


def _sheet_names(copy, monkeypatch):
    on(monkeypatch)
    monkeypatch.setattr(cl, "for_run", lambda run_id: cl.sheet_rows([held_pass()]))
    row = {
        "document_name": "D.pdf",
        "page_section": "p.2",
        "comment": "c",
        "comment_by": "AI Review",
        "standard_reference": "S 1.1",
        "row_kind": "datasheet_check",
        "engineer_confirmed": True,
    }
    data = crs_export.build_crs([row], {"review_run_id": "run-1", "copy": copy})
    return openpyxl.load_workbook(io.BytesIO(data)).sheetnames


def test_the_internal_copy_has_the_sheet_and_the_contractor_copy_never_does(
    monkeypatch,
):
    assert "Compliance list" in _sheet_names("internal", monkeypatch)
    assert "Compliance list" not in _sheet_names("issue", monkeypatch)
