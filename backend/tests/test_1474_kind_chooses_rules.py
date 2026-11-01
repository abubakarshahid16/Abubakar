"""#1474: the document KIND chooses the rule set. A procedure (or any non-datasheet
kind) never gets the equipment datasheet checklist nor equipment-type governing
standards; a datasheet is unchanged; an unknown kind is unchanged and marked; the
switch off changes nothing. Invented documents only."""

from __future__ import annotations

import json

import pytest

from app import applicability, comparison, db, kind_rules, submittal_review
from app.config import settings
from tests.test_754_required_vs_cited import _psv
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401
from tests.test_field_naming import _world


def _set_kind(doc_id, kind, state="suggested"):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_kinds (document_id, kind, state, routed_at)"
            " VALUES (?,?,?,?)",
            (doc_id, kind, state, "2026-11-01"),
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


def test_a_kind_never_adds_a_standard(on):
    result, std = _select("procedure")
    # every candidate offered is one the old path also offered
    assert {r["standard_document_id"] for r in result["selected"]} <= {std}


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


def test_the_run_records_the_equipment_type_as_not_used_only_for_a_non_datasheet(on):
    sub = _psv()
    _set_kind(sub, "procedure")
    cls, note = kind_rules.for_run(sub, {"equipment_type": "relief valve", "x": 1})
    assert cls == {"equipment_type": "relief valve", "x": 1}  # subject gates keep it
    assert note["equipment_type"] == (
        "equipment type 'relief valve' not used to choose the checklist or the "
        "standards: the document is a procedure"
    )
    _set_kind(sub, "datasheet")
    cls, note = kind_rules.for_run(sub, {"equipment_type": "relief valve"})
    assert cls == {"equipment_type": "relief valve"} and note is None


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
    assert outcome["datasheet_check_not_run"] == (
        "datasheet checklist not applied: the document is a procedure"
    )
    note = outcome["requirement_split"]["kind_rules"]
    assert note["blocked"] is True
    assert outcome["requirement_split"].get("checklist_coverage") is None
    assert "not used" in note["equipment_type"]


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
