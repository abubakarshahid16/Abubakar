# ruff: noqa: F811, C408
"""The AI reviewer on the LOCAL model (owner orders, 12 Nov 2026), behind `AGENT_REVIEW_LOCAL_ENGINE_ENABLED`.

Invented paper, rule book and models. A fake Ollama answers `model_transport.post_json_retrying`; no real model is ever loaded,
and the Claude lane is a transport that fails the test if it is touched."""

from __future__ import annotations

import json
import re

import pytest

from app import (
    agent_claude,
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
#: what the local engine's own /api/show says about each invented model (family words as it reports them)
SHOWS = {
    A_NAME: {"details": {"family": "qwen35moe", "families": ["qwen35moe"]}},
    B_NAME: {"details": {"family": "glm4moe", "families": ["glm4moe"]}},
    "qwen3:8b": {"details": {"family": "qwen3", "families": ["qwen3"]}},
    "gpt-oss:20b": {"details": {"family": "gptoss", "families": ["gptoss"]}},
}


def _tokens(body) -> int:
    """What a real engine reports: the tokens of the prompt it read (about 3 characters a token)."""
    return sum(len(m["content"]) for m in body["messages"]) // 3 + 1


class FakeOllama:
    """The local engine: answers from tables by model name; records every request in order."""

    def __init__(
        self,
        a=A_NAME,
        b=B_NAME,
        first=None,
        second=None,
        garbage=False,
        empty=False,
        cut_first_of_each=False,
    ):
        self.a, self.b = a, b
        self.cut_first_of_each, self.cut_seen = cut_first_of_each, set()
        self.first = dict(s.ANSWERS if first is None else first)
        self.second = dict(s.ANSWERS if second is None else second)
        self.garbage, self.empty = garbage, empty
        self.log: list[str] = []
        self.bodies = []

    report = None  # "short" | "window" | "missing" | "tiny": what the engine says about the prompt it read
    bodies: list = []

    def __call__(self, path, body, *, timeout):
        self.bodies.append(body)
        got = self._answer(path, body)
        if self.report == "short":
            got["prompt_eval_count"] = (
                5  # the engine read far fewer tokens than the request has
            )
        elif self.report == "window":
            got["prompt_eval_count"] = body["options"][
                "num_ctx"
            ]  # it read up to the window: the rest was cut
        elif self.report == "missing":
            got.pop("prompt_eval_count")
        return got

    def _answer(self, path, body):
        assert path == "/api/chat"
        self.log.append(body["model"])
        if (
            "CONTEXT CHECK" in body["messages"][0]["content"]
        ):  # the rule-book context check of a Fail (second stage)
            return {
                "model": body["model"],
                "message": {"content": json.dumps({"limits": False})},
                "done_reason": "stop",
                "prompt_eval_count": _tokens(body),
            }
        user = body["messages"][-1]["content"]
        raw = user[user.rfind('{"items":') :].split("\n\n")[0]
        ids = [q["item_id"] for q in json.loads(raw)["items"]]
        table = self.first if body["model"] == self.a else self.second
        if (
            self.cut_first_of_each
            and body["model"] == self.a
            and tuple(ids) not in self.cut_seen
        ):
            self.cut_seen.add(
                tuple(ids)
            )  # the answer stops at the output limit: half a JSON text
            return {
                "model": body["model"],
                "message": {"content": '{"answers": [{"item_id": "R-co'},
                "done_reason": "length",
                "prompt_eval_count": _tokens(body),
            }
        if self.empty:
            text = ""
        elif self.garbage:
            text = "I think it is fine, sorry"
        else:
            text = json.dumps(
                {"answers": [{"item_id": i, **table[i]} for i in ids if i in table]}
            )
        return {
            "model": body["model"],
            "message": {"content": text},
            "done_reason": "stop",
            "prompt_eval_count": _tokens(body),
        }


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
    monkeypatch.setattr(local_mod, "local_run", lambda _run: True)
    monkeypatch.setattr(
        agent_review_jobs, "lane", lambda: (_claude_must_not_be_touched, s.ENV)
    )
    monkeypatch.setattr(model_transport, "post_json_retrying", ollama)
    monkeypatch.setattr(model_memory, "unload", lambda m: unloads.append(m) or True)
    monkeypatch.setattr(local_mod, "_show", lambda m: SHOWS.get(m))

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
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )


def step_of(run_id):
    return json.loads(run_row(run_id)["counts_json"]).get("two_reader_step")


# ---------------------------------------------------------------- the family rule


