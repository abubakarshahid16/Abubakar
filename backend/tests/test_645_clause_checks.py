"""#645 clause to check (Stage C, planner 12 Oct): for each clause sentence
stored with no limit that the review could not decide, the local model
PROPOSES a check - field, operator, value, unit, condition, quote - and CODE
verifies every part against the sentence. What passes is stored as a DRAFT
for the engineer; no verdict is ever decided on it.

A fake model stands in for the local one; every test is about what code does
with what the model said. Invented clauses only.
"""
from __future__ import annotations

import json

from app import ai_requirements as air
from app import ai_task_runner, comparison
from app.config import settings
from app.db import connect
from app.reasoning_provider import Response
from tests.test_w5_677_scope_ledger import _req, review_run, temp_storage  # noqa: F401 - fixtures

SENTENCE = "The cold differential test pressure shall not exceed 12 barg."


def proposal(**over) -> dict:
    base = {"has_limit": True, "field": "cold differential test pressure", "operator": "<=",
            "value": "12", "unit": "barg", "condition": None,
            "quote": "cold differential test pressure shall not exceed 12 barg"}
    return {**base, **over}


class Fake:
    def __init__(self, *replies, model="test-model"):
        self.requested_model = model
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]

    def reason(self, packet):
        return Response(text=self.replies.pop(0), provider="ollama", model_tag=self.requested_model,
                        digest="d", finish_reason="stop", prompt_sha256=packet.sha256)


# ------------------------------------------------------------- code verifies

def test_a_check_code_confirms_part_by_part_is_kept():
    check, why = air.verify_proposal(proposal(), SENTENCE)
    assert why is None
    assert check == {"field": "cold differential test pressure", "operator": "<=", "value": "12",
                     "unit": "barg", "condition": None,
                     "quote": "cold differential test pressure shall not exceed 12 barg"}


def test_a_number_not_in_the_quote_is_refused():
    assert air.verify_proposal(proposal(value="15"), SENTENCE) == (None, air.VALUE_NOT_IN_QUOTE)
    # the sign is part of the number: 12 is not -12
    minus = "The design temperature shall not be below -12 degC."
    assert air.verify_proposal(proposal(value="12", unit="degC", quote=minus.rstrip(".")),
                               minus)[1] == air.VALUE_NOT_IN_QUOTE


def test_a_unit_not_in_the_quote_or_not_a_unit_is_refused():
    assert air.verify_proposal(proposal(unit="psig"), SENTENCE) == (None, air.UNIT_NOT_IN_QUOTE)
    # "bar" is not "barg": a unit stands whole in the quote
    assert air.verify_proposal(proposal(unit="bar"), SENTENCE) == (None, air.UNIT_NOT_IN_QUOTE)
    assert air.verify_proposal(proposal(unit="valves"), SENTENCE) == (None, air.UNIT_UNRECOGNISED)


def test_a_conditional_limit_without_its_condition_is_refused():
    sentence = "For sour service, the corrosion allowance shall not be less than 3 mm."
    base = proposal(field="corrosion allowance", operator=">=", value="3", unit="mm",
                    quote="the corrosion allowance shall not be less than 3 mm")
    assert air.verify_proposal(base, sentence) == (None, air.CONDITION_MISSING)
    check, why = air.verify_proposal({**base, "condition": "For sour service"}, sentence)
    assert why is None and check["condition"] == "For sour service"
    # a condition the sentence does not hold is the model's, not the clause's
    assert air.verify_proposal({**base, "condition": "for wet H2S service"}, sentence) == (
        None, air.CONDITION_NOT_IN_SOURCE)


def test_the_quote_field_value_and_operator_must_stand_up():
    assert air.verify_proposal(proposal(quote="test pressure shall be 12 barg"), SENTENCE) == (
        None, air.QUOTE_NOT_IN_SOURCE)
    assert air.verify_proposal(proposal(field="None"), SENTENCE) == (None, air.FIELD_MISSING)
    assert air.verify_proposal(proposal(value=None), SENTENCE) == (None, air.VALUE_MISSING)
    assert air.verify_proposal(proposal(operator=">="), SENTENCE) == (None, air.OPERATOR_DISAGREED)
    assert air.verify_proposal({"has_limit": False}, SENTENCE) == (None, air.NO_LIMIT)


def test_shall_not_be_less_than_is_read_as_a_minimum():
    """Code's own reading of the operator decides: "not be less than" is >=,
    never the "<" its last two words alone would say."""
    figures = air.read_figures("the wall shall not be less than 3 mm thick")
    assert [(f["value"], f["unit"], f["operator"]) for f in figures] == [("3", "mm", ">=")]
    assert air.read_figures("the drop shall not be more than 5 kPa")[0]["operator"] == "<="


# ------------------------------------------------------ drafts and counts

def _statement(rid, text=SENTENCE):
    return {"id": rid, "requirement_type": "statement", "source_text": text}


