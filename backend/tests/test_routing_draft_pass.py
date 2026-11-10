"""A draft-rule pass held only because its rule is not proven stores the hold code `rule_not_proven`, and with
CRS_ROUTING_BY_HOLD_REASON_ENABLED on it goes to the internal "Compliance list" as "No issue found (draft rule)"
(owner 3 Nov 11:40 b), also with CRS_COMPLIANCE_LIST_ENABLED off (Part of #805 Cycle 2, owner 10 Nov).

Kept on the CRS whatever the switch: a "By Contractor" (deferred_marker) row, a value carrying a deferral phrase,
a finding an engineer confirmed or accepted, a safety tick, and any other hold code. Switch off: as main.
Invented values only; no model, no network."""

from __future__ import annotations

import io
import zipfile

import pytest

from app import compliance_list as cl
from app import (
    crs_export,
    crs_mapping,
    crs_routing,
    db,
    hold_reason,
    kit_core,
    review,
    rule_trust,
    submittal_review,
)
from app import datasheet_checks as dc
from app.config import settings

DOC = "doc-draft-pass"
RUN = "run-draft-pass"
COND = {"role": "test_condition", "any": ["yes"]}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "draft-pass.sqlite")
    monkeypatch.setattr(settings, "rule_auto_use_enabled", False)
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", False)
    monkeypatch.setattr(settings, "crs_routing_by_hold_reason_enabled", False)
    monkeypatch.setattr(settings, "crs_compliance_list_enabled", False)
    db.reset_connection()
    db.init_db()
    review.ensure_schema()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,?,?,1,?,'ready',1,'2026-11-10T00:00:00Z')",
            (DOC, "sheet.pdf", "sha-draft-pass", "sheet.pdf"),
        )
    yield
    db.reset_connection()


def switch(monkeypatch, routing=True, compliance=False):
    monkeypatch.setattr(settings, "crs_routing_by_hold_reason_enabled", routing)
    monkeypatch.setattr(settings, "crs_compliance_list_enabled", compliance)


def _fact(name, value, i, note=None):
    out = {
        "id": f"f{i}",
        "field_name": name,
        "field_label": name,
        "raw_value": value,
        "field_value": value,
        "raw_unit": None,
        "page": 2,
        "equipment_tag": None,
    }
    if note:
        out["value_note"] = note
    return out


def _item(item_id, condition=None):
    item = {
        "id": item_id,
        "text": "The body material is given",
        "rule": {"kind": "required", "field": "body_material"},
        "source": {"standard": "STD-1", "clause": "4.2"},
    }
    if condition:
        item["condition"] = condition
    return item


def _eval(item, roles, draft=True):
    return dc.evaluate_item(item, roles, {}, None, dc.load_rules(), draft=draft)


def _passed(item_id="T-1", draft=True):
    return _eval(
        _item(item_id), {"body_material": [_fact("body material", "CF8M", 1)]}, draft
    )


def _store(results, label=None) -> dict[str, dict]:
    dc.store(RUN, DOC, results, pages_read={2: "read"}, label=label)
    rows = (
        db.connect()
        .execute("SELECT * FROM review_findings WHERE review_run_id = ?", (RUN,))
        .fetchall()
    )
    return {
        dict(r)["requirement_source_text"].split(":")[0].split()[-1]: dict(r)
        for r in rows
    }


# ------------------------------------------------------------ the code is written where the hold is made