def test_two_sizes_of_one_local_family_are_not_two_readers():
    assert not second_mod.models_differ([A_NAME], "qwen3:8b")
    assert not second_mod.models_differ(["qwen3:8b"], "qwen3:32b")
    assert second_mod.models_differ([A_NAME], B_NAME)
    assert second_mod.models_differ([A_NAME], "gpt-oss:20b")
    assert second_mod.models_differ(
        ["claude-sonnet-5-5"], "claude-opus-5-5"
    )  # a Claude id keeps its own rule
    assert not second_mod.models_differ([A_NAME], "unknown")


def test_a_name_of_no_listed_local_family_is_compared_whole():
    assert second_mod.models_differ(
        ["m1"], "m2"
    )  # as before: nothing is guessed about a name the list does not know
    assert not second_mod.models_differ(["m1"], "m1")


def _show_of(family):
    return (
        None
        if family is None
        else {"details": {"family": family, "families": [family]}}
    )


#: (first model, second model, the family the engine reports for each, may they be two readers): the reviewer's nine pairs and more
PAIRS = [
    ("codellama:7b", "llama3:8b", "llama", "llama", False),
    ("qwq:32b", "qwen3.5:9b", "qwen2", "qwen35", False),
    (
        "magistral:24b",
        "mistral:7b",
        "mistral3",
        "llama",
        False,
    ),  # the engine says different families; the name rule is stricter
    ("medgemma:4b", "gemma3:4b", "gemma3", "gemma3", False),
    ("hf.co/x/Meta-Llama-3.1-8B-GGUF:Q4", "llama3.1:8b", "llama", "llama", False),
    (
        "reader-ft:latest",
        "qwen3.5:9b",
        "qwen35",
        "qwen35",
        False,
    ),  # a renamed copy: the engine's data shows the same family
    (A_NAME, B_NAME, "qwen35moe", "glm4moe", True),
    ("qwen3.5:9b", "gpt-oss:20b", "qwen35", "gptoss", True),
    (
        "reader-ft:latest",
        "gpt-oss:20b",
        "qwen35",
        "gptoss",
        True,
    ),  # an unknown name is fine when the engine says the families differ
    (
        "qwen3.5:9b",
        "reader-ft:latest",
        "qwen35",
        None,
        False,
    ),  # the second model's data cannot be read: fails closed
    (
        "qwen3.5:9b",
        "glm-4.7-flash",
        None,
        "glm4moe",
        False,
    ),  # the first model's data cannot be read: fails closed
]


@pytest.mark.parametrize(("a", "b", "fa", "fb", "ready"), PAIRS)
def test_two_readers_are_two_families_by_the_engines_own_data_and_it_fails_closed(
    a, b, fa, fb, ready
):
    got = local_mod.second_ready_for(a, b, _show_of(fa), _show_of(fb))
    assert got[0] is ready
    assert (got[1] == "") is ready  # a refusal always says why


def test_a_second_model_the_engine_reports_no_family_for_is_not_a_second_reader():
    assert (
        local_mod.second_ready_for(A_NAME, B_NAME, SHOWS[A_NAME], {"details": {}})[0]
        is False
    )
    assert local_mod.second_ready_for(A_NAME, "", SHOWS[A_NAME], None)[0] is False
    assert local_mod.families_of(
        {
            "details": {"family": "qwen35moe"},
            "model_info": {"general.architecture": "qwen35moe"},
        }
    ) == {"qwen"}


def test_the_show_call_goes_through_the_one_local_socket_module(monkeypatch):
    seen = []
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, *, timeout: (
            seen.append((path, body)) or {"details": {"family": "x"}}
        ),
    )
    assert local_mod._show("m")["details"]["family"] == "x" and seen == [
        ("/api/show", {"model": "m"})
    ]
    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda *a, **k: (_ for _ in ()).throw(model_transport.ModelHostRefused("no")),
    )
    assert local_mod._show("m") is None


# ---------------------------------------------------------------- the engine: one socket, zero cost, no spend row


def test_a_local_run_uses_the_local_socket_only_costs_zero_and_writes_no_spend_row(
    local,
):
    run_id = run_review()
    assert local["ollama"].log and set(local["ollama"].log) == {
        A_NAME
    }  # the first reader only (two readers are off)
    assert claude_spend.entries() == []  # never a ledger line
    row = run_row(run_id)
    assert row["usd"] == 0.0
    lines = lines_of(run_id)
    assert lines  # the review was done
    for ln in lines.values():
        assert float(json.loads(ln["line_json"]).get("usd") or 0.0) == 0.0
        assert (
            ln["verdict_class"] != CLASS
        )  # no second reader asked: nothing is "two readers agree"


