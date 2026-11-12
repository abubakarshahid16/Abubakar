"""C4 (owner order 13): a second reader re-reads the page before a line says the paper is silent (invented paper and models).

The fake lane answers the lead from a table; a page re-read (system text starts PAGE RE-READ) from `REREAD`, and counts it."""

from __future__ import annotations

import json

import pytest

from app import (
    agent_claude,
    agent_review_jobs,
    agent_review_kind,
    db,
    nothing_read,
)
from app import agent_review_items as items_mod
from app import agent_review_reread as rr
from app import agent_review_run as run_mod
from app import agent_review_verdict as V
from app import agent_review_wording as W
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_job import lines_of, reading, run_job, start

SILENT = {
    "paper_page": 1,
    "paper_quote": "",
    "clause_quote": "",
    "reasoning": "nothing about it on the sheet",
    "comment": "state it",
    "verdict": "Query",
    "reason_code": "sheet_silent",
    "field_label": "Coating thickness",
}
FOUND_NUMBER = {
    "found": True,
    "paper_page": 1,
    "paper_quote": "Coating thickness: 0.35 mm",
    "paper_figure": "Coating thickness: 0.35 mm",
    "clause_quote": s.RULES["R-frame"][0],
    "clause_figure": "coating thickness shall be at least 0.2 mm",
    "meets": True,
    "reasoning": "the sheet states 0.35 mm",
    "comment": "",
}
FOUND_TEXT = {
    "found": True,
    "paper_page": 1,
    "paper_quote": "Coating layers two",
    "clause_quote": s.RULES["R-coat"][0],
    "meets": True,
    "reasoning": "two layers are stated",
    "comment": "",
}


class ReLane(s.FakeModel):
    """FakeModel plus the page re-read: `reread` is what the second reader says (a dict, text, or an exception to raise)."""

    def __init__(self, reread=None, **kw):
        super().__init__(**kw)
        self.reread = reread
        self.reread_bodies: list[dict] = []

    def __call__(self, url, *, headers, body, timeout):
        if "PAGE RE-READ" in json.dumps(body.get("system")):
            with self._lock:
                self.kinds.append("reread")
                self.reread_bodies.append(body)
            if isinstance(self.reread, BaseException):
                raise self.reread
            text = (
                self.reread if isinstance(self.reread, str) else json.dumps(self.reread)
            )
            usage = {"input_tokens": 1500, "output_tokens": 120}
            return self._reply(self.second_name, usage, text)
        return super().__call__(url, headers=headers, body=body, timeout=timeout)


@pytest.fixture
def w(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "agent_review_reread_silent_enabled", True)
    state = {"fake": ReLane(), "kind": reading()}
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (state["fake"], s.ENV))
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: state["kind"])
    monkeypatch.setattr(
        agent_review_jobs, "_scope_run_id", lambda _c, _s, run_id, *_a: run_id
    )
    monkeypatch.setattr(nothing_read, "read_phase", lambda *_a: None)
    state["doc"], state["cache"] = s.item_doc()

    def build(_conn, _paper, _kind, *, cache=None, **kw):
        cache.update(state["cache"])
        return state["doc"]

    monkeypatch.setattr(items_mod, "build_items", build)
    with db.connect() as conn:
        s.label_rows(conn, [i["item_id"] for i in state["doc"]["items"]])
    return state


def review(w, answers, reread):
    w["fake"] = ReLane(reread=reread, answers=answers)
    run_id, job_id = start()
    run_job(job_id)
    return lines_of(run_id), w["fake"]


def line_json(row):
    return json.loads(row["line_json"])


# ---------------------------------------------------------------- the step decides the line again by the same gate


def test_a_silent_number_line_with_a_verified_quote_is_decided_again_by_code(w):
    answers = {**s.ANSWERS, "R-frame": SILENT}
    lines, fake = review(w, answers, FOUND_NUMBER)
    row = lines["R-frame"]
    assert (row["word"], row["verdict_class"]) == ("Pass", "Proven by code")
    stored = line_json(row)
    assert stored["decided_by"] == V.BY_CODE and stored["compare"]["decided"] is True
    assert stored["paper_quote"] == FOUND_NUMBER["paper_quote"]
    assert stored["reread"]["found"] is True and stored["reread"]["pages"] == [1]
    assert fake.kinds.count("reread") == 1


def test_a_silent_number_line_the_gate_cannot_pass_stays_unproven_with_the_same_gate_reason(
    w,
):
    bad = {**FOUND_NUMBER, "paper_figure": "a figure that is not in the quote 9 mm"}
    lines, _ = review(w, {**s.ANSWERS, "R-frame": SILENT}, bad)
    row = lines["R-frame"]
    assert row["word"] not in ("Pass", "Fail")
    assert "no figure with its unit inside both quotes" in row["reason"]


