# ruff: noqa: F811
"""The AI reviewer on the LOCAL model (owner orders, 12 Nov 2026), behind `AGENT_REVIEW_LOCAL_ENGINE_ENABLED`.

Invented paper, rule book and models. A fake Ollama answers `model_transport.post_json_retrying`; no real model is ever loaded,
and the Claude lane is a transport that fails the test if it is touched."""

from __future__ import annotations

import json

import pytest

from app import (
    agent_review_jobs,
    claude_spend,
    db,
    model_memory,
    model_transport,
    reader_transport,
    review_engine,
)
from app import agent_review_local as local_mod
from app import agent_review_two_reader as two
from app import agent_run_second as second_mod
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of

E = review_engine
CLASS = "AI verdict, two readers agree"
A_NAME = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_XL"
B_NAME = "glm-4.7-flash"


class FakeOllama:
    """The local engine: answers from tables by model name; records every request in order."""

    def __init__(self, a=A_NAME, b=B_NAME, first=None, second=None, garbage=False, empty=False):
        self.a, self.b = a, b
        self.first = dict(s.ANSWERS if first is None else first)
        self.second = dict(s.ANSWERS if second is None else second)
        self.garbage, self.empty = garbage, empty
        self.log: list[str] = []

    def __call__(self, path, body, *, timeout):
        assert path == "/api/chat"
        self.log.append(body["model"])
        if "CONTEXT CHECK" in body["messages"][0]["content"]:  # the rule-book context check of a Fail (second stage)
            return {"model": body["model"], "message": {"content": json.dumps({"limits": False})}, "done_reason": "stop"}
        user = body["messages"][-1]["content"]
        raw = user[user.rfind('{"items":') :].split("\n\n")[0]
        ids = [q["item_id"] for q in json.loads(raw)["items"]]
        table = self.first if body["model"] == self.a else self.second
        if self.empty:
            text = ""
        elif self.garbage:
            text = "I think it is fine, sorry"
        else:
            text = json.dumps({"answers": [{"item_id": i, **table[i]} for i in ids if i in table]})
        return {"model": body["model"], "message": {"content": text}, "done_reason": "stop"}


def _claude_must_not_be_touched(url, *, headers, body, timeout):
    raise AssertionError("a local run reached the Claude lane")


@pytest.fixture
def local(w, monkeypatch):
    """The world of the AI reviewer's job tests, run on the local engine."""
    ollama = FakeOllama()
    unloads: list[str] = []
    monkeypatch.setattr(settings, "agent_review_local_engine_enabled", True)
    monkeypatch.setattr(settings, "agent_review_local_model_a", A_NAME)
    monkeypatch.setattr(settings, "agent_review_local_model_b", B_NAME)
    monkeypatch.setattr(agent_review_jobs, "local_run", lambda _run: True)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (_claude_must_not_be_touched, s.ENV))
    monkeypatch.setattr(model_transport, "post_json_retrying", ollama)
    monkeypatch.setattr(model_memory, "unload", lambda m: unloads.append(m) or True)
    monkeypatch.setattr(local_mod, "_installed", lambda _m: True)

    def boom(*_a, **_k):
        raise AssertionError("a local run asked for the Claude transport")

    monkeypatch.setattr(reader_transport, "transport", boom)
    w["ollama"], w["unloads"] = ollama, unloads
    return w


@pytest.fixture
def two_on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)


def run_row(run_id):
    return dict(
        db.connect().execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,)).fetchone()
    )


def step_of(run_id):
    return json.loads(run_row(run_id)["counts_json"]).get("two_reader_step")


# ---------------------------------------------------------------- the family rule


def test_two_sizes_of_one_local_family_are_not_two_readers():
    assert not second_mod.models_differ([A_NAME], "qwen3:8b")
    assert not second_mod.models_differ(["qwen3:8b"], "qwen3:32b")
    assert second_mod.models_differ([A_NAME], B_NAME)
    assert second_mod.models_differ([A_NAME], "gpt-oss:20b")
    assert second_mod.models_differ(["claude-sonnet-5-5"], "claude-opus-5-5")  # a Claude id keeps its own rule
    assert not second_mod.models_differ([A_NAME], "unknown")


def test_a_name_of_no_listed_local_family_is_compared_whole():
    assert second_mod.models_differ(["m1"], "m2")  # as before: nothing is guessed about a name the list does not know
    assert not second_mod.models_differ(["m1"], "m1")


def test_the_second_reader_is_ready_only_for_another_family_that_is_installed():
    ok = local_mod.second_ready_for
    assert ok(A_NAME, B_NAME, True) == (True, "")
    assert ok(A_NAME, "", None)[0] is False
    assert ok(A_NAME, "qwen3:8b", True)[0] is False
    assert ok(A_NAME, B_NAME, False)[0] is False