def test_a_cut_off_local_answer_is_retried_and_still_costs_zero(local):
    local["ollama"].cut_first_of_each = True
    run_id = run_review()
    got = lines_of(run_id)
    assert (
        set(got) == {"R-coat", "R-frame", "R-mark", "R-colour"}
        and local["ollama"].cut_seen
    )
    assert run_row(run_id)["usd"] == 0.0 and claude_spend.entries() == []
    for ln in got.values():
        assert (
            float(json.loads(ln["line_json"]).get("usd") or 0.0) == 0.0
        )  # a cut-off call is not charged a Claude worst case


def test_the_local_run_unloads_every_model_it_loaded(local, two_on):
    run_review()
    assert A_NAME in local["unloads"] and B_NAME in local["unloads"]


def test_the_first_reader_reads_every_item_before_the_second_model_is_ever_loaded(
    local, two_on
):
    run_review()
    log = local["ollama"].log
    first_b = log.index(B_NAME)
    assert set(log[:first_b]) == {A_NAME} and set(log[first_b:]) == {
        B_NAME
    }  # never interleaved
    assert local["unloads"].index(A_NAME) < len(
        local["unloads"]
    )  # A was dropped before B read
    assert local["unloads"][0] == A_NAME


def test_two_readers_of_two_families_give_the_class_on_the_local_engine(local, two_on):
    run_id = run_review()
    got = lines_of(run_id)
    assert (got["R-coat"]["verdict_class"], got["R-coat"]["word"]) == (
        CLASS,
        "AI verdict: met",
    )
    assert (got["R-mark"]["verdict_class"], got["R-mark"]["word"]) == (
        CLASS,
        "AI verdict: not met",
    )
    for ln in got.values():
        assert (
            ln["word"] not in ("Pass", "Fail")
            or ln["verdict_class"] == "Proven by code"
        )


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
    monkeypatch.setattr(
        local_mod, "_show", lambda m: None if m == B_NAME else SHOWS.get(m)
    )
    run_id = run_review()
    assert set(local["ollama"].log) == {A_NAME}
    assert step_of(run_id)["off"] == local_mod.OFF_SECOND_UNAVAILABLE


def test_the_workbook_says_a_second_reader_was_not_available(
    local, two_on, monkeypatch
):
    from app import crs_ai_workbook as WB

    monkeypatch.setattr(settings, "agent_review_local_model_b", "")
    row = WB._step_words(
        {
            "candidates": 2,
            "asked": 0,
            "calls": 0,
            "off": local_mod.OFF_SECOND_UNAVAILABLE,
        }
    )
    assert "second reader was not available" in row


def test_a_model_of_the_other_stage_is_refused_at_the_seam():
    eng = local_mod.LocalEngine(
        A_NAME, B_NAME, show=lambda m: SHOWS.get(m), post=lambda *a, **k: {}
    )
    with pytest.raises(
        local_mod.LocalStageRefused
    ):  # B before the first reader is finished
        eng.call("claude-opus-5-5", {"system": [], "messages": []}, 100)
    eng.to_second()
    with pytest.raises(local_mod.LocalStageRefused):  # A after the second stage began
        eng.call(A_NAME, {"system": [], "messages": []}, 100)


# ---------------------------------------------------------------- verdict safety is the Claude path's own


def test_a_quote_the_code_cannot_find_is_never_a_decision_on_the_local_path(
    local, two_on
):
    local["ollama"].first = {
        **s.ANSWERS,
        "R-coat": {
            **s.ANSWERS["R-coat"],
            "paper_quote": "Coating layers FIVE invented",
        },
    }
    got = lines_of(run_review())
    coat = got["R-coat"]
    assert coat["verdict_class"] not in (CLASS, "Proven by code")
    assert coat["word"] not in ("AI verdict: met", "Pass")
    assert "not verified" in coat["reason"] or "quote" in coat["reason"]


def test_a_second_reader_quote_the_code_cannot_find_does_not_give_the_class(
    local, two_on
):
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
        assert ln["word"] not in (
            "Pass",
            "Fail",
            "AI verdict: met",
            "AI verdict: not met",
            "AI thinks: met",
            "AI thinks: not met",
        )
        assert ln["verdict_class"] != "Proven by code"
        assert (
            "no answer" in ln["reason"].lower()
            or "could not" in ln["reason"].lower()
            or "AI call failed" in ln["reason"]
        )


def test_a_number_line_is_still_decided_by_code_not_by_the_local_model(local):
    got = lines_of(run_review())
    assert (got["R-frame"]["verdict_class"], got["R-frame"]["word"]) == (
        "Proven by code",
        "Pass",
    )


# ---------------------------------------------------------------- context: split, never cut, never "checked"


