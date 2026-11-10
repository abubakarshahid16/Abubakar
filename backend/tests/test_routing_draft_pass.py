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
    datasheets,
    db,
    deferred_value,
    degraded_read,
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


class Sheet:
    """The invented sheet the routing guards read: page texts, current facts, a failed AI reading."""

    def __init__(self):
        self.pages = {(DOC, 1): "Invented field 12 barg\nAnother field 30 degC"}
        self.facts: list[dict] = []
        self.failed_read = False


@pytest.fixture(autouse=True)
def sheet(monkeypatch):
    s = Sheet()
    monkeypatch.setattr(crs_routing, "_page_text", lambda d, p: s.pages.get((d, p)))
    monkeypatch.setattr(crs_routing, "_document_facts", lambda d: s.facts)
    monkeypatch.setattr(
        degraded_read, "relies_on_failed_read", lambda roles, d: s.failed_read
    )
    return s


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
        "document_id": DOC,
        # a real consistency pair of the reference data: design pressure against operating pressure
        "requirement_source_text": f"{dc.LABEL} DS-C1: invented text {n}",
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


def test_a_stored_draft_pass_moves_end_to_end(monkeypatch, sheet):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    stored = _store([_passed()], label=rule_trust.label_check)["T-1"]
    switch(monkeypatch, routing=True)
    assert not cl.is_listed(stored)  # T-1 is no rule of the reference data: kept
    monkeypatch.setattr(
        crs_routing, "_rule_roles", lambda i: frozenset({"body_material"})
    )
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


# ------------------------------------------------------------ the same page marks the figure deferred (owner, key row 33)


@pytest.mark.parametrize(
    "line, page, moves",
    [
        (
            "Other field 12 barg By Contractor / Vendor",
            1,
            False,
        ),  # (a) same figure, same dimension
        (
            "Other field 12 kg/m3 By Contractor",
            1,
            True,
        ),  # (b) same figure, another dimension
        ("Other field 12 barg By Contractor", 2, True),  # (c) marked on another page
        ("Other field 12 barg", 1, True),  # (d) the same figure, no mark
        ("Other field 13 barg TBA", 1, True),  # a marked line with another figure
        (
            "Other field 174 psig By Contractor",
            1,
            True,
        ),  # the same pressure in other units is not the figure
    ],
)
def test_a_figure_the_same_page_marks_deferred_keeps_the_draft_pass(
    monkeypatch, sheet, line, page, moves
):
    switch(monkeypatch, routing=True)
    sheet.pages[(DOC, page)] = sheet.pages.get((DOC, page), "") + "\n" + line
    assert cl.is_listed(draft_pass()) is moves


def test_an_unreadable_page_keeps_the_draft_pass(monkeypatch, sheet):
    switch(monkeypatch, routing=True)
    del sheet.pages[(DOC, 1)]  # (e)
    assert not cl.is_listed(draft_pass())
    sheet.pages[(DOC, 1)] = ""
    assert not cl.is_listed(draft_pass())


def test_a_value_with_no_figure_and_unit_is_not_compared(monkeypatch, sheet):
    switch(monkeypatch, routing=True)
    sheet.pages[(DOC, 1)] = "CF8M By Contractor"
    assert cl.is_listed(draft_pass(contractor_evidence_text="CF8M"))


def test_the_page_text_is_read_from_the_database(monkeypatch):
    monkeypatch.undo()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, needs_ocr, batch_no, equation_heavy)"
            " VALUES (?, 1, 'Invented 12 barg', 16, 0, 0, 0)",
            (DOC,),
        )
    assert crs_routing._page_text(DOC, 1) == "Invented 12 barg"
    assert (
        crs_routing._page_text(DOC, 2) is None
        and crs_routing._page_text(None, 1) is None
    )
    assert crs_routing._page_text(DOC, None) is None


# ------------------------------------------------------------ every value the rule reads (PR 1733 review)


def _kit_card(card_id):
    return next(c for k in kit_core._kits() for c in k.cards() if c["id"] == card_id)


def _calc_item():
    """A real checklist item of the reference data whose rule is a sizing calculation."""
    for entry in (dc.load_rules().get("checklists") or {}).values():
        for item in entry.get("items", []) if isinstance(entry, dict) else []:
            if (item.get("rule") or {}).get("formula") in degraded_read.FORMULA_INPUTS:
                return item
    raise AssertionError("no calculation item in the reference data")


