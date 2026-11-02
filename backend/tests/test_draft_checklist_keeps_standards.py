"""Lock 2: while a checklist is a DRAFT it cannot decide, so it does not set its standards aside. With the
switch on, their requirements stay in scope and each carries its own trust label. Invented documents only."""
from __future__ import annotations

import copy

from tests.test_746_checklist_governs import _chunk, _review, temp_storage  # noqa: F401

from app import comparison, datasheet_checks, db, rule_trust, scope_ledger, standards
from app.config import settings

SWITCH = "draft_checklist_keeps_standards_enabled"
PSV = "Pressure Safety Valve"


def _on(monkeypatch):
    monkeypatch.setattr(settings, SWITCH, True)


def _signed(monkeypatch):
    rules = copy.deepcopy(datasheet_checks.load_rules())
    rules["checklists"][PSV]["sign_off"] = {"status": "signed", "by": "eng", "date": "2026-11-02"}
    monkeypatch.setattr(datasheet_checks, "load_rules", lambda *a, **k: rules)


def test_off_a_draft_checklist_still_sets_its_standards_aside():
    assert getattr(settings, SWITCH) is False
    _result, stored, ids = _review(PSV)
    assert stored[ids["cited_1"]]["reason_code"] == "covered_by_checklist"


def test_on_a_draft_checklist_leaves_its_standards_in_scope(monkeypatch):
    _on(monkeypatch)
    result, stored, ids = _review(PSV)
    assert not any(d["state"] == scope_ledger.NOT_USED for d in stored.values())
    assert stored[ids["cited_1"]]["reason_code"] in scope_ledger.STATUS_REASON.values()
    assert stored[ids["cell"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    split = result["requirement_split"]
    assert split["not_used"] == 0 and "checklist" not in split and split["total"] == 4


def test_on_a_signed_checklist_still_governs(monkeypatch):
    _on(monkeypatch)
    _signed(monkeypatch)
    _result, stored, ids = _review(PSV)
    assert stored[ids["cited_1"]]["state"] == scope_ledger.NOT_USED


def test_on_the_draft_items_are_still_there_and_still_cite_their_standards(monkeypatch):
    _on(monkeypatch)
    sources = datasheet_checks.checklist_sources(PSV, datasheet_checks.load_rules())
    assert sources["draft"] is True and sources["items"] > 0 and sources["standards"]


def _rows(run):
    with db.connect() as conn:
        rows = conn.execute("SELECT requirement_id, compliance_status, trust_label, rule_said"
                            " FROM review_findings WHERE review_run_id = ?", (run,)).fetchall()
    return {r["requirement_id"]: dict(r) for r in rows}


def _with_limit(monkeypatch, confirmed=False):
    """Adds to the cited standard a limit the sheet's value meets: what could become a verdict."""
    real = comparison.run_comparison
    made = {}

    def wrapped(run, **kwargs):
        text = "Set pressure shall not exceed 10 barg."
        made["id"] = standards.create_requirement(
            standard_document_id="cited", chunk_id=_chunk("lc", "cited"), clause="5.3", page=1,
            requirement_text=text, source_text=text,
            structured={"requirement_type": "numeric_limit", "operator": "<=", "field": "Set pressure",
                        "subject": "set pressure", "value": 10, "unit": "barg", "raw_value": "10", "raw_unit": "barg"})["id"]
        if confirmed:
            with db.connect() as conn:
                conn.execute("INSERT INTO users (id,email,display_name,password_hash,created_at)"
                             " VALUES ('eng','eng@example.invalid','Eng','x','2026-11-02')")
                conn.execute("UPDATE standard_requirements SET confirmed_by='eng' WHERE id=?", (made["id"],))
        made["run"] = run
        return real(run, **kwargs)

    monkeypatch.setattr(comparison, "run_comparison", wrapped)
    return made


def test_on_a_kept_unproven_rule_never_decides_even_with_labels_off(monkeypatch):
    _on(monkeypatch)
    assert settings.rule_auto_use_enabled is False
    made = _with_limit(monkeypatch)
    _review(PSV)
    row = _rows(made["run"])[made["id"]]
    assert (row["compliance_status"], row["rule_said"], row["trust_label"]) == (
        "NEEDS_ENGINEER_REVIEW", "COMPLIANT", rule_trust.UNPROVEN)


def test_on_a_kept_engineer_confirmed_rule_decides_under_its_own_label(monkeypatch):
    _on(monkeypatch)
    made = _with_limit(monkeypatch, confirmed=True)
    _review(PSV)
    row = _rows(made["run"])[made["id"]]
    assert (row["compliance_status"], row["trust_label"]) == ("COMPLIANT", rule_trust.ENGINEER_CONFIRMED)


def test_on_a_standard_the_checklist_does_not_cite_is_not_labelled_by_this_switch(monkeypatch):
    _on(monkeypatch)
    made = _with_limit(monkeypatch)
    _result, _stored, ids = _review(PSV)
    assert _rows(made["run"])[ids["other"]]["trust_label"] is None