def test_a_request_that_does_not_fit_is_not_sent_and_says_so(local, monkeypatch):
    monkeypatch.setattr(
        model_transport, "shared_window", lambda: 900
    )  # nothing can fit
    run_id = run_review()
    assert local["ollama"].log == []  # nothing was sent, nothing was cut
    for ln in lines_of(run_id).values():
        assert (
            local_mod.LOCAL_TOO_LONG in json.loads(ln["line_json"]).get("error", "")
            or local_mod.LOCAL_TOO_LONG in ln["reason"]
        )
        assert ln["word"] not in (
            "Pass",
            "Fail",
            "AI verdict: met",
            "AI verdict: not met",
        )


def test_a_batch_that_is_too_long_is_split_by_items_and_all_are_asked(
    local, monkeypatch
):
    # a window that fits one item's request but not the whole batch's
    eng = local_mod.LocalEngine(A_NAME, B_NAME)
    one = {
        "system": [{"type": "text", "text": "s" * 100}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "x" * 900}]}
        ],
    }
    big = {
        "system": [{"type": "text", "text": "s" * 100}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "x" * 9000}]}
        ],
    }
    eng._window = 1500
    assert eng.fits(one, 300) and not eng.fits(big, 300)
    run_id = (
        run_review()
    )  # the whole world through the split path: every item has a line
    assert set(lines_of(run_id)) == {"R-coat", "R-frame", "R-mark", "R-colour"}


# ---------------------------------------------------------------- the switch off / old path


def test_a_stored_plan_on_local_is_a_local_run_only_with_the_switch_on(w, monkeypatch):
    plan = {"choice": "local", "parts": [{"name": "rule_check", "engine": "local", "why": "x"},
                                         {"name": "ai_review", "engine": "local", "why": "y"}]}  # fmt: skip
    run_id, _job = s_start()
    E.record(
        db.connect(),
        run_id,
        plan,
        "adm",
        then_ai=False,
        bar_claude=True,
        now="2026-11-12T00:00:00Z",
    )
    assert E.ai_review_engine(db.connect(), run_id) == "local"
    monkeypatch.setattr(settings, "agent_review_local_engine_enabled", False)
    assert local_mod.local_run(run_id) is False
    monkeypatch.setattr(settings, "agent_review_local_engine_enabled", True)
    assert local_mod.local_run(run_id) is True
    plan["parts"][1]["engine"] = "claude"
    E.record(
        db.connect(),
        run_id,
        plan,
        "adm",
        then_ai=False,
        bar_claude=False,
        now="2026-11-12T00:00:00Z",
    )
    assert local_mod.local_run(run_id) is False
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
    contract = E.decide(
        "automatic", open_facts(kind="contract", is_contract=True, paper_approved=False)
    )
    assert (
        contract.part(E.AI_REVIEW).engine == E.NOT_RUN
    )  # no yes: no AI review at all, as before


def test_automatic_for_a_paper_that_may_not_go_to_claude_reads_it_locally():
    contract = E.decide(
        "automatic",
        open_facts(
            kind="contract",
            is_contract=True,
            paper_approved=False,
            local_ai=True,
            rules_for_kind=True,
        ),
    )
    ai = contract.part(E.AI_REVIEW)
    assert ai.engine == E.ON_LOCAL and "Claude is not used" in ai.why
    assert contract.text_leaves is False and contract.needs_yes is True
    blocked = E.decide("automatic", open_facts(blocked=True, local_ai=True))
    assert blocked.part(E.AI_REVIEW).engine == E.ON_LOCAL


def test_claude_is_still_refused_never_silently_local():
    plan = E.decide(
        "claude",
        open_facts(
            blocked=True, paper_approved=False, step_engine_claude=False, local_ai=True
        ),
    )
    assert plan.refused and plan.part(E.AI_REVIEW).engine == E.NOT_RUN


def test_automatic_still_uses_claude_when_every_door_is_open():
    assert (
        E.decide("automatic", open_facts(local_ai=True)).part(E.AI_REVIEW).engine
        == E.ON_CLAUDE
    )


def test_the_local_ai_review_is_not_offered_for_an_unknown_kind_or_with_the_reviewer_off():
    assert (
        E.decide("local", open_facts(kind=None, local_ai=True)).part(E.AI_REVIEW).engine
        == E.NOT_RUN
    )
    assert (
        E.decide("local", open_facts(agent_enabled=False, local_ai=True))
        .part(E.AI_REVIEW)
        .engine
        == E.NOT_RUN
    )
    assert (
        E.decide("local", open_facts(kind="drawing", local_ai=True))
        .part(E.AI_REVIEW)
        .engine
        == E.NOT_RUN
    )