def _noted(name, value, note, tag=None):
    return {
        **_fact(name, value, name.replace(" ", "-"), note=note),
        "equipment_tag": tag,
    }


def test_a_deferred_value_on_the_other_side_of_the_rule_keeps_the_row(
    monkeypatch, sheet
):
    switch(monkeypatch, routing=True)
    card = _kit_card("VSLD-05")  # design pressure >= 105 % of operating pressure
    f = draft_pass(requirement_source_text=f"{dc.LABEL} VSLD-05: {card['text']}")
    assert cl.is_listed(f)  # a clean kit pass still moves
    sheet.facts = [_noted("operating pressure", "11 barg", "By Contractor")]
    assert not cl.is_listed(f)
    sheet.facts = [_noted("operating pressure", "11 barg", "By Contractor", tag="P-2")]
    assert cl.is_listed(f)  # another tag's value is not the one this row read


def test_a_deferred_calculation_input_keeps_the_row(monkeypatch, sheet):
    switch(monkeypatch, routing=True)
    item = _calc_item()
    f = draft_pass(requirement_source_text=f"{dc.LABEL} {item['id']}: x")
    assert cl.is_listed(f)
    sheet.facts = [_noted("required capacity", "9000 kg/h", "TBA")]
    assert not cl.is_listed(f)


def test_a_failed_ai_reading_keeps_the_row_and_an_unknown_rule_stays(
    monkeypatch, sheet
):
    switch(monkeypatch, routing=True)
    f = draft_pass(requirement_source_text=f"{dc.LABEL} VSLD-05: x")
    assert cl.is_listed(f)
    sheet.failed_read = True
    assert not cl.is_listed(f)
    sheet.failed_read = False
    assert not cl.is_listed(
        draft_pass(requirement_source_text=f"{dc.LABEL} NO-SUCH-1: x")
    )
    assert not cl.is_listed(draft_pass(requirement_source_text="free text"))


def test_rule_roles_cover_both_sides_kit_cards_and_calculation_inputs():
    assert (
        crs_routing._rule_id({"requirement_source_text": f"{dc.LABEL} VSLD-05: a: b"})
        == "VSLD-05"
    )
    assert crs_routing._rule_id({"requirement_source_text": "Other VSLD-05: a"}) is None
    assert {"design_pressure", "operating_pressure"} <= crs_routing._rule_roles(
        "VSLD-05"
    )
    assert {"design_pressure", "operating_pressure"} <= crs_routing._rule_roles("DS-C1")
    assert "required_capacity" in crs_routing._rule_roles(_calc_item()["id"])
    assert (
        crs_routing._rule_roles("NO-SUCH-1") is None
        and crs_routing._rule_roles(None) is None
    )


def test_relies_on_failed_read_asks_the_reader_summary(monkeypatch):
    monkeypatch.undo()
    summaries = {}
    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda d: summaries.get(d))
    roles = frozenset({"operating_pressure"})
    assert not degraded_read.relies_on_failed_read(roles, DOC)
    summaries[DOC] = {
        "engine": "ollama",
        "rejected_fields": {"operating_pressure: model_timed_out": 1},
    }
    assert degraded_read.relies_on_failed_read(roles, DOC)
    assert not degraded_read.relies_on_failed_read(frozenset({"set_pressure"}), DOC)
    summaries[DOC] = {
        "engine": "ollama",
        "partly_read": {"2": "engine answer unusable"},
    }
    assert degraded_read.relies_on_failed_read(frozenset(), DOC)
    assert not degraded_read.relies_on_failed_read(roles, None)


# ------------------------------------------------------------ a kit pass gets the reason of the hold it would get


def _kit_pass(card_id="VSLD-05"):
    return kit_core.held(
        {
            "rule_id": card_id,
            "status": "COMPLIANT",
            "text": "x",
            "detail": "d",
            "checklist": True,
            "fact_id": "f-own",
            "equipment_tag": None,
            "role": "design_pressure",
        },
        {"kit": "vessel"},
    )


