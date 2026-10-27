"""#645/#833 general-path step 1 (planner 13 Oct): "standards -> checklist, by
AI, once" - compile ONE standard's open clause sentences into proposed
numeric checks, independent of any review run. `compile_standard` only widens
what feeds `propose_checks` (#645 part 1): the model call, the per-part
verification and the draft storage are unchanged and already tested in
`test_645_clause_checks.py` / `test_645_draft_decisions.py`. This file tests
only the new selection: one standard, not one review's undecided list; no
review_run_id required; a standard the caller may not read, or a sentence
already superseded by an accepted draft, is never asked about.

Invented clauses and a stub model only.
"""
from __future__ import annotations

from app import ai_requirements as air
from app import ai_task_runner
from app.db import connect
from tests.test_645_clause_checks import SENTENCE, proposal
from tests.test_w5_677_scope_ledger import (  # noqa: F401
    _chunk,
    _doc,
    _req,
    temp_storage,
)


def _fake_run_task(reply):
    def run_task(spec, text, provider=None, use_cache=True):
        data = reply if text == SENTENCE else {"has_limit": False}
        return ai_task_runner.TaskResult(spec.name, ai_task_runner.STATE_OK, data, None, "m")
    return run_task


def _standard_with_statement(std_id, chunk_id, text=SENTENCE):
    _doc(std_id, f"{std_id}.pdf", "COMPANY_STANDARD")
    _chunk(chunk_id, std_id, text)
    return _req(std_id, chunk_id, text, requirement_type="statement")


def test_compile_standard_reads_only_that_standards_own_open_statements(monkeypatch):
    other_stmt = "Bolting shall be ASTM A193 Grade B7."
    want = _standard_with_statement("spec", "sc")
    _standard_with_statement("other", "oc", other_stmt)
    monkeypatch.setattr(air.ai_task_runner, "run_task", _fake_run_task(proposal()))

    report = air.compile_standard("spec", allowed_document_ids=frozenset({"spec", "other"}), limit=50)

    assert report["sentences"] == 1 and report["proposed"] == 1
    assert report["standard_document_id"] == "spec"
    drafts = air.list_drafts(allowed_document_ids=frozenset({"spec", "other"}))
    assert [d["requirement_id"] for d in drafts] == [want]


def test_a_standard_the_caller_may_not_read_yields_nothing(monkeypatch):
    _standard_with_statement("spec", "sc")
    monkeypatch.setattr(air.ai_task_runner, "run_task", _fake_run_task(proposal()))

    report = air.compile_standard("spec", allowed_document_ids=frozenset({"other"}), limit=50)

    assert report == {"sentences": 0, "asked": 0, "proposed": 0, "no_limit": 0, "refused": {},
                      "could_not_read": 0, "not_asked_budget": 0, "model": None,
                      "by_standard": {}, "standard_document_id": "spec"}
    assert air.list_drafts(allowed_document_ids=frozenset({"spec"})) == []


def test_no_review_run_is_needed_and_none_is_recorded_on_the_draft(monkeypatch):
    _standard_with_statement("spec", "sc")
    monkeypatch.setattr(air.ai_task_runner, "run_task", _fake_run_task(proposal()))

    air.compile_standard("spec", allowed_document_ids=frozenset({"spec"}), limit=50)

    row = connect().execute("SELECT review_run_id FROM clause_check_drafts").fetchone()
    assert row["review_run_id"] is None


def test_compiling_twice_does_not_duplicate_the_draft(monkeypatch):
    _standard_with_statement("spec", "sc")
    monkeypatch.setattr(air.ai_task_runner, "run_task", _fake_run_task(proposal()))

    air.compile_standard("spec", allowed_document_ids=frozenset({"spec"}), limit=50)
    air.compile_standard("spec", allowed_document_ids=frozenset({"spec"}), limit=50)

    count = connect().execute("SELECT COUNT(*) FROM clause_check_drafts").fetchone()[0]
    assert count == 1


def test_a_sentence_an_accepted_draft_superseded_is_not_offered_by_a_later_compile(monkeypatch):
    stmt = _standard_with_statement("spec", "sc")
    monkeypatch.setattr(air.ai_task_runner, "run_task", _fake_run_task(proposal()))
    air.compile_standard("spec", allowed_document_ids=frozenset({"spec"}), limit=50)
    draft = air.list_drafts(allowed_document_ids=frozenset({"spec"}))[0]

    decided = air.decide_draft(draft["id"], decision="accept", allowed_document_ids=frozenset({"spec"}))

    # the statement row is superseded, not deleted
    old = dict(connect().execute("SELECT superseded_at, requirement_type FROM standard_requirements"
                                 " WHERE id = ?", (stmt,)).fetchone())
    assert old["superseded_at"] is not None and old["requirement_type"] == "statement"
    # a later compile of the same standard no longer sees it as an open statement
    again = air.statements_of_standard("spec", allowed_document_ids=frozenset({"spec"}))
    assert again == []
    # the new confirmed row is the one left open, and it is not a `statement`
    new_row = dict(connect().execute("SELECT requirement_type, superseded_at FROM standard_requirements"
                                     " WHERE id = ?", (decided["new_requirement_id"],)).fetchone())
    assert new_row["requirement_type"] == "numeric_limit" and new_row["superseded_at"] is None