def test_no_plan_that_runs_locally_says_text_leaves_for_any_choice_kind_or_door():
    import itertools

    for choice, kind, blocked, approved, lane_open in itertools.product(
        E.CHOICES,
        ("datasheet", "procedure", "contract"),
        (True, False),
        (True, False),
        (True, False),
    ):
        plan = E.decide(choice, open_facts(kind=kind, is_contract=kind == "contract", blocked=blocked,
                                           paper_approved=approved, lane_open=lane_open, local_ai=True))  # fmt: skip
        d = plan.as_dict()
        for part in plan.parts:
            if part.engine == E.ON_LOCAL:
                assert part.engine != E.ON_CLAUDE
        assert d["text_leaves"] == any(p.engine == E.ON_CLAUDE for p in plan.parts)


def test_the_sentence_and_cost_of_a_local_plan_say_local_zero_and_a_guess(
    w, monkeypatch
):
    import sqlite3

    plan = E.decide("local", open_facts(local_ai=True)).as_dict()
    plan["kind"] = "datasheet"
    sentence = E.sentence_of(plan)
    assert (
        "runs on the local model" in sentence
        and "No text leaves this computer" in sentence
    )
    conn = db.connect()
    assert isinstance(conn, sqlite3.Connection)
    t = local_mod.local_time(conn, s.PAPER)
    assert (
        t["minutes_guess"] is None and "cannot be made yet" in t["basis"]
    )  # no earlier run: nothing invented


def test_a_local_time_estimate_is_labelled_a_guess_and_counts_requests(w):
    run_id, _job = s_start()
    with db.connect() as conn:
        conn.execute("INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, items_total, started_at) VALUES (?,?,?,?,?,?)",
                     (run_id, s.PAPER, "datasheet", "read by code", 37, "2026-11-12"))  # fmt: skip
        t = local_mod.local_time(conn, s.PAPER)
    assert (
        t["requests"] == 20 and t["minutes_guess"] == 20
    )  # 37 rules, no second reader (that switch is off): 20 first-reader requests
    assert (
        "no second reader" in t["basis"]
        and "estimate" in t["basis"]
        and "other reviews wait" in t["basis"]
    )
    with db.connect() as conn:
        both = local_mod.local_time(conn, s.PAPER, two_readers=True)
    assert (
        both["requests"] == 29 and "second reader" in both["basis"]
    )  # counted only when the second reader is switched on


# ---------------------------------------------------------------- the follow-up and the sheet header


def test_the_sheet_header_of_a_local_ai_review_says_local_not_claude():
    from app import crs_ai_header

    assert "local model" in crs_ai_header.reviewed_by("r", ai=True, usd=0.0, local=True)
    assert crs_ai_header.reviewed_by("r", ai=True, usd=0.0) == "AI reviewer on Claude"


def test_a_two_reader_state_is_a_code_never_text():
    assert local_mod.OFF_SECOND_UNAVAILABLE != two.OFF_LEAD_UNKNOWN


# ---------------------------------------------------------------- truncation: the engine's own count decides, not the estimate


@pytest.mark.parametrize("report", ["short", "window", "missing"])
def test_a_prompt_the_engine_says_it_cut_or_did_not_report_never_gives_a_decision(
    local, two_on, report
):
    local["ollama"].report = report
    run_id = run_review()
    got = lines_of(run_id)
    assert (
        got and local["ollama"].log
    )  # requests were made, every answer was thrown away
    for ln in got.values():
        assert ln["word"] not in (
            "Pass",
            "Fail",
            "AI verdict: met",
            "AI verdict: not met",
            "AI thinks: met",
            "AI thinks: not met",
        )
        assert ln["verdict_class"] not in ("Proven by code", CLASS)
        assert (
            local_mod.LOCAL_TOO_LONG in json.loads(ln["line_json"]).get("error", "")
            or local_mod.LOCAL_TOO_LONG in ln["reason"]
        )
    counts = json.loads(run_row(run_id)["counts_json"])
    assert counts["local_answers_discarded"] > 0


