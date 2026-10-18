"""rule_trust wired into the review (#947, owner decision 14 Oct; switch
`rule_auto_use_enabled`, OFF by default).

OFF: nothing changes - no draft is used, no finding is labelled, the run's
stored outcome has no `rule_trust`, and a re-run writes what it wrote before.
ON: a clause sentence with an undecided AI draft is compared through that
draft in the sentence's own place; an UNPROVEN rule never decides (its
verdict is held for the engineer with `rule_said`); a PROVEN family's rule
keeps its verdict, and a SAFETY-tier "meets" is shown for the engineer's
tick - on the internal CRS only, gating issue until ticked. An engineer's
reject of a proven rule's finding drops the family's proof.

Invented standards, an invented sheet and a stub model only.

MUTATION PROOF (danger zone, CLAUDE.md rule 6): the entries in
`scripts/mutations/rule_trust_wiring.py` (M985-01..09) and
`pr985_rule_trust_wiring.py` (M985-10..20) each delete one of these and name the
test that fails.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app import access, ai_requirements as air, ai_task_runner, comparison, rule_trust
from app.config import settings
from app.db import connect
from app.main import app
from tests.test_645_clause_checks import SENTENCE, proposal
from tests.test_w5_677_scope_ledger import NOW, _req, review_run, temp_storage  # noqa: F401 - fixtures

SPEC, SUB = "spec", "sub"


@pytest.fixture
def world(review_run, monkeypatch):  # noqa: F811
    """The review world with one undecided sentence, its draft, and the
    code-extracted set-pressure limit the sheet meets (9 of 10 barg)."""
    run, ids, scope = review_run
    stmt = _req(SPEC, "sc", SENTENCE, requirement_type="statement")

    def fake_run_task(spec, text, provider=None, use_cache=True):
        data = proposal() if text == SENTENCE else {"has_limit": False}
        return ai_task_runner.TaskResult(spec.name, ai_task_runner.STATE_OK, data, None,
                                         settings.ai_task_model)

    monkeypatch.setattr(settings, "ai_clause_checks_enabled", True)
    monkeypatch.setattr(air.ai_task_runner, "run_task", fake_run_task)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    comparison.run_comparison(run, allowed_document_ids=scope)
    draft = air.list_drafts(allowed_document_ids=scope)
    assert [d["requirement_id"] for d in draft] == [stmt]
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    yield {"run": run, "scope": scope, "stmt": stmt, "limit": ids["compared"], "draft": draft[0]}
    app.dependency_overrides.clear()


def _client(scope) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(scope))
    return TestClient(app)


def _findings(run):
    return {r["requirement_id"]: dict(r) for r in connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND requirement_id IS NOT NULL",
        (run,))}


def _rerun(world, run=None):
    return comparison.run_comparison(run or world["run"], allowed_document_ids=world["scope"])


def _new_run(world) -> str:
    """A fresh review run of the same submittal against the same standards."""
    run = str(uuid.uuid4())
    with connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
                     "updated_at) VALUES (?,?,'pending',?,?)", (run, SUB, NOW, NOW))
        for std in (SPEC, "nace"):
            conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,"
                         "standard_document_id,selection_method,included,created_at)"
                         " VALUES (?,?,?,'rule',1,?)", (str(uuid.uuid4()), run, std, NOW))
    return run


def _prove(world, *, model=None):
    """A PROVEN proof for (spec, Pressure Safety Valve) under `model` - the
    run's task model by default, the model that compiled a draft otherwise."""
    key = rule_trust.family_key(SPEC, "Pressure Safety Valve")
    result = {"cases": 1, "correct": 1, "errors": [], "status": rule_trust.PROVEN}
    rule_trust.save_proof(key, result, model_id=model or settings.ai_task_model,
                          standard_revision=None)
    return key


def _ai_compiled(world):
    """The code-extracted limit, recorded as the model compiled it (the run's
    task model), never confirmed - the kind of rule a family proof covers."""
    with connect() as conn:
        conn.execute("UPDATE standard_requirements SET extraction_method = ? WHERE id = ?",
                     (rule_trust.AI_COMPILED_METHOD, world["limit"]))


# ------------------------------------------------------------------ switch off

def test_off_uses_no_draft_labels_nothing_and_stores_nothing_new(world):
    assert settings.rule_auto_use_enabled is False
    out = _rerun(world)
    rows = _findings(world["run"])
    # the sentence is compared as a sentence, not through its draft
    assert rows[world["stmt"]]["rule_said"] is None
    assert rows[world["limit"]]["compliance_status"] == "COMPLIANT"
    assert {r["trust_label"] for r in rows.values()} == {None}
    assert {r["show_for_engineer_tick"] for r in rows.values()} == {None}
    assert "rule_trust" not in out
    assert "rule_trust" not in comparison.run_outcome(world["run"], allowed_document_ids=world["scope"])
    assert air.auto_use_rules(SPEC, allowed_document_ids=world["scope"]) == {}


