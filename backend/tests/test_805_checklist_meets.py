"""#805 Stage A (planner 11 Oct): a met checklist item is stored as a
COMPLIANT finding, so "Meets" is visible like any result.

What must hold: every met checklist item becomes one COMPLIANT finding of the
run carrying its item id, the fact, the page and the standard clause; a DRAFT
checklist's finding is marked as such and the run trace counts it as
`draft_checklist`; a pass is never a CRS comment; a check that is not a
checklist item (a consistency pair, the revision block) still adds no row;
"does not apply" still adds no row. Generic: nothing here names an equipment
type beyond the fixture. Invented values only.
"""
from __future__ import annotations

import uuid

import pytest

from app import access, crs_mapping, datasheet_checks as dc, db, review_trace, submittal_review
from app.config import settings
from tests.test_746_relief_valve_checklist import PSV, SHEET

NOW = "2026-10-11T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "meets.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


@pytest.fixture
def run():
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES ('sub','psv.pdf','s',1,'x','ready',2,?)", (NOW,))
        run_id = str(uuid.uuid4())
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                     " VALUES (?,'sub','completed',?,?)", (run_id, NOW, NOW))
    return run_id


def _stored(run_id, status=None):
    sql = "SELECT * FROM review_findings WHERE review_run_id = ?"
    args = [run_id]
    if status:
        sql += " AND compliance_status = ?"
        args.append(status)
    return [dict(r) for r in db.connect().execute(sql, args)]


def _store(run_id, facts=SHEET):
    results = dc.evaluate(facts, equipment_type=PSV, page_texts={1: "Rev Date Description\nPrepared Checked Approved"})
    dc.store(run_id, "sub", results, pages_read={})
    return results


def test_every_met_checklist_item_is_stored_as_a_compliant_finding(run):
    results = _store(run)
    met = [r for r in results if r.get("checklist") and r["status"] == dc.COMPLIANT]
    assert met, "the fixture sheet meets some checklist items"
    stored = _stored(run, dc.COMPLIANT)
    assert len(stored) == len(met)
    by_rule = {f["requirement_source_text"].split(":")[0]: f for f in stored}
    f = by_rule["Datasheet check PSV-24"]          # set pressure 10 barg <= MAWP 12 barg
    assert f["origin"] == dc.ORIGIN and f["fact_id"] and f["contractor_page"] == 2
    assert f["standard_clause"] == "API 520-I 5.4.2.1"
    assert f["required_action"] == "None." and f["severity"] == "observation"


def test_a_draft_checklists_findings_are_marked_and_counted_in_the_trace(run):
    _store(run)
    stored = _stored(run, dc.COMPLIANT)
    assert stored and all(dc.is_draft_checklist(f["requirement"]) for f in stored)
    trace = review_trace.build(run, access.AccessScope(user_id=None, allowed_document_ids=frozenset({"sub"})))
    step = next(s for s in trace["steps"] if s["step"] == "CHECKLIST")
    drafts = sum(1 for f in _stored(run) if dc.is_draft_checklist(f["requirement"]))
    assert step["counts"]["draft_checklist"] == drafts
    assert step["counts"]["COMPLIANT"] == len(stored)
    assert "draft_checklist" in step["summary"]
    assert any(item.startswith("[draft_checklist] ") for item in step["items"])


def test_a_signed_checklist_is_not_marked_draft(run, monkeypatch):
    real = dc.checklist_for
    monkeypatch.setattr(dc, "checklist_for", lambda t, r: {**real(t, r), "draft": False})
    _store(run)
    stored = _stored(run, dc.COMPLIANT)
    assert stored and not any(dc.is_draft_checklist(f["requirement"]) for f in stored)


def test_a_pass_is_never_a_crs_comment(run):
    _store(run)
    findings = _stored(run)
    rows = crs_mapping.build_crs_rows(findings, [], "psv.pdf")
    met_ids = {f["id"] for f in findings if f["compliance_status"] == dc.COMPLIANT}
    assert met_ids and not ({r.get("finding_id") for r in rows} & met_ids)


def test_other_passes_and_does_not_apply_still_add_no_row(run):
    results = _store(run)
    revision = next(r for r in results if r["rule_id"] == "DS-R1")
    assert revision["status"] == dc.COMPLIANT          # a revision block was found ...
    stored_rules = {f["requirement_source_text"].split(":")[0] for f in _stored(run)}
    assert "Datasheet check DS-R1" not in stored_rules   # ... and is not a row
    not_applicable = {f"Datasheet check {r['rule_id']}" for r in results
                      if r["status"] == dc.NOT_APPLICABLE}
    assert not_applicable and not (not_applicable & stored_rules)