def test_the_context_size_is_asked_explicitly_on_every_call_and_comes_from_the_settings(
    local, two_on, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_local_num_ctx", 12288)
    monkeypatch.setattr(settings, "agent_review_local_num_ctx_b", 16384)
    run_review()
    by_model = {}
    for b in local["ollama"].bodies:
        by_model.setdefault(b["model"], set()).add(b["options"]["num_ctx"])
    assert by_model[A_NAME] == {12288} and by_model[B_NAME] == {16384}


def test_the_default_context_size_is_the_shared_window(local):
    run_review()
    assert {b["options"]["num_ctx"] for b in local["ollama"].bodies} == {
        model_transport.shared_window()
    }


def test_a_reply_that_reports_the_whole_prompt_is_used():
    text = "word " * 600  # about 3,000 characters
    assert local_mod._cut_prompt(900, 8192, text) is None
    assert local_mod._cut_prompt(None, 8192, text) == "prompt size not reported"
    assert (
        local_mod._cut_prompt(5000, 8192, text) == "prompt at or near the window"
    )  # the engine reports BELOW the window when it cuts
    assert (
        local_mod._cut_prompt(10, 8192, text) == "prompt shorter than the request needs"
    )
    assert local_mod._cut_prompt(True, 8192, text) == "prompt size not reported"


# ---------------------------------------------------------------- R51 F1/F2: the estimate decides what is sent, the engine's count is the second net


NUMERIC_PAGE = "\n".join(
    f"{i:03d}  30.0000  {i * 7.31:08.4f}  12.5000  0.0010  {i * 3}" for i in range(260)
)[:10500]


def numeric_parts(text=NUMERIC_PAGE):
    return {
        "system": [{"type": "text", "text": "You review."}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}],
    }


def test_a_numeric_page_the_old_three_characters_a_token_rule_would_send_is_not_sent():
    from app import context_budget

    assert len(NUMERIC_PAGE) == 10500
    old_rule = (
        len(NUMERIC_PAGE) // 3 + 1 + 1000 + 256
    )  # what chars // 3 said: it fits the 8192 window
    assert old_rule < 8192
    assert (
        context_budget.estimate_tokens(NUMERIC_PAGE) > 8192
    )  # the repo's fail-safe estimate says it does not
    sent = []
    eng = local_mod.LocalEngine(
        A_NAME,
        B_NAME,
        post=lambda *a, **k: sent.append(1) or {},
        show=lambda m: SHOWS.get(m),
    )
    with pytest.raises(agent_claude.AgentBadReply) as caught:
        eng.call(A_NAME, numeric_parts(), 1000)
    assert (
        caught.value.code == local_mod.LOCAL_TOO_LONG and sent == []
    )  # nothing reached the engine
    assert eng.stats()["local_not_asked_too_long"] == 1


def test_an_engine_that_reports_a_cut_prompt_below_the_window_is_never_an_answer(
    monkeypatch,
):
    from app import context_budget

    monkeypatch.setattr(
        context_budget, "estimate_tokens", lambda _t: 10
    )  # an estimate that under-counted: the second net must catch it
    window = 8192

    def cut(
        path, body, *, timeout
    ):  # what the engine really does on an overflow: it keeps part and reports a count below the window
        return {
            "model": A_NAME,
            "message": {"content": '{"answers": []}'},
            "done_reason": "stop",
            "prompt_eval_count": int(window * 0.67),
        }

    eng = local_mod.LocalEngine(
        A_NAME, B_NAME, post=cut, show=lambda m: SHOWS.get(m), window=window
    )
    with pytest.raises(agent_claude.AgentBadReply) as caught:
        eng.call(A_NAME, numeric_parts(), 1000)
    assert caught.value.code == local_mod.LOCAL_TOO_LONG
    assert eng.stats()["local_answers_discarded"] == 1


def test_a_reported_shortfall_never_yields_met_or_not_met_in_a_run(local, two_on):
    local["ollama"].report = "window"
    got = lines_of(run_review())
    assert all(
        ln["word"]
        not in (
            "AI verdict: met",
            "AI verdict: not met",
            "AI thinks: met",
            "AI thinks: not met",
            "Pass",
            "Fail",
        )
        for ln in got.values()
    )


# ---------------------------------------------------------------- R51 F5, F6: progress and a busy computer


def test_every_local_request_beats_the_heartbeat_and_says_question_k_of_n_reader_r_of_2(
    local, two_on, monkeypatch
):
    from app import worker_review

    beats, labels = [], []
    monkeypatch.setattr(worker_review, "beat_now", lambda: beats.append(1) or 0.0)
    monkeypatch.setattr(local_mod, "progress_writer", lambda _run: labels.append)
    run_review()
    assert len(beats) >= len(local["ollama"].log) > 0
    assert any(
        re.fullmatch(
            r"asking the local AI reviewer: question \d+ of \d+, reader 1 of 2", x
        )
        for x in labels
    )
    assert any(
        re.fullmatch(
            r"asking the local AI reviewer: question \d+ of \d+, reader 2 of 2", x
        )
        for x in labels
    )