# ------------------------------------------------------------------- switch on

def test_on_an_unproven_rule_never_decides(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    out = _rerun(world)
    rows = _findings(world["run"])
    # the code-extracted limit: the sheet meets it, but no family is proven
    held = rows[world["limit"]]
    assert (held["compliance_status"], held["rule_said"], held["trust_label"]) == (
        "NEEDS_ENGINEER_REVIEW", "COMPLIANT", rule_trust.UNPROVEN)
    assert rule_trust.UNPROVEN_REASON in held["ai_rationale"]
    assert held["tier"] == rule_trust.SAFETY            # set pressure is a safety field
    assert held["show_for_engineer_tick"] == 0           # not compliant any more, so no tick
    # the sentence is now compared THROUGH its draft, in its own place (same id)
    through = rows[world["stmt"]]
    assert through["trust_label"] == rule_trust.UNPROVEN
    assert through["requirement_id"] == world["stmt"]
    # the sheet has no cold differential test pressure: missing, never "meets"
    assert through["compliance_status"] == "MISSING_INFORMATION"
    assert set(out["rule_trust"]["labels"]) == {rule_trust.UNPROVEN}
    assert out["rule_trust"]["labels"][rule_trust.UNPROVEN] >= 2
    # EVERY held verdict of the run, the datasheet checks included - never the
    # rule loop's share alone (s2's real-group run: 51 reported, 1,555 held).
    every = [dict(r) for r in connect().execute(
        "SELECT rule_said, origin FROM review_findings WHERE review_run_id = ?", (world["run"],))]
    held_all = [r for r in every if r["rule_said"]]
    assert out["rule_trust"]["held_unproven"] == len(held_all)
    assert len(held_all) > 1 and any(r["origin"] == "datasheet_check" for r in held_all)
    assert out["rule_trust"]["findings_counted"] == len(every)
    # the scope ledger still ends every requirement in exactly one state
    # (`scope_ledger.check_complete` raises otherwise) and the run completed
    assert out["scope"]["in_scope"] >= 5


def test_a_proof_covers_ai_compiled_rules_only(world, monkeypatch):
    """Planner answer on #985: AI-compiled = by proof; every other rule that is
    not engineer-approved needs an engineer. A proven family does not lift
    the code-extracted limit."""
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    _prove(world)
    _rerun(world)
    rows = _findings(world["run"])
    held = rows[world["limit"]]
    assert (held["compliance_status"], held["rule_said"], held["trust_label"]) == (
        "NEEDS_ENGINEER_REVIEW", "COMPLIANT", rule_trust.UNPROVEN)
    assert rows[world["stmt"]]["trust_label"] == rule_trust.AUTO_PROVEN


def test_on_a_proven_family_keeps_the_verdict_and_flags_a_safety_meets_for_a_tick(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    _prove(world)
    _ai_compiled(world)
    out = _rerun(world)
    rows = _findings(world["run"])
    kept = rows[world["limit"]]
    assert (kept["compliance_status"], kept["rule_said"], kept["trust_label"]) == (
        "COMPLIANT", None, rule_trust.AUTO_PROVEN)
    assert (kept["tier"], kept["show_for_engineer_tick"]) == (rule_trust.SAFETY, 1)
    # the draft's rule: same family, compiled by the proof's model, passes
    # code's second check
    assert rows[world["stmt"]]["trust_label"] == rule_trust.AUTO_PROVEN
    trust = out["rule_trust"]
    assert trust["auto_proven"] == 2 and trust["safety_ticks"] == 1
    # step 10: at least one automatic finding is drawn for the spot-check
    assert len(trust["audit_sample"]) == 1 and trust["audit_sample"][0] in {r["id"] for r in rows.values()}
    # step 7: the field no rule targets is listed, the one a rule checks is not
    assert trust["uncovered_fields"] == ["H2S service"] and trust["fields_read"] == 2
    assert comparison.run_outcome(world["run"], allowed_document_ids=world["scope"])["rule_trust"] == trust
    # THE PROOF IS PER COMPILING MODEL: a draft another model compiled is not
    # covered by this family's proof
    with connect() as conn:
        conn.execute("UPDATE clause_check_drafts SET model = 'another-model'")
    _rerun(world)
    assert _findings(world["run"])[world["stmt"]]["trust_label"] == rule_trust.UNPROVEN


def test_an_engineer_confirmed_rule_needs_no_proof(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    with connect() as conn:
        conn.execute("INSERT INTO users (id, email, display_name, password_hash, created_at)"
                     " VALUES ('eng', 'eng@example.invalid', 'Eng', 'x', ?)", (NOW,))
        conn.execute("UPDATE standard_requirements SET confirmed_by = 'eng' WHERE id = ?",
                     (world["limit"],))
    _rerun(world)
    kept = _findings(world["run"])[world["limit"]]
    assert (kept["compliance_status"], kept["trust_label"]) == ("COMPLIANT", rule_trust.ENGINEER_CONFIRMED)


def test_a_proof_under_another_model_or_revision_does_not_count(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    _ai_compiled(world)     # a code-extracted rule is UNPROVEN whatever the proof
    key = rule_trust.family_key(SPEC, "Pressure Safety Valve")
    rule_trust.save_proof(key, {"cases": 1, "correct": 1, "errors": [], "status": rule_trust.PROVEN},
                          model_id="some-other-model", standard_revision=None)
    _rerun(world)
    assert _findings(world["run"])[world["limit"]]["trust_label"] == rule_trust.UNPROVEN
    _prove(world)
    _rerun(world)
    assert _findings(world["run"])[world["limit"]]["trust_label"] == rule_trust.AUTO_PROVEN
    with connect() as conn:
        conn.execute("UPDATE document_classification SET revision = 'Rev B' WHERE document_id = ?",
                     (SPEC,))
    _rerun(world)
    assert _findings(world["run"])[world["limit"]]["trust_label"] == rule_trust.UNPROVEN


def test_a_draft_code_refuses_again_is_not_used(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    with connect() as conn:
        conn.execute("UPDATE clause_check_drafts SET value = '15' WHERE id = ?", (world["draft"]["id"],))
    assert air.auto_use_rules(SPEC, allowed_document_ids=world["scope"]) == {}
    _rerun(world)
    assert _findings(world["run"])[world["stmt"]]["rule_said"] is None


# --------------------------------------------------------------------- the CRS

def test_the_internal_crs_shows_the_trust_and_the_safety_tick_and_the_issue_copy_does_not(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    _prove(world)
    _ai_compiled(world)
    _rerun(world)
    client = _client(world["scope"])
    internal = client.get(f"/api/reviews/runs/{world['run']}/crs/preview").json()
    assert "Rule trust (internal)" in internal["columns"]
    ticks = [r for r in internal["rows"] if r["row_kind"] == "safety_tick"]
    assert len(ticks) == 1
    assert "ENGINEER TO TICK (safety field)" in ticks[0]["comment"]
    assert "9 barg" in ticks[0]["comment"] and "meets the standard" in ticks[0]["comment"]
    assert ticks[0]["page_section"].startswith("p.1")
    issue = client.get(f"/api/reviews/runs/{world['run']}/crs/preview?copy=issue").json()
    assert "Rule trust (internal)" not in issue["columns"]
    assert [r for r in issue["rows"] if r["row_kind"] == "safety_tick"] == []
    # step 7 on the Review notes: the field no rule checked, with its denominator
    notes = {n["note"]: n for n in internal["review_notes"]}
    assert notes["Not checked by any rule"]["count"] == 1
    assert "1 of 2 datasheet fields" in notes["Not checked by any rule"]["detail"]
    assert "H2S service" in notes["Not checked by any rule"]["detail"]
    assert notes["Spot-check automatic findings"]["count"] == 1


def test_the_safety_tick_gates_issue_until_ticked_and_a_tick_is_a_correct_audit(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    key = _prove(world)
    _ai_compiled(world)
    _rerun(world)
    client = _client(world["scope"])
    run = world["run"]
    gate = client.get(f"/api/reviews/runs/{run}/crs/issue-gate").json()
    fid = _findings(run)[world["limit"]]["id"]
    assert fid in {f["finding_id"] for f in gate["open_findings"]}
    assert any(f["row_kind"] == "safety_tick" for f in gate["open_findings"])
    tick = client.post(f"/api/reviews/runs/{run}/crs/open-items/findings/{fid}/decision",
                       json={"decision": "accept", "reason": "read the set pressure on the page: 9 barg"})
    assert tick.status_code == 200, tick.text
    gate = client.get(f"/api/reviews/runs/{run}/crs/issue-gate").json()
    assert fid not in {f["finding_id"] for f in gate["open_findings"]}
    audit = connect().execute("SELECT outcome, engineer FROM rule_audit_outcome WHERE finding_id = ?",
                              (fid,)).fetchone()
    assert (audit["outcome"], audit["engineer"]) == (rule_trust.AUDIT_CORRECT, "eng")
    proof = rule_trust.load_proof(key, model_id=settings.ai_task_model, standard_revision=None)
    assert proof["status"] == rule_trust.PROVEN
    # ticked: still never a comment to the contractor
    issue = client.get(f"/api/reviews/runs/{run}/crs/preview?copy=issue").json()
    assert [r for r in issue["rows"] if r["row_kind"] == "safety_tick"] == []


def test_something_is_off_drops_the_familys_proof(world, monkeypatch):
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    key = _prove(world)
    _ai_compiled(world)
    _rerun(world)
    client = _client(world["scope"])
    run = world["run"]
    fid = _findings(run)[world["limit"]]["id"]
    off = client.post(f"/api/reviews/runs/{run}/crs/open-items/findings/{fid}/decision",
                      json={"decision": "reject", "reason": "the page says 9 barg at 20 C, not at relief"})
    assert off.status_code == 200, off.text
    proof = rule_trust.load_proof(key, model_id=settings.ai_task_model, standard_revision=None)
    assert proof["status"] == rule_trust.INVALID and fid in proof["invalid_reason"]
    # the next review (a new run) is held for the engineer again
    fresh = _new_run(world)
    _rerun(world, fresh)
    assert _findings(fresh)[world["limit"]]["trust_label"] == rule_trust.UNPROVEN


def test_a_decision_on_an_unlabelled_finding_records_no_audit(world):
    _rerun(world)
    client = _client(world["scope"])
    fid = _findings(world["run"])[world["limit"]]["id"]
    client.post(f"/api/reviews/runs/{world['run']}/crs/open-items/findings/{fid}/decision",
                json={"decision": "accept", "reason": "checked by eye on the page"})
    assert connect().execute("SELECT COUNT(*) FROM rule_audit_outcome").fetchone()[0] == 0


# ------------------------------------------------- the datasheet checks too

def _checks(run):
    return [dict(r) for r in connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = 'datasheet_check'",
        (run,))]


def test_every_datasheet_check_is_labelled_too(world, monkeypatch):
    """Planner answer on #985: label every rule. The PSV checklist is a draft
    (not signed off), so with the switch on none of its items decides: a pass
    is held for the engineer and still reaches the CRS as a row."""
    _rerun(world)
    off = _checks(world["run"])
    assert off and {r["trust_label"] for r in off} == {None}
    assert {r["show_for_engineer_tick"] for r in off} == {None}
    decided = [r for r in off if r["compliance_status"] in ("COMPLIANT", "NON_COMPLIANT")]
    assert decided, "the invented sheet must give the checklist something to decide"
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    _rerun(world)
    on = _checks(world["run"])
    assert {r["trust_label"] for r in on} == {rule_trust.UNPROVEN}
    assert not [r for r in on if r["compliance_status"] in ("COMPLIANT", "NON_COMPLIANT")]
    held = [r for r in on if r["rule_said"]]
    assert len(held) == len(decided)
    assert all(rule_trust.UNPROVEN_REASON in r["finding"] for r in held)
    # a held check is still a CRS row (a held PASS was never one before)
    rows = _client(world["scope"]).get(f"/api/reviews/runs/{world['run']}/crs/preview").json()["rows"]
    shown = [r for r in rows if r["row_kind"] == "datasheet_check"
             and rule_trust.UNPROVEN_REASON in r["comment"]]
    assert shown and {r["rule_trust"] for r in shown} == {"automatic rule not yet proven"}
    assert all(any(f["contractor_section"] in r["page_section"] for r in shown) for f in held)


def test_a_signed_checklist_item_is_an_engineers_rule(world, monkeypatch):
    from app import datasheet_checks
    rules = datasheet_checks.load_rules()
    rules["checklists"]["Pressure Safety Valve"]["sign_off"] = {"status": "signed", "by": "eng",
                                                                "date": "2026-10-16"}
    monkeypatch.setattr(datasheet_checks, "load_rules", lambda *a, **k: rules)
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    _rerun(world)
    items = [r for r in _checks(world["run"]) if "DRAFT checklist" not in r["requirement"]]
    signed = [r for r in items if r["standard_clause"]]     # a checklist item cites its clause
    assert signed and {r["trust_label"] for r in signed} == {rule_trust.ENGINEER_CONFIRMED}
    assert not [r for r in signed if r["rule_said"]]