# ---------------------------------------------------------------- the engine: one socket, zero cost, no spend row


def test_a_local_run_uses_the_local_socket_only_costs_zero_and_writes_no_spend_row(local):
    run_id = run_review()
    assert local["ollama"].log and set(local["ollama"].log) == {A_NAME}  # the first reader only (two readers are off)
    assert claude_spend.entries() == []  # never a ledger line
    row = run_row(run_id)
    assert row["usd"] == 0.0
    lines = lines_of(run_id)
    assert lines  # the review was done
    for ln in lines.values():
        assert float(json.loads(ln["line_json"]).get("usd") or 0.0) == 0.0
        assert ln["verdict_class"] != CLASS  # no second reader asked: nothing is "two readers agree"


def test_the_local_run_unloads_every_model_it_loaded(local, two_on):
    run_review()
    assert A_NAME in local["unloads"] and B_NAME in local["unloads"]


def test_the_first_reader_reads_every_item_before_the_second_model_is_ever_loaded(local, two_on):
    run_review()
    log = local["ollama"].log
    first_b = log.index(B_NAME)
    assert set(log[:first_b]) == {A_NAME} and set(log[first_b:]) == {B_NAME}  # never interleaved
    assert local["unloads"].index(A_NAME) < len(local["unloads"])  # A was dropped before B read
    assert local["unloads"][0] == A_NAME


def test_two_readers_of_two_families_give_the_class_on_the_local_engine(local, two_on):
    run_id = run_review()
    got = lines_of(run_id)
    assert (got["R-coat"]["verdict_class"], got["R-coat"]["word"]) == (CLASS, "AI verdict: met")
    assert (got["R-mark"]["verdict_class"], got["R-mark"]["word"]) == (CLASS, "AI verdict: not met")
    for ln in got.values():
        assert ln["word"] not in ("Pass", "Fail") or ln["verdict_class"] == "Proven by code"


@pytest.mark.parametrize("second_name", ["qwen3:8b", "", "unknown"])
def test_a_second_model_of_the_same_family_or_none_is_never_asked_and_never_the_class(
    local, two_on, monkeypatch, second_name
):
    monkeypatch.setattr(settings, "agent_review_local_model_b", second_name)
    run_id = run_review()
    assert set(local["ollama"].log) == {A_NAME}  # model B was never asked
    assert all(ln["verdict_class"] != CLASS for ln in lines_of(run_id).values())
    step = step_of(run_id)
    assert step["off"] == local_mod.OFF_SECOND_UNAVAILABLE and step["asked"] == 0
    thinks = lines_of(run_id)["R-coat"]
    assert thinks["word"].startswith("AI thinks")  # the line stays "AI thinks"


def test_a_second_model_that_is_not_installed_is_not_asked(local, two_on, monkeypatch):
    monkeypatch.setattr(local_mod, "_installed", lambda _m: False)
    run_id = run_review()
    assert set(local["ollama"].log) == {A_NAME}
    assert step_of(run_id)["off"] == local_mod.OFF_SECOND_UNAVAILABLE


def test_the_workbook_says_a_second_reader_was_not_available(local, two_on, monkeypatch):
    from app import crs_ai_workbook as WB

    monkeypatch.setattr(settings, "agent_review_local_model_b", "")
    row = WB._step_words({"candidates": 2, "asked": 0, "calls": 0, "off": local_mod.OFF_SECOND_UNAVAILABLE})
    assert "second reader was not available" in row


def test_a_model_of_the_other_stage_is_refused_at_the_seam():
    eng = local_mod.LocalEngine(A_NAME, B_NAME, installed=lambda _m: True, post=lambda *a, **k: {})
    with pytest.raises(local_mod.LocalStageRefused):  # B before the first reader is finished
        eng.call("claude-opus-5-5", {"system": [], "messages": []}, 100)
    eng.to_second()
    with pytest.raises(local_mod.LocalStageRefused):  # A after the second stage began
        eng.call(A_NAME, {"system": [], "messages": []}, 100)


# ---------------------------------------------------------------- verdict safety is the Claude path's own


def test_a_quote_the_code_cannot_find_is_never_a_decision_on_the_local_path(local, two_on):
    local["ollama"].first = {
        **s.ANSWERS,
        "R-coat": {**s.ANSWERS["R-coat"], "paper_quote": "Coating layers FIVE invented"},
    }
    got = lines_of(run_review())
    coat = got["R-coat"]
    assert coat["verdict_class"] not in (CLASS, "Proven by code")
    assert coat["word"] not in ("AI verdict: met", "Pass")
    assert "not verified" in coat["reason"] or "quote" in coat["reason"]