def test_a_computer_held_by_another_heavy_job_stops_the_run_in_plain_words(
    local, monkeypatch
):
    import contextlib

    @contextlib.contextmanager
    def busy(*_a, **_k):
        raise local_mod.heavy_lock.HeavyJobBusy({"kind": "p1"}, 1800.0)
        yield

    monkeypatch.setattr(local_mod.heavy_lock, "held", busy)
    run_id = run_review()
    stop = run_row(run_id)["stop_reason"]
    assert (
        stop == "another heavy job held the computer for 30 minutes; start again later"
    )
    assert "HeavyJobBusy" not in stop and local["ollama"].log == []


# ---------------------------------------------------------------- R51 F7: the sheet says nothing was asked


def _cells(path):
    import openpyxl

    wb = openpyxl.load_workbook(path)
    return [
        str(c.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if c.value is not None
    ]


def test_a_not_asked_line_reads_on_the_built_sheets_as_not_asked_never_as_a_failed_call(
    local, monkeypatch
):
    monkeypatch.setattr(
        model_transport, "shared_window", lambda: 900
    )  # nothing fits: every item is "not asked"
    run_id = run_review()
    folder = agent_review_jobs.run_dir(run_id)
    internal, contractor = (
        _cells(folder / "crs-internal.xlsx"),
        _cells(folder / "crs-contractor.xlsx"),
    )
    assert "Not asked: too long for the local model. Not reviewed." in internal
    for cell in [*internal, *contractor]:
        assert "AI call failed" not in cell and "the AI call failed" not in cell
    line = next(iter(lines_of(run_id).values()))
    assert json.loads(line["line_json"])["reason_code"] == "not_asked_too_long"


# ---------------------------------------------------------------- R51 F4: other jobs and the chat


def test_only_the_models_this_run_loaded_are_unloaded_and_the_chat_menu_says_a_review_is_running(
    monkeypatch,
):
    dropped = []
    eng = local_mod.LocalEngine(
        A_NAME,
        B_NAME,
        post=lambda *a, **k: {},
        unload=dropped.append,
        show=lambda m: SHOWS.get(m),
    )
    monkeypatch.setattr(
        local_mod.heavy_lock,
        "held",
        lambda *a, **k: __import__("contextlib").nullcontext(),
    )
    with eng.session():
        eng.used.add(A_NAME)  # this run only ever loaded the first model
    assert (
        dropped == [A_NAME]
    )  # a model the run never loaded (the second, or the chat's) is never unloaded from here
    import os
    import time

    from app import chat_model

    monkeypatch.setattr(
        local_mod.heavy_lock,
        "read",
        lambda *a, **k: {
            "kind": local_mod.LOCK_KIND,
            "started_epoch": time.time(),
            "pid": os.getpid(),
            "host": "x",
        },
    )
    monkeypatch.setattr(local_mod.heavy_lock, "is_stale", lambda *a, **k: False)
    local_option = next(
        m for m in chat_model.available_models()["models"] if m["id"] == "local"
    )
    assert (
        local_option["reason"] == "A local review is running; answers may be slower."
        and local_option["available"] is True
    )
    monkeypatch.setattr(local_mod.heavy_lock, "read", lambda *a, **k: None)
    assert (
        next(m for m in chat_model.available_models()["models"] if m["id"] == "local")[
            "reason"
        ]
        is None
    )


# ---------------------------------------------------------------- R51 F8: the plan says what will and will not run


def test_a_contract_or_procedure_with_no_rules_of_its_kind_is_not_planned_as_an_ai_review_on_local():
    for kind in ("contract", "procedure"):
        plan = E.decide(
            "local",
            open_facts(
                kind=kind,
                is_contract=kind == "contract",
                local_ai=True,
                rules_for_kind=False,
            ),
        )
        ai = plan.part(E.AI_REVIEW)
        assert (
            ai.engine == E.NOT_RUN
            and "general review" in ai.why
            and "does not run on the local model yet" in ai.why
        )
        assert (
            E.decide(
                "automatic",
                open_facts(
                    kind=kind,
                    is_contract=kind == "contract",
                    paper_approved=False,
                    local_ai=True,
                ),
            )
            .part(E.AI_REVIEW)
            .engine
            == E.NOT_RUN
        )


def test_a_contract_with_rules_of_its_kind_says_the_rules_run_and_the_general_review_does_not():
    plan = E.decide(
        "local",
        open_facts(
            kind="contract", is_contract=True, local_ai=True, rules_for_kind=True
        ),
    )
    ai = plan.part(E.AI_REVIEW)
    assert (
        ai.engine == E.ON_LOCAL
        and "rules of this kind" in ai.why
        and "general review" in ai.why
        and "does not run on the local model yet" in ai.why
    )
    sentence = E.sentence_of({**plan.as_dict(), "kind": "contract"})
    assert "does not run on the local model yet" in sentence


def test_the_plan_of_a_datasheet_on_local_carries_the_wait_words_and_an_estimate(w):
    plan = E.decide("local", open_facts(local_ai=True)).as_dict()
    assert plan["parts"][1]["engine"] == "local"
    t = local_mod.local_time(db.connect(), s.PAPER)
    assert (
        "other reviews wait behind it" in t["basis"]
        and "chat answers may be slower" in t["basis"]
    )


def test_the_contractor_comment_of_a_not_asked_line_says_not_asked_not_a_failed_call():
    from app import agent_review_crs as crs

    base = {
        "item_id": "R-1",
        "paper_page": 1,
        "reason_code": "not_asked_too_long",
        "error": local_mod.LOCAL_TOO_LONG,
        "verdict": "Query",
    }
    said = crs.company_comment(base, contractor=True)
    assert (
        "(Not asked: too long for the local model. Not reviewed.)" in said
        and "AI call failed" not in said
    )
    failed = crs.company_comment(
        {**base, "reason_code": "ai_call_failed", "error": "transport_x"},
        contractor=True,
    )
    assert (
        "(Not reviewed: the AI call failed.)" in failed
    )  # a real failure keeps its words


# ---------------------------------------------------------------- Automatic when Claude refuses every call (the account limit)


def _ledger(monkeypatch, lines):
    from app import claude_spend

    monkeypatch.setattr(claude_spend, "_raw_lines", lambda: lines)


def _at(minutes_ago):
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(
        timespec="seconds"
    )


def test_a_standing_refusal_is_the_newest_account_level_rejection_with_no_success_after_it(
    monkeypatch,
):
    from app import claude_standing_refusal as ref

    refusal = {
        "at": _at(5),
        "releases": "r1",
        "step": "agent_review",
        "reason": "unbilled:HTTPStatusError:http_400:no_credit",
    }
    _ledger(monkeypatch, [refusal])
    assert ref.standing() is True
    _ledger(
        monkeypatch,
        [{**refusal, "reason": "unbilled:HTTPStatusError:http_429:rate_limit_error"}],
    )
    assert ref.standing() is True
    _ledger(
        monkeypatch,
        [refusal, {"at": _at(1), "settles": "r2", "finish_reason": "end_turn"}],
    )
    assert ref.standing() is False  # a call went through after it
    _ledger(monkeypatch, [{**refusal, "at": _at(60 * 30)}])
    assert ref.standing() is False  # older than a day
    _ledger(monkeypatch, [{**refusal, "reason": "unbilled:ReaderRefused"}])
    assert (
        ref.standing() is False
    )  # a refusal made here (a closed flag) is not the account's
    _ledger(monkeypatch, [])
    assert ref.standing() is False


def test_automatic_resolves_to_local_with_one_plain_sentence_when_claude_refuses_every_call():
    plan = E.decide("automatic", open_facts(claude_refused=True, local_ai=True))
    ai = plan.part(E.AI_REVIEW)
    assert (
        ai.engine == E.ON_LOCAL and plan.refused is None and plan.text_leaves is False
    )
    assert ai.why.startswith(
        "Claude cannot be used now, so this review runs on this computer"
    )
    assert plan.part(E.RULE_CHECK).engine == E.ON_LOCAL
    sentence = E.sentence_of({**plan.as_dict(), "kind": "datasheet"})
    assert "Claude cannot be used now, so this review runs on this computer" in sentence


def test_a_refusing_claude_never_yields_a_failed_start_for_automatic_and_still_refuses_the_claude_choice():
    off = E.decide(
        "automatic", open_facts(claude_refused=True)
    )  # the local switch is off: the rule check runs, the AI review does not, no refusal
    assert off.refused is None and off.part(E.AI_REVIEW).engine == E.NOT_RUN
    assert "Claude cannot be used now" in off.part(E.AI_REVIEW).why
    chosen = E.decide(
        "claude",
        open_facts(claude_refused=True, step_engine_claude=False, local_ai=True),
    )
    assert (
        chosen.refused and chosen.part(E.AI_REVIEW).engine == E.NOT_RUN
    )  # never a silent fallback when Claude was asked for


def test_read_facts_reads_the_standing_refusal(w, monkeypatch):
    from app import claude_spend

    monkeypatch.setattr(
        claude_spend,
        "_raw_lines",
        lambda: [
            {
                "at": _at(2),
                "releases": "r",
                "step": "s",
                "reason": "unbilled:HTTPStatusError:http_400:no_credit",
            }
        ],
    )
    facts, _reading = E.read_facts(db.connect(), s.PAPER, frozenset({s.PAPER}))
    assert facts.claude_refused is True