def test_proposals_are_stored_as_drafts_and_counted_out_of_the_sentences():
    reqs = [_statement("r1"), _statement("r2", "Bolting shall be ASTM A193 B7."),
            _statement("r3", "Valve bodies shall be cast steel."),
            _statement("r4", "The test shall last 30 minutes.")]
    out = air.propose_checks(reqs, review_run_id="run-1", limit=3,
                             provider=Fake(proposal(), {"has_limit": False, "field": None,
                                                        "operator": None, "value": None, "unit": None,
                                                        "condition": None, "quote": None},
                                           "not json", "not json either"))
    # "no limit" is the model's answer, not code refusing a proposal
    assert out.pop("by_standard") == {"": {"asked": 3, "not_asked": 1}}  # 235.1
    assert out == {"sentences": 4, "asked": 3, "proposed": 1, "no_limit": 1, "refused": {},
                   "could_not_read": 1, "not_asked_budget": 1, "model": "test-model"}
    rows = [dict(r) for r in connect().execute("SELECT * FROM clause_check_drafts")]
    assert len(rows) == 1
    assert (rows[0]["requirement_id"], rows[0]["status"], rows[0]["value"], rows[0]["unit"]) == (
        "r1", "draft", "12", "barg")
    assert air.report_line(out) == (
        "1 of 4 sentence requirement(s) now have a proposed check (drafts for the engineer); "
        "1 the model read no limit in, 0 proposal(s) refused by code, 1 not read by the model, "
        "1 not asked (the per-run cap).")
    assert air.report_line(None) is None


def test_only_undecided_statements_are_offered():
    reqs = [_statement("open"), _statement("met"), {"id": "num", "requirement_type": "numeric_limit"},
            _statement("none")]
    status = {"open": comparison.NOT_IN_DOCUMENT_SCOPE, "met": comparison.COMPLIANT,
              "num": comparison.NOT_IN_DOCUMENT_SCOPE}
    assert [r["id"] for r in air.undecided_statements(reqs, status)] == ["open", "none"]


def test_the_run_card_prints_the_count_line_as_a_local_step():
    from app import ai_numbers

    counts = {"sentences": 5, "asked": 4, "proposed": 2, "refused": {air.VALUE_NOT_IN_QUOTE: 1},
              "could_not_read": 1, "not_asked_budget": 1, "model": "qwen3.5:2b"}
    step = ai_numbers.for_run({"requirement_split": {"clause_checks": counts}}, None, None)[
        "clause_checks"]
    assert (step["step"], step["state"], step["where"]) == ("AI clause checks", "incomplete",
                                                            "local model")
    assert step["lines"] == [air.report_line(counts)]
    assert step["counts"]["proposed"] == 2 and step["counts"]["sentences"] == 5
    assert (step["counts"]["refused"], step["counts"]["no_limit"]) == (1, 0)
    # NO RECORD IS NULL, NEVER A ZERO: a run from before #645 has no step
    assert ai_numbers.for_run({"requirement_split": {}}, None, None) is None


# ------------------------------------------------------------ in the review

def _findings(run):
    return sorted((r["requirement_id"] or "", r["compliance_status"]) for r in connect().execute(
        "SELECT requirement_id, compliance_status FROM review_findings WHERE review_run_id = ?",
        (run,)))


def test_the_review_proposes_drafts_and_no_verdict_changes(review_run, monkeypatch):  # noqa: F811
    run, _ids, scope = review_run
    stmt = _req("spec", "sc", SENTENCE, requirement_type="statement")
    off = comparison.run_comparison(run, allowed_document_ids=scope)
    assert off["clause_checks"] is None
    before = _findings(run)

    asked = []

    def fake_run_task(spec, text, provider=None, use_cache=True):
        asked.append(text)
        return ai_task_runner.TaskResult(spec.name, ai_task_runner.STATE_OK, proposal(), None,
                                         "test-model")

    monkeypatch.setattr(settings, "ai_clause_checks_enabled", True)
    monkeypatch.setattr(air.ai_task_runner, "run_task", fake_run_task)
    on = comparison.run_comparison(run, allowed_document_ids=scope)
    # ONLY the sentence this run could not decide is offered: the compared
    # limit, the definition and the gated clauses are not
    assert asked == [SENTENCE]
    assert on["clause_checks"]["proposed"] >= 1
    assert comparison.run_outcome(run, allowed_document_ids=scope)[
        "requirement_split"]["clause_checks"] == on["clause_checks"]
    from fastapi.testclient import TestClient
    from app.main import app
    card = TestClient(app).get(f"/api/reviews/runs/{run}/ai-numbers").json()["clause_checks"]
    assert card["lines"] == [air.report_line(on["clause_checks"])]
    # A DRAFT, NEVER A VERDICT: the run's findings are the same with it on
    assert _findings(run) == before
    draft = connect().execute("SELECT * FROM clause_check_drafts WHERE requirement_id = ?",
                              (stmt,)).fetchone()
    assert draft["status"] == "draft" and draft["review_run_id"] == run


