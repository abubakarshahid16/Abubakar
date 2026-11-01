"""#1474: the document KIND chooses the rule set. A procedure (or any non-datasheet
kind) never gets the equipment datasheet checklist nor equipment-type governing
standards; a datasheet is unchanged; an unknown kind is unchanged and marked; the
switch off changes nothing. Invented documents only."""

from __future__ import annotations

import json

import pytest

from app import absence, applicability, comparison, db, kind_rules, submittal_review
from app.config import settings
from tests.test_754_required_vs_cited import _psv
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401
from tests.test_field_naming import _world


def _set_kind(doc_id, kind, state="suggested", guess=False):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_kinds"
            " (document_id, kind, state, evidence, routed_at) VALUES (?,?,?,?,?)",
            (doc_id, kind, state, json.dumps({"guess": guess}), "2026-11-01"),
        )


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "kind_chooses_rules_enabled", True)


def _select(kind=None, state="suggested"):
    std = _doc(
        "std_520", "API-520-I.pdf", "COMPANY_STANDARD", document_number="API 520 Part I"
    )
    sub = _psv()
    if kind:
        _set_kind(sub, kind, state)
    return applicability.select(
        sub, allowed_document_ids=_scope(std, sub), persist=False
    ), std


def _included(result):
    return {r["standard_document_id"] for r in result["selected"] if r["included"]}


def test_a_procedure_gets_no_equipment_type_governing_standard(on):
    result, std = _select("procedure")
    assert std not in _included(result)
    assert result["governing_not_held"] == []
    excl = {
        e["standard_document_id"]: e for e in result["standards_check"]["kind_excluded"]
    }
    assert excl[std]["reason"] == (
        "chosen for an equipment type; the document is a procedure"
    )
    assert result["standards_check"]["required"] == []


def test_a_confirmed_specification_is_blocked_too(on):
    result, std = _select("specification", "confirmed")
    assert std not in _included(result)


def test_a_datasheet_keeps_the_governing_standard(on):
    result, std = _select("datasheet")
    assert std in _included(result)
    assert (
        "kind_excluded" not in result["standards_check"]
        and "kind_note" not in result["standards_check"]
    )


def test_an_unknown_kind_is_unchanged_and_marked(on):
    result, std = _select("unknown", "needs_engineer")
    assert std in _included(result)
    assert "equipment rules still apply" in result["standards_check"]["kind_note"]


def test_an_unrouted_document_is_unchanged_and_marked(on):
    result, std = _select(None)
    assert std in _included(result)
    assert "not routed" in result["standards_check"]["kind_note"]


def test_switch_off_changes_nothing():
    result, std = _select("procedure")
    assert std in _included(result)
    assert (
        "kind_excluded" not in result["standards_check"]
        and "kind_note" not in result["standards_check"]
    )


def test_a_kind_never_adds_a_standard(on, monkeypatch):
    docs = [
        _doc(
            "std_520",
            "API-520-I.pdf",
            "COMPANY_STANDARD",
            document_number="API 520 Part I",
        ),
        _doc(
            "std_cls",
            "Relief-Code.pdf",
            "COMPANY_STANDARD",
            document_number="ZZ 999",
            equipment_type="relief valve",
        ),
        _doc(
            "std_cited", "ISO-9999.pdf", "COMPANY_STANDARD", document_number="ISO 9999"
        ),
        _doc("std_other", "Other.pdf", "COMPANY_STANDARD", document_number="QQ 1"),
    ]
    sub = _psv(text="Sizing per ISO 9999. Set pressure 340 psig.")
    scope = _scope(sub, *docs)
    monkeypatch.setattr(settings, "kind_chooses_rules_enabled", False)
    old = {
        r["standard_document_id"]
        for r in applicability.select(sub, allowed_document_ids=scope, persist=False)[
            "selected"
        ]
    }
    monkeypatch.setattr(settings, "kind_chooses_rules_enabled", True)
    _set_kind(sub, "procedure")
    new = {
        r["standard_document_id"]
        for r in applicability.select(sub, allowed_document_ids=scope, persist=False)[
            "selected"
        ]
    }
    assert {"std_520", "std_cls", "std_cited"} <= old
    assert new <= old and "std_cited" in new and not {"std_520", "std_cls"} & new


def test_a_standard_classified_for_the_equipment_type_is_dropped_for_a_procedure(on):
    std = _doc(
        "std_cls",
        "Some-Relief-Code.pdf",
        "COMPANY_STANDARD",
        document_number="ZZ 999",
        equipment_type="relief valve",
    )
    sub = _psv()
    _set_kind(sub, "procedure")
    result = applicability.select(
        sub, allowed_document_ids=_scope(std, sub), persist=False
    )
    assert std not in _included(result)
    assert [
        e["standard_document_id"] for e in result["standards_check"]["kind_excluded"]
    ] == [std]