def test_a_second_reader_quote_the_code_cannot_find_does_not_give_the_class(local, two_on):
    local["ollama"].second = {
        **s.ANSWERS,
        "R-mark": {**s.ANSWERS["R-mark"], "paper_quote": "Marking GREEN invented"},
    }
    got = lines_of(run_review())
    assert got["R-mark"]["verdict_class"] != CLASS
    assert got["R-coat"]["verdict_class"] == CLASS  # the other line is unaffected


@pytest.mark.parametrize("kw", [{"garbage": True}, {"empty": True}])
def test_an_unreadable_or_empty_local_answer_is_a_query_never_met_or_not_met(local, kw):
    local["ollama"].garbage = kw.get("garbage", False)
    local["ollama"].empty = kw.get("empty", False)
    got = lines_of(run_review())
    assert got
    for ln in got.values():
        assert ln["word"] not in ("Pass", "Fail", "AI verdict: met", "AI verdict: not met", "AI thinks: met", "AI thinks: not met")
        assert ln["verdict_class"] != "Proven by code"
        assert "no answer" in ln["reason"].lower() or "could not" in ln["reason"].lower() or "AI call failed" in ln["reason"]


def test_a_number_line_is_still_decided_by_code_not_by_the_local_model(local):
    got = lines_of(run_review())
    assert (got["R-frame"]["verdict_class"], got["R-frame"]["word"]) == ("Proven by code", "Pass")


# ---------------------------------------------------------------- context: split, never cut, never "checked"


def test_a_request_that_does_not_fit_is_not_sent_and_says_so(local, monkeypatch):
    monkeypatch.setattr(model_transport, "shared_window", lambda: 900)  # nothing can fit
    run_id = run_review()
    assert local["ollama"].log == []  # nothing was sent, nothing was cut
    for ln in lines_of(run_id).values():
        assert local_mod.LOCAL_TOO_LONG in json.loads(ln["line_json"]).get("error", "") or local_mod.LOCAL_TOO_LONG in ln["reason"]
        assert ln["word"] not in ("Pass", "Fail", "AI verdict: met", "AI verdict: not met")


def test_a_batch_that_is_too_long_is_split_by_items_and_all_are_asked(local, monkeypatch):
    # a window that fits one item's request but not the whole batch's
    eng = local_mod.LocalEngine(A_NAME, B_NAME)
    one = {"system": [{"type": "text", "text": "s" * 100}], "messages": [{"role": "user", "content": [{"type": "text", "text": "x" * 900}]}]}
    big = {"system": [{"type": "text", "text": "s" * 100}], "messages": [{"role": "user", "content": [{"type": "text", "text": "x" * 9000}]}]}
    eng._window = 1500
    assert eng.fits(one, 300) and not eng.fits(big, 300)
    run_id = run_review()  # the whole world through the split path: every item has a line
    assert set(lines_of(run_id)) == {"R-coat", "R-frame", "R-mark", "R-colour"}


# ---------------------------------------------------------------- the switch off / old path

def test_a_stored_plan_on_local_is_a_local_run_only_with_the_switch_on(w, monkeypatch):
    plan = {"choice": "local", "parts": [{"name": "rule_check", "engine": "local", "why": "x"},
                                         {"name": "ai_review", "engine": "local", "why": "y"}]}  # fmt: skip
    run_id, _job = s_start()
    E.record(db.connect(), run_id, plan, "adm", then_ai=False, bar_claude=True, now="2026-11-12T00:00:00Z")
    assert E.ai_review_engine(db.connect(), run_id) == "local"
    monkeypatch.setattr(settings, "agent_review_local_engine_enabled", False)
    assert agent_review_jobs.local_run(run_id) is False
    monkeypatch.setattr(settings, "agent_review_local_engine_enabled", True)
    assert agent_review_jobs.local_run(run_id) is True
    plan["parts"][1]["engine"] = "claude"
    E.record(db.connect(), run_id, plan, "adm", then_ai=False, bar_claude=False, now="2026-11-12T00:00:00Z")
    assert agent_review_jobs.local_run(run_id) is False
    assert E.ai_review_engine(db.connect(), "no-such-run") is None


def s_start():
    from tests.test_agent_review_job import start

    return start()


# ---------------------------------------------------------------- the plan


def open_facts(**kw):
    base = dict(
        kind="datasheet", agent_enabled=True, provider="per_task", agent_engine_claude=True,
        step_engine_claude=True, lane_open=True, blocked=False, paper_approved=True, is_contract=False,
        contract_yes=False, scored_allowed=True, kind_scored=True, caps_ok=True, books_ok=True,
    )  # fmt: skip
    base.update(kw)
    return E.Facts(**base)


def test_local_only_with_the_switch_on_runs_the_ai_review_on_the_local_model():
    plan = E.decide("local", open_facts(local_ai=True))
    ai = plan.part(E.AI_REVIEW)
    assert ai.engine == E.ON_LOCAL and plan.text_leaves is False
    assert plan.part(E.RULE_CHECK).engine == E.ON_LOCAL