def test_label_check_holds_a_draft_pass_and_stores_rule_not_proven(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    out = rule_trust.label_check(_passed())
    assert out["status"] == "NEEDS_ENGINEER_REVIEW" and out["rule_said"] == "COMPLIANT"
    assert out[hold_reason.KEY] == hold_reason.RULE_NOT_PROVEN
    stored = _store([_passed()], label=rule_trust.label_check)["T-1"]
    assert stored[hold_reason.COLUMN] == hold_reason.RULE_NOT_PROVEN
    assert stored["rule_said"] == "COMPLIANT" and stored["trust_label"] == "UNPROVEN"


def test_label_check_keeps_another_hold_code_and_writes_none_on_a_decided_check(
    monkeypatch,
):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    applicability = rule_trust.label_check(_eval(_item("T-2", COND), {}))
    assert applicability[hold_reason.KEY] == hold_reason.APPLICABILITY_NOT_STATED
    signed = {**_passed("T-3", draft=False), "draft": False, "local": False}
    decided = rule_trust.label_check(signed)
    assert decided["status"] == "COMPLIANT" and hold_reason.KEY not in decided
    monkeypatch.setattr(settings, "rule_auto_use_enabled", False)
    assert hold_reason.KEY not in rule_trust.label_check(_passed())


def test_a_kit_card_held_by_kit_core_stores_rule_not_proven():
    out = kit_core.held(_passed("T-4"), {"kit": "invented"})
    assert out["status"] == "NEEDS_ENGINEER_REVIEW" and out["rule_said"] == "COMPLIANT"
    assert out[hold_reason.KEY] == hold_reason.RULE_NOT_PROVEN
    stored = _store([out])["T-4"]  # rule_auto_use off: the kit holds it on its own
    assert stored[hold_reason.COLUMN] == hold_reason.RULE_NOT_PROVEN
    assert hold_reason.KEY not in kit_core.held(_passed("T-5"), {})  # not a kit card


# ------------------------------------------------------------ the routing switch lists a draft pass


def draft_pass(n="1", **over):
    base = {
        "id": f"f-{n}",
        "origin": "datasheet_check",
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "rule_said": "COMPLIANT",
        "trust_label": "UNPROVEN",
        "hold_reason_code": hold_reason.RULE_NOT_PROVEN,
        "contractor_evidence_text": "12 barg",
        "contractor_page": 1,
        "contractor_section": f"Invented field {n}",
        "standard_clause": f"4.{n}",
        "standard_name": "INVENTED-STD 1",
        "requirement": f"Invented requirement {n}",
        "finding": f"Invented field {n} 12 barg (page 1) is stated.",
    }
    return {**base, **over}


def test_a_draft_pass_moves_with_routing_on_also_with_the_compliance_list_off(
    monkeypatch,
):
    f = draft_pass()
    switch(monkeypatch, routing=False)
    assert not cl.is_listed(f) and len(crs_mapping.crs_groups([f])) == 1
    switch(monkeypatch, routing=True, compliance=False)
    assert cl.is_listed(f) and crs_mapping.crs_groups([f]) == []
    assert cl.sheet_rows([f])[0][4] == cl.STATUS  # "No issue found (draft rule)"


def test_a_stored_draft_pass_moves_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    stored = _store([_passed()], label=rule_trust.label_check)["T-1"]
    switch(monkeypatch, routing=True)
    assert cl.is_listed(stored) and crs_mapping.crs_groups([stored]) == []


@pytest.mark.parametrize("compliance", [False, True])
def test_a_by_contractor_deferred_marker_row_with_a_pass_never_moves(
    monkeypatch, compliance
):
    switch(monkeypatch, routing=True, compliance=compliance)
    f = draft_pass(
        hold_reason_code=hold_reason.DEFERRED_MARKER, contractor_evidence_text="10 barg"
    )
    assert not cl.is_listed(f) and len(crs_mapping.crs_groups([f])) == 1


@pytest.mark.parametrize(
    "code", [hold_reason.OTHER, None, hold_reason.FIELD_SEVERAL_VALUES]
)
def test_a_draft_pass_held_for_another_reason_or_with_no_code_stays(monkeypatch, code):
    switch(monkeypatch, routing=True)
    assert not cl.is_listed(draft_pass(hold_reason_code=code))


def test_a_value_with_a_deferral_phrase_stays_on_the_crs(monkeypatch):
    """Owner 10 Nov: a figure followed by "By Contractor" is not a confirmed value, in the value read or its fact."""
    switch(monkeypatch, routing=True)
    assert not cl.is_listed(
        draft_pass(contractor_evidence_text="10 barg By Contractor")
    )
    noted = _fact("invented field", "10 barg", 7, note="By Contractor")
    monkeypatch.setattr(
        crs_routing, "_own_fact", lambda i: noted if i == "f7" else None
    )
    assert not cl.is_listed(draft_pass(fact_id="f7"))
    assert cl.is_listed(
        draft_pass(fact_id="f8")
    )  # no fact on record: the value read decides


def test_the_own_fact_is_read_from_the_database():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO submittal_facts (id, submittal_document_id, field_name, field_value, raw_value,"
            " value_note, page, created_at, updated_at) VALUES ('fx', ?, 'x', '10', '10', 'By Contractor', 2,"
            " '2026-11-10', '2026-11-10')",
            (DOC,),
        )
    assert crs_routing._own_fact("fx")["value_note"] == "By Contractor"
    assert (
        crs_routing._own_fact("missing") is None and crs_routing._own_fact(None) is None
    )


def test_a_finding_an_engineer_accepted_or_confirmed_never_moves(monkeypatch):
    switch(monkeypatch, routing=True)
    assert not cl.is_listed(draft_pass(approval_status="accepted", approved_by="eng-2"))
    assert not cl.is_listed(draft_pass(confirmed_by="eng-1"))


def test_a_safety_tick_row_is_not_changed(monkeypatch):
    switch(monkeypatch, routing=True)
    tick = draft_pass(
        compliance_status="COMPLIANT",
        rule_said=None,
        trust_label="TESTED_CARD",
        show_for_engineer_tick=True,
        hold_reason_code=None,
    )
    assert not cl.is_listed(tick) and len(crs_mapping.crs_groups([tick])) == 1
    assert not cl.is_listed(draft_pass(show_for_engineer_tick=True))


# ------------------------------------------------------------ switch off: main's workbook


def _main_draft_pass(finding: dict) -> bool:
    """`compliance_list._draft_pass` as main has it (ca7b3e1a), copied."""
    if (
        not settings.crs_compliance_list_enabled
        or finding.get("confirmed_by")
        or finding.get("approval_status") == "rejected"
    ):
        return False
    if finding.get("trust_label") in cl.PERSON_LABELS or not cl._value_given(finding):
        return False
    if finding.get("tier") == "SAFETY" or finding.get("show_for_engineer_tick"):
        return False
    return (
        finding.get("compliance_status") == "NEEDS_ENGINEER_REVIEW"
        and finding.get("rule_said") == "COMPLIANT"
        and finding.get("trust_label") == "UNPROVEN"
    )


def _findings():
    return [
        draft_pass("1"),
        draft_pass("2", hold_reason_code=hold_reason.DEFERRED_MARKER),
        draft_pass("3", contractor_evidence_text="10 barg By Contractor"),
        draft_pass("4", approval_status="accepted", approved_by="eng-2"),
        draft_pass("5", hold_reason_code=hold_reason.OTHER),
    ]


def _parts(findings, monkeypatch) -> dict:
    monkeypatch.setattr(cl, "_stored", lambda run_id: findings)
    rows = crs_mapping.build_crs_rows(findings, ["API 990"], "D.pdf")
    data = crs_export.build_crs(
        rows,
        {
            "review_run_id": "run-1",
            "copy": "internal",
            "review_notes": crs_mapping.build_review_notes(findings, ["API 990"]),
        },
    )
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist() if n != "docProps/core.xml"}


@pytest.mark.parametrize("compliance", [False, True])
def test_switch_off_the_workbook_is_main_s(monkeypatch, compliance):
    switch(monkeypatch, routing=False, compliance=compliance)
    off = _parts(_findings(), monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(cl, "_draft_pass", _main_draft_pass)
        assert off == _parts(_findings(), monkeypatch)
    switch(monkeypatch, routing=True, compliance=compliance)
    on = _parts(_findings(), monkeypatch)
    assert on != off  # not vacuous: the switch changes which rows the CRS shows
    moved = {f["id"] for f in _findings() if cl.is_listed(f)}
    assert moved == {"f-1"}  # only the plain draft pass; the guarded rows stay