def test_a_kit_pass_resting_on_a_deferred_value_gets_deferred_marker(monkeypatch):
    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", True)
    assert (
        deferred_value._right_roles(dc.load_rules())["VSLD-05"] == "operating_pressure"
    )
    own = {
        "id": "f-own",
        "field_name": "design pressure",
        "field_value": "12 barg",
        "equipment_tag": None,
    }
    right = {
        "id": "f-r",
        "field_name": "operating pressure",
        "field_value": "11 barg",
        "value_note": "By Contractor",
        "equipment_tag": None,
    }
    out = deferred_value.hold_results(
        [_kit_pass()], [own, right], dc.load_rules(), frozenset()
    )
    assert out[0][hold_reason.KEY] == hold_reason.DEFERRED_MARKER
    assert (
        out[0]["status"] == "NEEDS_ENGINEER_REVIEW"
        and out[0]["detail"] == _kit_pass()["detail"]
    )
    clean = deferred_value.hold_results(
        [_kit_pass()], [own], dc.load_rules(), frozenset()
    )
    assert clean[0][hold_reason.KEY] == hold_reason.RULE_NOT_PROVEN


def test_a_kit_pass_on_a_failed_ai_reading_loses_rule_not_proven(monkeypatch):
    summary = {
        "engine": "ollama",
        "rejected_fields": {"operating_pressure: model_failed": 1},
    }
    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda d: summary)
    out = degraded_read.hold([_kit_pass()], DOC)
    assert (
        hold_reason.KEY not in out[0]
        and hold_reason.stored(out[0], out[0]["status"]) == hold_reason.OTHER
    )
    monkeypatch.setattr(datasheets, "latest_reader_summary", lambda d: None)
    assert (
        degraded_read.hold([_kit_pass()], DOC)[0][hold_reason.KEY]
        == hold_reason.RULE_NOT_PROVEN
    )


def test_label_check_keeps_the_code_of_an_earlier_hold(monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    deferred = {
        **_kit_pass(),
        hold_reason.KEY: hold_reason.DEFERRED_MARKER,
        "draft": True,
        "local": True,
    }
    assert (
        rule_trust.label_check(deferred)[hold_reason.KEY] == hold_reason.DEFERRED_MARKER
    )
    failed = {k: v for k, v in deferred.items() if k != hold_reason.KEY}
    assert hold_reason.KEY not in rule_trust.label_check(failed)


# ------------------------------------------------------------ every post-check step re-codes a kit pass (PR 1733 review)


def _vsld09(value="-3"):
    """An invented VSLD-09 (test pressure stated) kit pass on `value`, and that value's fact."""
    fact = {
        "id": "f-tp",
        "field_name": "test pressure",
        "field_label": "test pressure",
        "raw_value": value,
        "field_value": value,
        "page": 1,
        "equipment_tag": None,
    }
    kit = kit_core.held(
        {
            "rule_id": "VSLD-09",
            "status": "COMPLIANT",
            "text": "x",
            "detail": "d",
            "checklist": True,
            "fact_id": "f-tp",
            "equipment_tag": None,
            "role": "test_pressure",
        },
        {"kit": "vessel"},
    )
    return kit, fact


@pytest.mark.parametrize("value", ["-3", "PN-16"])
def test_an_impossible_value_kit_pass_loses_rule_not_proven(monkeypatch, value):
    from app import impossible_sign

    monkeypatch.setattr(settings, "deferred_value_is_query_enabled", False)
    kit, fact = _vsld09(value)
    assert "test_pressure" in impossible_sign._roles_read(dc.load_rules())["VSLD-09"]
    out = deferred_value.hold_results([kit], [fact], dc.load_rules(), frozenset())
    assert hold_reason.KEY not in out[0]
    assert hold_reason.stored(out[0], out[0]["status"]) == hold_reason.OTHER
    assert out[0]["status"] == kit["status"] and out[0]["detail"] == kit["detail"]
    clean_kit, clean = _vsld09("15 barg")
    same = deferred_value.hold_results(
        [clean_kit], [clean], dc.load_rules(), frozenset()
    )
    assert same[0][hold_reason.KEY] == hold_reason.RULE_NOT_PROVEN


@pytest.mark.parametrize("value", ["-3", "PN-16"])
def test_an_impossible_value_the_rule_reads_keeps_the_row(monkeypatch, sheet, value):
    """Routing on, re-checked from the stored facts: the row passes every check or it stays."""
    switch(monkeypatch, routing=True)
    f = draft_pass(
        requirement_source_text=f"{dc.LABEL} VSLD-09: x", contractor_evidence_text="15"
    )
    sheet.facts = [_vsld09("15 barg")[1]]
    assert cl.is_listed(f)
    sheet.facts = [_vsld09(value)[1]]
    assert not cl.is_listed(f)


def test_a_kit_pass_the_rulebook_contradicts_loses_rule_not_proven():
    from types import SimpleNamespace

    from app import rulebook_v2_review as v2

    kit, _fact = _vsld09("15 barg")
    row = SimpleNamespace(
        status="NON_COMPLIANT",
        rule_said=None,
        reason=None,
        fact_ids={"f-tp"},
        words="w",
    )
    out = v2.settle_with_checks(SimpleNamespace(rows=[row]), [kit])
    assert hold_reason.KEY not in out[0] and out[0]["detail"] == kit["detail"]
    assert row.status == "NON_COMPLIANT"  # the rulebook's own record is unchanged
    agree = SimpleNamespace(
        status="COMPLIANT", rule_said=None, reason=None, fact_ids={"f-tp"}, words="w"
    )
    same = v2.settle_with_checks(SimpleNamespace(rows=[agree]), [kit])
    assert same[0][hold_reason.KEY] == hold_reason.RULE_NOT_PROVEN
    other = SimpleNamespace(
        status="NON_COMPLIANT", rule_said=None, reason=None, fact_ids={"f-x"}, words="w"
    )
    assert v2.settle_with_checks(SimpleNamespace(rows=[other]), [kit])[0][
        hold_reason.KEY
    ] == (hold_reason.RULE_NOT_PROVEN)


# ------------------------------------------------------------ the routing re-check is as strong as the check (#1733 round 3)

#: Invented rules: one field name, two roles; only the second may not be negative, and only the type "Widget" wants it.
_TWO_ROLES = {
    "roles": {
        "a_role": {"kind": "x", "names": ["^thing$"]},
        "b_role": {"kind": "x", "names": ["^thing$"], "never_negative": True},
    },
    "mandatory": {"_generic": [], "Widget": ["b_role"]},
    "checklists": {},
    "consistency": [],
}


def _classify(equipment_type):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by, equipment_type)"
            " VALUES (?, 'none', ?)",
            (DOC, equipment_type),
        )