def test_with_the_switch_off_the_plan_is_exactly_as_before():
    off = E.decide("local", open_facts())
    assert off.part(E.AI_REVIEW).engine == E.NOT_RUN
    assert off.part(E.AI_REVIEW).why == E.AI_NEEDS_CLAUDE_LOCAL
    assert off.as_dict() == E.decide("local", open_facts(local_ai=False)).as_dict()
    contract = E.decide("automatic", open_facts(kind="contract", is_contract=True, paper_approved=False))
    assert contract.part(E.AI_REVIEW).engine == E.NOT_RUN  # no yes: no AI review at all, as before


def test_automatic_for_a_paper_that_may_not_go_to_claude_reads_it_locally():
    contract = E.decide("automatic", open_facts(kind="contract", is_contract=True, paper_approved=False, local_ai=True))
    ai = contract.part(E.AI_REVIEW)
    assert ai.engine == E.ON_LOCAL and "Claude is not used" in ai.why
    assert contract.text_leaves is False and contract.needs_yes is True
    blocked = E.decide("automatic", open_facts(blocked=True, local_ai=True))
    assert blocked.part(E.AI_REVIEW).engine == E.ON_LOCAL


def test_claude_is_still_refused_never_silently_local():
    plan = E.decide("claude", open_facts(blocked=True, paper_approved=False, step_engine_claude=False, local_ai=True))
    assert plan.refused and plan.part(E.AI_REVIEW).engine == E.NOT_RUN


def test_automatic_still_uses_claude_when_every_door_is_open():
    assert E.decide("automatic", open_facts(local_ai=True)).part(E.AI_REVIEW).engine == E.ON_CLAUDE


def test_the_local_ai_review_is_not_offered_for_an_unknown_kind_or_with_the_reviewer_off():
    assert E.decide("local", open_facts(kind=None, local_ai=True)).part(E.AI_REVIEW).engine == E.NOT_RUN
    assert E.decide("local", open_facts(agent_enabled=False, local_ai=True)).part(E.AI_REVIEW).engine == E.NOT_RUN
    assert E.decide("local", open_facts(kind="drawing", local_ai=True)).part(E.AI_REVIEW).engine == E.NOT_RUN


def test_no_plan_that_runs_locally_says_text_leaves_for_any_choice_kind_or_door():
    import itertools

    for choice, kind, blocked, approved, lane_open in itertools.product(
        E.CHOICES, ("datasheet", "procedure", "contract"), (True, False), (True, False), (True, False)
    ):
        plan = E.decide(choice, open_facts(kind=kind, is_contract=kind == "contract", blocked=blocked,
                                           paper_approved=approved, lane_open=lane_open, local_ai=True))  # fmt: skip
        d = plan.as_dict()
        for part in plan.parts:
            if part.engine == E.ON_LOCAL:
                assert part.engine != E.ON_CLAUDE
        assert d["text_leaves"] == any(p.engine == E.ON_CLAUDE for p in plan.parts)


def test_the_sentence_and_cost_of_a_local_plan_say_local_zero_and_a_guess(w, monkeypatch):
    import sqlite3

    plan = E.decide("local", open_facts(local_ai=True)).as_dict()
    plan["kind"] = "datasheet"
    sentence = E.sentence_of(plan)
    assert "runs on the local model" in sentence and "No text leaves this computer" in sentence
    conn = db.connect()
    assert isinstance(conn, sqlite3.Connection)
    t = E._local_time(conn, s.PAPER)
    assert t["minutes_guess"] is None and "not known yet" in t["basis"]  # no earlier run: nothing invented


def test_a_local_time_estimate_is_labelled_a_guess_and_counts_requests(w):
    run_id, _job = s_start()
    with db.connect() as conn:
        conn.execute("INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, items_total, started_at) VALUES (?,?,?,?,?,?)",
                     (run_id, s.PAPER, "datasheet", "read by code", 37, "2026-11-12"))  # fmt: skip
        t = E._local_time(conn, s.PAPER)
    assert t["requests"] == 13 + 7 and t["minutes_guess"] == 20 and "guess" in t["basis"]


# ---------------------------------------------------------------- the follow-up and the sheet header


def test_the_sheet_header_of_a_local_ai_review_says_local_not_claude():
    from app import crs_ai_header

    assert "local model" in crs_ai_header.reviewed_by("r", ai=True, usd=0.0, local=True)
    assert crs_ai_header.reviewed_by("r", ai=True, usd=0.0) == "AI reviewer on Claude"


def test_a_two_reader_state_is_a_code_never_text():
    assert local_mod.OFF_SECOND_UNAVAILABLE != two.OFF_LEAD_UNKNOWN