def test_a_text_line_is_never_proven_by_the_second_reader_alone(w):
    answers = {**s.ANSWERS, "R-coat": {**SILENT, "paper_quote": ""}}
    lines, fake = review(w, answers, FOUND_TEXT)
    row = lines["R-coat"]
    assert row["word"] == "AI thinks: met"  # never Pass: no independent second opinion
    assert row["verdict_class"] == "AI opinion, engineer to confirm"
    # the second model is the reader here, so the gate bought no second opinion of its own for this line
    assert (
        fake.kinds.count("second") == 1
    )  # R-mark's own Fail only; the re-read line bought none
    assert fake.kinds.count("reread") == 1


# ---------------------------------------------------------------- what keeps the Query


def test_the_second_reader_finds_nothing_the_line_says_two_readers_found_no_value(w):
    lines, fake = review(
        w, {**s.ANSWERS, "R-frame": SILENT}, {"found": False, "paper_quote": ""}
    )
    row = lines["R-frame"]
    assert row["word"] == "Query" and row["verdict_class"] == "Query for the engineer"
    assert W.REREAD_NO_VALUE_WHY in row["reason"]
    assert line_json(row)["reread"]["found"] is False
    assert fake.kinds.count("reread") == 1


def test_a_quote_that_is_not_on_the_page_keeps_the_query_with_the_two_readers_words(w):
    invented = {**FOUND_NUMBER, "paper_quote": "Coating thickness: 9.99 mm"}
    lines, _ = review(w, {**s.ANSWERS, "R-frame": SILENT}, invented)
    row = lines["R-frame"]
    assert row["word"] == "Query"
    assert W.REREAD_NO_VALUE_WHY in row["reason"]


def test_a_silent_line_of_a_failed_call_is_exactly_the_old_query_with_no_claim(w):
    lines, fake = review(
        w, {**s.ANSWERS, "R-frame": SILENT}, agent_claude.AgentTransportError("boom")
    )
    row = lines["R-frame"]
    assert row["word"] == "Query"
    assert "two AI readers" not in row["reason"]
    assert line_json(row)["reread"]["found"] is None
    assert fake.kinds.count("reread") == 1  # one call, never sent again


def test_an_unreadable_answer_is_the_old_query_with_no_claim(w):
    lines, _ = review(w, {**s.ANSWERS, "R-frame": SILENT}, "not json at all")
    row = lines["R-frame"]
    assert row["word"] == "Query" and "two AI readers" not in row["reason"]


def test_a_refused_call_ends_the_optional_step_and_never_stops_the_run(w, monkeypatch):
    real = run_mod.Runner.call

    def refuse(self, model, parts, max_tokens, once=False):
        if model == agent_claude.SECOND_MODEL and "PAGE RE-READ" in json.dumps(
            parts.get("system")
        ):
            raise agent_claude.AgentBudgetStop("cap")
        return real(self, model, parts, max_tokens, once)

    monkeypatch.setattr(run_mod.Runner, "call", refuse)
    answers = {**s.ANSWERS, "R-frame": SILENT, "R-coat": SILENT}
    lines, fake = review(w, answers, FOUND_NUMBER)
    assert lines["R-frame"]["word"] == "Query" and lines["R-coat"]["word"] == "Query"
    assert "two AI readers" not in lines["R-frame"]["reason"]
    assert lines["R-mark"]["verdict_class"] != "Not reviewed"  # the run went on
    assert fake.kinds.count("reread") == 0


# ---------------------------------------------------------------- the bound: one call per silent line, none otherwise


def test_exactly_one_extra_call_per_silent_line_and_none_for_the_others(w):
    answers = {
        **s.ANSWERS,
        "R-frame": SILENT,
        "R-coat": {
            **SILENT,
            "reason_code": "absent",
            "verdict": "Fail",
            "pages_searched": [1],
        },
        "R-colour": {**SILENT, "reason_code": "needs_drawing_or_calc"},
    }
    lines, fake = review(w, answers, {"found": False})
    assert fake.kinds.count("reread") == 2  # R-frame (sheet_silent) and R-coat (absent)
    # R-mark (a Fail with quotes), R-colour (needs a drawing): no call
    assert "reread" not in line_json(lines["R-mark"])
    assert "reread" not in line_json(lines["R-colour"])