# ------------------------------------------- the live run of 12 Oct (planner)

def test_a_run_stored_before_the_split_reads_its_no_limit_out_of_the_refusals():
    """Live run 12 Oct: "20 refused by code" counted the model's own "no
    limit" answers as code refusals. A stored run of that shape now says
    which is which, and names code's reasons."""
    stored = {"sentences": 51, "asked": 20, "proposed": 0, "could_not_read": 0,
              "not_asked_budget": 31, "model": "m",
              "refused": {air.NO_LIMIT: 17, air.QUOTE_NOT_IN_SOURCE: 2, air.VALUE_NOT_IN_QUOTE: 1}}
    assert air.split_refusals(stored) == (17, {air.QUOTE_NOT_IN_SOURCE: 2, air.VALUE_NOT_IN_QUOTE: 1})
    assert air.report_line(stored) == (
        "0 of 51 sentence requirement(s) now have a proposed check (drafts for the engineer); "
        "17 the model read no limit in, 3 proposal(s) refused by code "
        f"({air.QUOTE_NOT_IN_SOURCE}: 2; {air.VALUE_NOT_IN_QUOTE}: 1), 0 not read by the model, "
        "31 not asked (the per-run cap).")
    from app import ai_numbers
    step = ai_numbers.clause_checks(stored)
    assert (step["counts"]["no_limit"], step["counts"]["refused"]) == (17, 3)


def test_the_cap_goes_first_to_sentences_that_print_a_figure():
    reqs = [_statement("words-1", "Valve bodies shall be cast steel."),
            _statement("words-2", "Bolting shall be ASTM A-type alloy steel."),
            _statement("figure", SENTENCE)]
    asked = []

    class Recording(Fake):
        def reason(self, packet):
            asked.append(packet)
            return super().reason(packet)

    out = air.propose_checks(reqs, limit=1, provider=Recording(proposal()))
    assert (out["asked"], out["proposed"], out["not_asked_budget"]) == (1, 1, 2)
    rows = [r["requirement_id"] for r in connect().execute("SELECT requirement_id FROM clause_check_drafts")]
    assert rows == ["figure"]


def test_the_model_is_recorded_when_it_answered_but_nothing_passed():
    """Live run 12 Oct: 20 answers, all "no limit", and the run said model: null."""
    out = air.propose_checks([_statement("r1", "Valve bodies shall be cast steel.")], limit=5,
                             provider=Fake({"has_limit": False, "field": None, "operator": None,
                                           "value": None, "unit": None, "condition": None,
                                           "quote": None}, model="local-2b"))
    assert (out["no_limit"], out["proposed"], out["model"]) == (1, 0, "local-2b")


def test_the_cap_goes_first_to_a_sentence_tied_to_a_field_the_sheet_states():
    """Order 235.1: a sentence naming a stated field outranks one that merely
    prints a figure; no sheet names = the old order."""
    figure_only = _statement("figure-only", "The test shall last 30 minutes.")
    tied = _statement("tied", "The set pressure shall be marked on the nameplate.")
    other = _statement("other", "Valve bodies shall be cast steel.")
    asked = []

    class Recording(Fake):
        def reason(self, packet):
            asked.append(packet)
            return super().reason(packet)

    facts = [
        {
            "field_name": "set_pressure",
            "field_label": "Set pressure",
            "raw_value": "10",
            "is_blank": 0,
        }
    ]
    out = air.propose_checks(
        [figure_only, other, tied],
        limit=1,
        facts=facts,
        provider=Recording(proposal(has_limit=False)),
    )
    assert out["asked"] == 1 and "nameplate" in asked[0].prompt
    assert out["by_standard"] == {"": {"asked": 1, "not_asked": 2}}
    asked.clear()
    air.propose_checks(
        [figure_only, other, tied],
        limit=1,
        facts=[],
        provider=Recording(proposal(has_limit=False)),
    )
    assert "30 minutes" in asked[0].prompt


def test_a_field_name_inside_another_word_does_not_tie_a_sentence():
    from app import clause_budget

    reqs = [
        {"id": "a", "source_text": "Compressed air shall be dry."},
        {"id": "b", "source_text": "The air pressure shall be checked."},
    ]
    got = clause_budget.order(reqs, lambda r: r["source_text"], ["air pressure"])
    assert [r["id"] for r in got] == ["b", "a"]
    got = clause_budget.order(reqs, lambda r: r["source_text"], ["pressur"])
    assert [r["id"] for r in got] == ["a", "b"]


def test_the_budget_is_counted_per_standard():
    from app import clause_budget

    reqs = [
        {"id": i, "standard_name": n} for i, n in enumerate(["A", "A", "B", "B", "B"])
    ]
    assert clause_budget.per_standard(reqs, 3) == {
        "A": {"asked": 2, "not_asked": 0},
        "B": {"asked": 1, "not_asked": 2},
    }
