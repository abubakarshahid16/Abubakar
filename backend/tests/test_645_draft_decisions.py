"""#645 part 2 (planner 12 Oct): the engineer accepts or rejects a clause-check
draft. Accept is checked by code again and VERSIONED - a new confirmed numeric
limit, the sentence row superseded, not deleted - and the next review uses
it. Reject keeps the draft with the decision, and the same proposal for the
same words is not offered again. Access follows the standard's grant.

Invented clauses and a stub model only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import ai_requirements as air
from app import ai_task_runner, comparison, standards
from app.config import settings
from app.db import connect
from app.main import app
from tests.test_645_clause_checks import SENTENCE, proposal
from tests.test_w5_677_scope_ledger import _req, review_run, temp_storage  # noqa: F401 - fixtures


@pytest.fixture
def drafted(review_run, monkeypatch):  # noqa: F811
    """The review world with one undecided sentence and its draft."""
    run, ids, scope = review_run
    stmt = _req("spec", "sc", SENTENCE, requirement_type="statement")
    replies = [proposal()]

    def fake_run_task(spec, text, provider=None, use_cache=True):
        data = replies[0] if text == SENTENCE else {"has_limit": False}
        return ai_task_runner.TaskResult(spec.name, ai_task_runner.STATE_OK, data, None, "m")

    monkeypatch.setattr(settings, "ai_clause_checks_enabled", True)
    monkeypatch.setattr(air.ai_task_runner, "run_task", fake_run_task)
    comparison.run_comparison(run, allowed_document_ids=scope)
    draft = air.list_drafts(allowed_document_ids=scope)
    assert [d["requirement_id"] for d in draft] == [stmt]
    return {"run": run, "scope": scope, "stmt": stmt, "draft": draft[0], "replies": replies}


def _decide(draft_id, decision):
    return TestClient(app).post(f"/api/standards/clause-checks/{draft_id}/decision",
                                json={"decision": decision})


def _row(rid):
    return dict(connect().execute("SELECT * FROM standard_requirements WHERE id = ?",
                                  (rid,)).fetchone())


def test_the_drafts_are_listed_for_the_standards_the_caller_may_read(drafted):
    body = TestClient(app).get("/api/standards/clause-checks").json()
    assert [(d["id"], d["field"], d["value"], d["unit"], d["status"]) for d in body] == [
        (drafted["draft"]["id"], "cold differential test pressure", "12", "barg", "draft")]
    assert body[0]["source_text"] == SENTENCE and body[0]["clause"] == "5.1"
    # "not yours" is "not there"
    assert air.list_drafts(allowed_document_ids=frozenset({"nace"})) == []


def test_accept_writes_a_confirmed_limit_and_supersedes_the_sentence(drafted):
    out = _decide(drafted["draft"]["id"], "accept")
    assert out.status_code == 200, out.text
    new = _row(out.json()["new_requirement_id"])
    assert (new["requirement_type"], new["operator"], new["raw_value"], new["raw_unit"],
            new["field"], new["extraction_method"]) == (
        "numeric_limit", "<=", "12", "barg", "cold differential test pressure", "human")
    assert new["value"] is not None and new["unit"]           # normalised by the parser
    assert new["confirmed_at"] and new["superseded_at"] is None
    assert new["source_text"] == SENTENCE and new["chunk_id"] == "sc"
    # VERSIONED: the sentence row stays, superseded - never deleted
    old = _row(drafted["stmt"])
    assert old["superseded_at"] and old["requirement_type"] == "statement"
    decided = air.list_drafts(allowed_document_ids=drafted["scope"], status="accepted")
    assert decided[0]["new_requirement_id"] == new["id"]
    audit = connect().execute("SELECT action FROM audit_events WHERE action LIKE "
                              "'standard.clause_check%'").fetchall()
    assert [a["action"] for a in audit] == ["standard.clause_check_accepted"]
    # a decided draft is not decided twice
    assert _decide(drafted["draft"]["id"], "reject").status_code == 422


def test_the_next_review_uses_the_accepted_limit(drafted):
    new_id = _decide(drafted["draft"]["id"], "accept").json()["new_requirement_id"]
    comparison.run_comparison(drafted["run"], allowed_document_ids=drafted["scope"])
    cited = {r["requirement_id"] for r in connect().execute(
        "SELECT requirement_id FROM review_findings WHERE review_run_id = ?", (drafted["run"],))}
    assert new_id in cited and drafted["stmt"] not in cited


def test_code_checks_the_draft_again_at_accept(drafted):
    # a draft whose value no longer stands in its quote is refused, and nothing is written
    with connect() as conn:
        conn.execute("UPDATE clause_check_drafts SET value = '15' WHERE id = ?",
                     (drafted["draft"]["id"],))
    out = _decide(drafted["draft"]["id"], "accept")
    assert out.status_code == 422 and air.VALUE_NOT_IN_QUOTE in out.text
    assert _row(drafted["stmt"])["superseded_at"] is None
    assert connect().execute("SELECT COUNT(*) FROM standard_requirements WHERE "
                             "requirement_type = 'numeric_limit' AND raw_value = '15'").fetchone()[0] == 0


def test_a_reversed_operator_is_refused_at_accept(drafted, monkeypatch):
    # the parser's own tripwire, asked again at accept
    monkeypatch.setattr(air, "verify_proposal",
                        lambda p, s: ({**p, "operator": ">=", "condition": None}, None))
    out = _decide(drafted["draft"]["id"], "accept")
    assert out.status_code == 422 and "opposite way" in out.text


def test_reject_keeps_the_draft_and_the_same_words_are_not_proposed_again(drafted):
    out = _decide(drafted["draft"]["id"], "reject")
    assert out.status_code == 200 and out.json()["status"] == "rejected"
    assert _row(drafted["stmt"])["superseded_at"] is None       # the sentence is untouched
    comparison.run_comparison(drafted["run"], allowed_document_ids=drafted["scope"])
    rows = connect().execute("SELECT status FROM clause_check_drafts").fetchall()
    assert [r["status"] for r in rows] == ["rejected"]
    assert air.list_drafts(allowed_document_ids=drafted["scope"]) == []


def test_an_unknown_or_unreadable_draft_is_404(drafted):
    assert _decide("no-such-draft", "accept").status_code == 404
    with pytest.raises(air.DraftError):
        air.decide_draft(drafted["draft"]["id"], decision="accept",
                         allowed_document_ids=frozenset({"nace"}))
    assert _decide(drafted["draft"]["id"], "maybe").status_code == 422


def test_listing_writes_nothing(drafted):
    before = connect().execute("SELECT COUNT(*) FROM standard_requirements").fetchone()[0]
    TestClient(app).get("/api/standards/clause-checks?status=draft")
    assert connect().execute("SELECT COUNT(*) FROM standard_requirements").fetchone()[0] == before
    assert standards  # the module that owns the versioned rows


def test_listing_before_any_draft_exists_is_empty_not_an_error():  # noqa: F811 - temp_storage
    assert TestClient(app).get("/api/standards/clause-checks").json() == []