def test_the_switch_is_off_by_default_and_then_no_call_is_made(w, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_reread_silent_enabled", False)
    lines, fake = review(w, {**s.ANSWERS, "R-frame": SILENT}, FOUND_NUMBER)
    assert fake.kinds.count("reread") == 0
    assert lines["R-frame"]["word"] == "Query" and "reread" not in line_json(
        lines["R-frame"]
    )
    assert (
        type(settings).model_fields["agent_review_reread_silent_enabled"].default
        is False
    )


def test_the_request_carries_only_the_chosen_page_text_and_the_field_and_a_named_limit(
    w,
):
    _, fake = review(w, {**s.ANSWERS, "R-frame": SILENT}, {"found": False})
    body = fake.reread_bodies[0]
    assert body["max_tokens"] == rr.REREAD_MAX_TOKENS
    text = json.dumps(body["messages"])
    assert s.PAPER_PAGE.splitlines()[1] in text  # the whole stored page text
    assert text.count("<paper ") == 1


def test_a_rule_that_is_not_approved_buys_no_page_read(w, monkeypatch):
    w["doc"]["items"] = [
        {**i, "rule_tier": V.RULE_NOT_APPROVED} if i["item_id"] == "R-frame" else i
        for i in w["doc"]["items"]
    ]
    lines, fake = review(w, {**s.ANSWERS, "R-frame": SILENT}, FOUND_NUMBER)
    assert fake.kinds.count("reread") == 0
    assert lines["R-frame"]["word"] != "Pass"


# ---------------------------------------------------------------- pure parts


def test_silent_cause_names_each_exit_and_nothing_else():
    q = {"verdict": V.QUERY}
    assert rr.silent_cause({**q, "reason_code": "sheet_silent"}) == "sheet_silent"
    assert rr.silent_cause({**q, "reason_code": "absent"}) == "absent"
    assert (
        rr.silent_cause({**q, "reason_code": "absent_pages_not_named"})
        == "absent_pages_not_named"
    )
    assert rr.silent_cause({**q, "reason_code": "needs_drawing_or_calc"}) is None
    assert rr.silent_cause({**q, "reason_code": "unclear_clause"}) is None
    assert rr.silent_cause({**q, "reason_code": "not_applicable"}) is None
    assert rr.silent_cause({**q, "reason_code": "sheet_silent", "error": "x"}) is None
    assert rr.silent_cause({"verdict": V.PASS, "reason_code": "absent"}) is None
    no_value = {
        **q,
        "ai_verdict": V.PASS,
        "reason_code": "met",
        "quotes_checked": {"paper": True, "clause": True},
        "paper_quote": "Coating thickness",
        "field_label_ai": "Coating thickness",
    }
    assert rr.silent_cause(no_value) == "no_value"
    assert rr.silent_cause({**no_value, "not_mentioned_hold": True}) == "not_stated"


def test_the_two_readers_words_state_only_what_the_code_saw():
    banned = (
        "the paper gives",
        "the paper does not",
        "the paper says",
        "the paper is",
        "the paper has",
    )
    assert not any(b in W.REREAD_NO_VALUE_WHY.lower() for b in banned)
    base = {"verdict": V.QUERY, "reason_code": "sheet_silent", "ai_verdict": V.QUERY}
    for reread, said in (
        ({"found": False}, True),
        ({"found": None}, False),
        ({"found": True}, False),
    ):
        out = W.apply({**base, "reread": reread})
        assert (W.REREAD_NO_VALUE_WHY in str(out["not_proven_reason"])) is said
    twice = W.apply(W.apply({**base, "reread": {"found": False}}))
    assert twice["not_proven_reason"].count(W.REREAD_NO_VALUE_WHY) == 1


def test_a_page_choice_is_bounded_cited_first_then_the_best_hint_pages():
    class Pages:
        texts = {  # noqa: RUF012
            n: f"page {n} coating thickness" if n in (2, 5, 7) else f"page {n} filler"
            for n in range(1, 9)
        }

        def page(self, _doc, n):
            return self.texts.get(n)

    class Host(rr.RereadMixin):
        paper, total_pages, pages = "p", 8, Pages()

    item = {
        "page_hint": list(range(1, 9)),
        "question": "coating thickness",
        "field_roles": [],
    }
    host = Host()
    assert host.reread_pages(item, {"paper_page": 4}) == [
        4
    ]  # the page the first reader cited
    chosen = host.reread_pages(item, {"paper_page": None})
    assert len(chosen) == rr.REREAD_MAX_PAGES == 3 and chosen == [2, 5, 7]
    assert host.reread_pages(item, {"paper_page": 99}) == [
        2,
        5,
        7,
    ]  # a page the paper does not have is not cited