def test_the_run_note_names_the_unused_standards_and_the_equipment_type(on):
    std = _doc(
        "std_520", "API-520-I.pdf", "COMPANY_STANDARD", document_number="API 520 Part I"
    )
    sub = _psv()
    _set_kind(sub, "procedure", "confirmed")
    scope = _scope(std, sub)
    note = kind_rules.for_run(sub, scope, [])
    assert note["checklist"] == (
        "Datasheet checklist not applied: the document is a procedure (confirmed)."
    )
    assert note["standards"] == (
        "1 standard(s) chosen for an equipment type were not used: API 520 Part I, "
        "because the document is a procedure."
    )
    assert "still decides which requirements apply by subject" in note["equipment_type"]
    assert kind_rules.for_run(sub, scope, [std])["standards"] is None  # applied anyway
    _set_kind(sub, "datasheet")
    assert kind_rules.for_run(sub, scope, []) is None


def test_a_guessed_kind_keeps_the_datasheet_rules_and_says_so(on):
    std = _doc(
        "std_520", "API-520-I.pdf", "COMPANY_STANDARD", document_number="API 520 Part I"
    )
    sub = _psv()
    scope = _scope(std, sub)
    _set_kind(sub, "contract", "suggested", guess=True)
    assert kind_rules.blocked(sub) is None
    assert std in _included(
        applicability.select(sub, allowed_document_ids=scope, persist=False)
    )
    assert (
        kind_rules.unknown_mark(sub) == "document kind is a guess; datasheet rules kept"
    )
    _set_kind(sub, "contract", "confirmed", guess=True)  # a person confirmed it
    assert kind_rules.blocked(sub) is not None


def test_kind_rules_helper_words():
    assert kind_rules.blocked(None) is None
    assert kind_rules.checklist_not_applied("nope") is None


# ---- the review run -------------------------------------------------------

PSV_TYPE = "Pressure Safety Valve"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "kind_rules.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _review(kind, state="suggested"):
    _req, _fact, run, scope = _world("Set pressure", "10 barg")
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = ? WHERE document_id = 'sub-1'",
            (PSV_TYPE,),
        )
    if kind:
        _set_kind("sub-1", kind, state)
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    run_row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run,))
        .fetchone()
    )
    outcome = json.loads(run_row["outcome_json"])
    checklist_rows = [
        f for f in result["findings"] if "PSV-" in str(f.get("requirement_source_text"))
    ]
    return checklist_rows, outcome


def test_a_procedure_review_runs_no_checklist_and_says_so(world, on):
    rows, outcome = _review("procedure")
    assert rows == []
    assert "not applied" not in str(outcome["datasheet_check_not_run"])
    note = outcome["requirement_split"]["kind_rules"]
    assert note["blocked"] is True
    assert outcome["requirement_split"].get("checklist_coverage") is None
    assert note["checklist"].startswith("Datasheet checklist not applied:")
    lines = [
        p["line"]
        for p in absence.unchecked_parts(run_status="completed", outcome=outcome)
    ]
    assert note["checklist"] in lines
    assert not any("could not be checked: datasheet checklist" in x for x in lines)
    kind_only = [
        p
        for p in absence.unchecked_parts(run_status="completed", outcome=outcome)
        if p["part"] == "document_kind"
    ]
    assert len(kind_only) == 2 and absence.notice_for(kind_only) == ""


def test_the_crs_review_notes_carry_the_kind_line_on_the_internal_copy(world, on):
    from app import access, main

    _req, _fact, run, scope = _world("Set pressure", "10 barg")
    _set_kind("sub-1", "procedure", "confirmed")
    comparison.run_comparison(run, allowed_document_ids=scope)
    who = access.AccessScope(user_id="eng-1", allowed_document_ids=scope)
    _rows, meta, *_ = main._crs_content(run, who, "internal")
    notes = {n["detail"]: n["note"] for n in meta["review_notes"]}
    line = "Datasheet checklist not applied: the document is a procedure (confirmed)."
    assert notes[line] == "Document kind"
    assert any("subject" in d for d in notes)
    assert line in meta["unchecked_parts"]


def test_a_datasheet_review_still_runs_the_checklist(world, on):
    rows, outcome = _review("datasheet")
    assert rows, "the PSV checklist still runs for a datasheet"
    assert "kind_rules" not in outcome["requirement_split"]


def test_an_unknown_kind_review_still_runs_the_checklist_and_is_marked(world, on):
    rows, outcome = _review("unknown", "needs_engineer")
    assert rows
    assert outcome["requirement_split"]["kind_rules"]["blocked"] is False
    assert (
        "document kind not decided"
        in outcome["requirement_split"]["kind_rules"]["mark"]
    )


def test_switch_off_review_is_unchanged(world):
    rows, outcome = _review("procedure")
    assert rows
    assert "kind_rules" not in outcome["requirement_split"]