def test_the_routing_recheck_reads_a_field_as_the_role_the_check_read_it(
    monkeypatch, sheet
):
    """A name matching two roles is read as the one the equipment type wants, at check time and in routing."""
    from app import impossible_sign

    switch(monkeypatch, routing=True)
    monkeypatch.setattr(dc, "load_rules", lambda: _TWO_ROLES)
    monkeypatch.setattr(crs_routing, "_rule_roles", lambda i: frozenset({"b_role"}))
    negative = _fact("thing", "-3", 1)
    wanted = dc.datasheet_roles.wanted_roles("Widget", _TWO_ROLES)
    # the check holds it
    assert impossible_sign._impossible([negative], _TWO_ROLES, wanted)
    assert not impossible_sign._impossible([negative], _TWO_ROLES, frozenset())
    _classify("Widget")
    f = draft_pass()
    sheet.facts = [_fact("thing", "15", 1)]
    assert crs_routing.draft_pass_may_leave(f)
    sheet.facts = [negative]
    assert not crs_routing.draft_pass_may_leave(f)


def test_with_no_stored_type_an_impossible_looking_value_keeps_the_row(
    monkeypatch, sheet
):
    """The safe side: the type's roles cannot be found, so a negative value the rule reads keeps the row."""
    switch(monkeypatch, routing=True)
    monkeypatch.setattr(dc, "load_rules", lambda: _TWO_ROLES)
    monkeypatch.setattr(crs_routing, "_rule_roles", lambda i: frozenset({"b_role"}))
    f = draft_pass()
    sheet.facts = [_fact("thing", "15", 1)]
    assert crs_routing.draft_pass_may_leave(f)
    sheet.facts = [_fact("thing", "-3", 1)]
    assert not crs_routing.draft_pass_may_leave(f)


@pytest.mark.parametrize("value", ["-3", "PN-16"])
def test_an_impossible_value_in_the_findings_own_fact_keeps_the_row(monkeypatch, value):
    """The finding's own fact (current or superseded) is checked for an impossible value, as for a mark."""
    switch(monkeypatch, routing=True)
    _classify(None)
    own = {"f9": _fact("test pressure", "15 barg", 9)}
    monkeypatch.setattr(crs_routing, "_own_fact", lambda i: own.get(i))
    assert cl.is_listed(draft_pass(fact_id="f9"))
    own["f9"] = _fact("test pressure", value, 9)
    assert not cl.is_listed(draft_pass(fact_id="f9"))
