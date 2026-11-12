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
from app import agent_review_request as request_mod
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

    def __init__(self, reread=None, again=None, **kw):
        super().__init__(**kw)
        self.reread = reread
        self.again = (
            again or {}
        )  # the lead's answer per item when it is asked again with the pointer
        self.reread_bodies: list[dict] = []
        self.asked_again: list[str] = []

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
        last = (
            body["messages"][0]["content"][-1]["text"] if body.get("messages") else ""
        )
        if "a_second_reader_points_to" in last:
            ids = [
                q["item_id"]
                for q in json.loads(last.split("\n\n", 1)[1].split("\n\n")[0])["items"]
            ]
            with self._lock:
                self.kinds.append("lead_again")
                self.asked_again += ids
            got = [{"item_id": i, **self.again[i]} for i in ids if i in self.again]
            usage = {"input_tokens": 1200, "output_tokens": 300}
            return self._reply(self.LEAD, usage, json.dumps({"answers": got}))
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


def review(w, answers, reread, again=None):
    w["fake"] = ReLane(reread=reread, answers=answers, again=again)
    run_id, job_id = start()
    run_job(job_id)
    return lines_of(run_id), w["fake"]


def line_json(row):
    return json.loads(row["line_json"])


# ---------------------------------------------------------------- the step: re-read, lead asked again, normal gate


AGAIN_NUMBER = {"R-frame": s.ANSWERS["R-frame"]}
AGAIN_TEXT = {"R-coat": s.ANSWERS["R-coat"]}


def test_a_recovered_number_line_has_two_readers_behind_it_and_is_decided_by_code(w):
    answers = {**s.ANSWERS, "R-frame": SILENT}
    lines, fake = review(w, answers, FOUND_NUMBER, AGAIN_NUMBER)
    row = lines["R-frame"]
    assert (row["word"], row["verdict_class"]) == ("Pass", "Proven by code")
    stored = line_json(row)
    assert stored["decided_by"] == V.BY_CODE and stored["compare"]["decided"] is True
    assert stored["reread"]["outcome"] == "recovered" and stored["reread"]["pages"] == [
        1
    ]
    assert fake.kinds.count("reread") == 1 and fake.asked_again == ["R-frame"]


def test_the_lead_is_asked_again_with_the_page_and_the_pointer_and_no_other_page(w):
    _, fake = review(w, {**s.ANSWERS, "R-frame": SILENT}, FOUND_NUMBER, AGAIN_NUMBER)
    assert fake.asked_again == ["R-frame"]


def test_a_recovered_text_line_gets_the_normal_second_opinion_and_may_then_be_proven(w):
    answers = {**s.ANSWERS, "R-coat": SILENT}
    lines, fake = review(w, answers, FOUND_TEXT, AGAIN_TEXT)
    assert lines["R-coat"]["word"] == "Pass"
    assert fake.kinds.count("second") == 2  # R-mark's Fail and the recovered R-coat
    assert fake.kinds.count("lead_again") == 1


def test_a_recovered_text_line_whose_second_opinion_disagrees_stays_the_old_query_with_the_pointer_words(
    w,
):
    answers = {**s.ANSWERS, "R-coat": SILENT}
    w["fake"] = ReLane(
        reread=FOUND_TEXT, answers=answers, again=AGAIN_TEXT, agree=False
    )
    run_id, job_id = start()
    run_job(job_id)
    row = lines_of(run_id)["R-coat"]
    assert row["word"] == "Query"
    assert W.REREAD_NOT_CONFIRMED_WHY.format(page=1) in row["reason"]
    assert line_json(row)["reread"]["outcome"] == "not_confirmed"


def test_no_line_is_met_or_proven_on_one_readers_word(w):
    """The lead says silent again after the pointer: the second reader's quote alone never makes a met, Pass or Fail."""
    for item_id, found in (("R-frame", FOUND_NUMBER), ("R-coat", FOUND_TEXT)):
        answers = {**s.ANSWERS, item_id: SILENT}
        lines, _ = review(w, answers, found, {item_id: SILENT})
        row = lines[item_id]
        assert row["word"] == "Query", item_id
        assert W.REREAD_NOT_CONFIRMED_WHY.format(page=1) in row["reason"]
        assert "met" not in row["word"]


def test_a_recovered_number_line_the_gate_cannot_pass_stays_unproven_with_the_gate_reason(
    w,
):
    bad = {
        "R-frame": {
            **s.ANSWERS["R-frame"],
            "paper_figure": "a figure that is not in the quote 9 mm",
        }
    }
    lines, _ = review(w, {**s.ANSWERS, "R-frame": SILENT}, FOUND_NUMBER, bad)
    assert lines["R-frame"]["word"] not in ("Pass", "Fail")


# ---------------------------------------------------------------- what keeps the Query


def test_the_second_reader_finds_nothing_the_line_says_two_readers_found_no_value(w):
    lines, fake = review(
        w, {**s.ANSWERS, "R-frame": SILENT}, {"found": False, "paper_quote": ""}
    )
    assert fake.kinds.count("lead_again") == 0
    row = lines["R-frame"]
    assert row["word"] == "Query" and row["verdict_class"] == "Query for the engineer"
    assert W.REREAD_NO_VALUE_WHY in row["reason"]
    assert line_json(row)["reread"]["outcome"] == "no_value"
    assert fake.kinds.count("reread") == 1


def test_a_quote_that_is_not_on_the_page_is_not_used_and_never_says_no_value_was_found(
    w,
):
    invented = {**FOUND_NUMBER, "paper_quote": "Coating thickness: 9.99 mm"}
    lines, fake = review(w, {**s.ANSWERS, "R-frame": SILENT}, invented, AGAIN_NUMBER)
    row = lines["R-frame"]
    assert row["word"] == "Query"
    assert W.REREAD_QUOTE_NOT_FOUND_WHY in row["reason"]
    assert W.REREAD_NO_VALUE_WHY not in row["reason"]
    assert fake.kinds.count("lead_again") == 0  # an unverified quote buys no lead call


def test_a_silent_line_of_a_failed_call_is_exactly_the_old_query_with_no_claim(w):
    lines, fake = review(
        w, {**s.ANSWERS, "R-frame": SILENT}, agent_claude.AgentTransportError("boom")
    )
    row = lines["R-frame"]
    assert row["word"] == "Query"
    assert "two AI readers" not in row["reason"]
    assert line_json(row)["reread"]["outcome"] == "failed"
    assert fake.kinds.count("reread") == 1  # one call, never sent again
    assert (
        row["reason"]
        == W.apply({**line_json(row), "reread": None})["not_proven_reason"]
    )
    assert (
        line_json(row)["usd"] > 0
    )  # the failed call is charged to the line (its reserved worst case)


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


BANNED = (
    "the paper gives",
    "the paper does not",
    "the paper says",
    "the paper is",
    "the paper has",
)


def test_every_why_constant_of_the_wording_module_is_in_the_banned_phrase_scope():
    found = {
        n: getattr(W, n)
        for n in dir(W)
        if n.endswith("_WHY") and isinstance(getattr(W, n), str)
    }
    assert {
        "REREAD_NO_VALUE_WHY",
        "REREAD_QUOTE_NOT_FOUND_WHY",
        "REREAD_NOT_CONFIRMED_WHY",
    } <= set(found)
    for name, text in found.items():
        if (
            name != "SILENCE_WHY"
        ):  # the owner's own wording for a silent paper, exempt in the verdict test too
            assert not any(b in text.lower() for b in BANNED), (name, text)


def test_each_outcome_has_its_own_words_and_a_failed_or_recovered_line_says_nothing():
    base = {"verdict": V.QUERY, "reason_code": "sheet_silent", "ai_verdict": V.QUERY}
    said = {
        "no_value": W.REREAD_NO_VALUE_WHY,
        "quote_not_found": W.REREAD_QUOTE_NOT_FOUND_WHY,
        "not_confirmed": W.REREAD_NOT_CONFIRMED_WHY.format(page=3),
    }
    for outcome, words in said.items():
        out = W.apply({**base, "reread": {"outcome": outcome, "page": 3}})
        assert words in out["not_proven_reason"], outcome
        others = [x for x in said.values() if x != words]
        assert not any(x in out["not_proven_reason"] for x in others)
    for outcome in ("failed", "recovered", None):
        out = W.apply({**base, "reread": {"outcome": outcome}})
        assert not any(x in str(out["not_proven_reason"]) for x in said.values())
    twice = W.apply(W.apply({**base, "reread": {"outcome": "no_value"}}))
    assert twice["not_proven_reason"].count(W.REREAD_NO_VALUE_WHY) == 1


def test_the_step_does_not_run_when_the_lead_is_unknown_or_the_same_family(
    w, monkeypatch
):
    answers = {**s.ANSWERS, "R-frame": SILENT}
    monkeypatch.setattr(
        agent_claude, "SECOND_MODEL", ReLane.LEAD
    )  # the second model IS the lead's family
    lines, fake = review(w, answers, FOUND_NUMBER, AGAIN_NUMBER)
    assert fake.kinds.count("reread") == 0 and "reread" not in line_json(
        lines["R-frame"]
    )
    monkeypatch.undo()
    monkeypatch.setattr(settings, "agent_review_reread_silent_enabled", True)

    class Host(rr.RereadMixin):
        reread_enabled, _stop = True, type("E", (), {"is_set": lambda self: False})()
        tier_lookup = None

    line = {"verdict": V.QUERY, "reason_code": "sheet_silent", "usd": 0.1}
    item = {"item_id": "x", "rule_label": {"tier": "AI approved"}}
    assert (
        Host().reread_silent_line(item, line, None, None) is line
    )  # an unknown lead: no call


def test_a_resumed_silent_line_is_not_asked_again_and_not_re_read(w):
    silent = {
        "item_id": "R-frame",
        "verdict": V.QUERY,
        "reason_code": "sheet_silent",
        "ai_verdict": "Query",
    }
    fake = ReLane(reread=FOUND_NUMBER, again=AGAIN_NUMBER)
    pages = type(
        "P", (), {"page": lambda self, d, n: s.PAPER_PAGE, "count": lambda self, d: 1}
    )()
    runner = run_mod.Runner(
        paper=s.PAPER, items=[s.item("R-frame")], pages=pages,
        clauses=request_mod.ClauseCache({}), model=agent_claude.LEAD_MODEL, send=fake,
        done_lines={"R-frame": silent}, reread_silent=True,
    )  # fmt: skip
    assert runner.todo() == []
    assert fake.kinds == []


def test_with_the_switch_off_every_stored_line_equals_the_line_without_the_step(
    w, monkeypatch
):
    answers = {**s.ANSWERS, "R-frame": SILENT}
    monkeypatch.setattr(settings, "agent_review_reread_silent_enabled", False)
    off, _ = review(w, answers, FOUND_NUMBER, AGAIN_NUMBER)
    monkeypatch.setattr(
        run_mod.Runner, "reread_silent_line", lambda self, it, ln, lm, bx: ln
    )
    db.reset_connection()
    stripped, _ = review(w, answers, FOUND_NUMBER, AGAIN_NUMBER)

    def strip(rows):
        return {k: json.loads(v["line_json"]) for k, v in rows.items()}

    assert strip(off) == strip(stripped)


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


# ---------------------------------------------------------------- the optional step never stops the review


def _line_dicts(rows):
    """Stored lines without the step's own marker (`reread`) and the cost of calls the refused step had already paid."""
    out = {k: json.loads(v["line_json"]) for k, v in rows.items()}
    for ln in out.values():
        ln.pop("reread", None)
        ln.pop("usd", None)
    return out


def _refuse_in_step(monkeypatch, where):
    """A cap refusal on one paid call inside the optional step ("lead": the re-ask; "second": the recovered line's second opinion)."""
    real_call, real_second = (
        run_mod.Runner.call,
        agent_claude.ClaudeProvider.second_opinion,
    )

    def call(self, model, parts, max_tokens, once=False):
        if where == "lead" and "a_second_reader_points_to" in json.dumps(
            parts["messages"]
        ):
            raise agent_claude.AgentBudgetStop("cap")
        return real_call(self, model, parts, max_tokens, once)

    def second(self, *a, **k):
        if where == "second" and run_mod.Runner._optional.on:
            raise agent_claude.AgentBudgetStop("cap")
        return real_second(self, *a, **k)

    monkeypatch.setattr(run_mod.Runner, "call", call)
    monkeypatch.setattr(agent_claude.ClaudeProvider, "second_opinion", second)


@pytest.mark.parametrize(("where", "item_id", "found", "again"), [
    ("lead", "R-frame", FOUND_NUMBER, AGAIN_NUMBER),
    ("second", "R-coat", FOUND_TEXT, AGAIN_TEXT),
])  # fmt: skip
def test_a_cap_refusal_inside_the_step_leaves_the_old_query_and_the_review_completes(
    w, monkeypatch, where, item_id, found, again
):
    answers = {**s.ANSWERS, item_id: SILENT}
    monkeypatch.setattr(settings, "agent_review_reread_silent_enabled", False)
    off, _ = review(w, answers, found, again)
    monkeypatch.setattr(settings, "agent_review_reread_silent_enabled", True)
    db.reset_connection()
    _refuse_in_step(monkeypatch, where)
    on, _ = review(w, answers, found, again)
    assert _line_dicts(on) == _line_dicts(
        off
    )  # every line, the silent one too, exactly as with the switch off
    assert {k: r["verdict_class"] for k, r in on.items()} == {
        k: r["verdict_class"] for k, r in off.items()
    }


def test_a_lead_answer_that_repeats_a_quote_not_on_the_page_is_refused(w):
    again = {
        "R-frame": {**s.ANSWERS["R-frame"], "paper_quote": "Coating thickness: 9.99 mm"}
    }
    lines, fake = review(w, {**s.ANSWERS, "R-frame": SILENT}, FOUND_NUMBER, again)
    row = lines["R-frame"]
    assert row["word"] == "Query"
    assert W.REREAD_NOT_CONFIRMED_WHY.format(page=1) in row["reason"]
    assert fake.kinds.count("lead_again") == 1


def test_the_lead_is_told_to_check_the_page_itself(w):
    seen = []
    real = run_mod.Runner._ask_lead

    def spy(self, batch, parts, split_ok, once=False):
        seen.append((json.dumps(parts["messages"]), once))
        return real(self, batch, parts, split_ok, once)

    import pytest as _p

    mp = _p.MonkeyPatch()
    mp.setattr(run_mod.Runner, "_ask_lead", spy)
    try:
        review(w, {**s.ANSWERS, "R-frame": SILENT}, FOUND_NUMBER, AGAIN_NUMBER)
    finally:
        mp.undo()
    again = [t for t, o in seen if "a_second_reader_points_to" in t]
    assert len(again) == 1 and "Check the page yourself" in again[0]
    assert [o for t, o in seen if "a_second_reader_points_to" in t] == [True]


# ---------------------------------------------------------------- a step that ended early is stated, never dropped

from fastapi.testclient import TestClient  # noqa: E402

from app import access  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def five(w, monkeypatch):
    monkeypatch.setitem(
        s.RULES,
        "R-x",
        ("The marking shall be in red for every unit.", "4.3", None, None, None, None),
    )
    ids = ("R-coat", "R-frame", "R-mark", "R-colour", "R-x")
    w["doc"], w["cache"] = s.item_doc(ids)
    with db.connect() as conn:
        s.label_rows(conn, ["R-x"])
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    w.update(ids=ids, answers=dict.fromkeys(ids, SILENT))
    return w


def _routed(five, reread, refuse_after=None, monkeypatch=None):
    five["fake"] = ReLane(reread=reread, answers=five["answers"])
    if refuse_after is not None:
        real, seen = run_mod.Runner.call, []

        def call(self, model, parts, max_tokens, once=False):
            if "PAGE RE-READ" in json.dumps(parts.get("system")):
                seen.append(1)
                if len(seen) > refuse_after:
                    raise agent_claude.AgentBudgetStop("cap")
            return real(self, model, parts, max_tokens, once)

        monkeypatch.setattr(run_mod.Runner, "call", call)
    client = TestClient(app, base_url="http://127.0.0.1")
    r = client.post("/api/reviews/agent-run", json={"submittal_document_id": s.PAPER})
    run_id = r.json().get("run_id") or r.json()["review_run_id"]
    assert (
        agent_review_jobs.run(agent_review_jobs.claim_next("w-test"), "w-test")
        == "done"
    )
    return client, run_id


def test_a_step_that_stops_after_two_of_five_silent_lines_is_stated_with_three_not_re_read(
    five, monkeypatch
):
    client, run_id = _routed(
        five, {"found": False}, refuse_after=2, monkeypatch=monkeypatch
    )
    summary = client.get(f"/api/reviews/runs/{run_id}/agent/summary").json()
    assert summary["page_reread_stopped"] == {
        "why": "a spending cap refused a call",
        "not_reread": 3,
    }
    lines = _line_dicts_with_marks(run_id)
    assert sorted(o for o in lines.values() if o) == [
        "no_value",
        "no_value",
        "step_off",
        "step_off",
        "step_off",
    ]
    assert rr.reread_facts(True, "x", [{"reread": {"outcome": "step_off"}}, {}]) == {
        "why": "x",
        "not_reread": 1,
    }
    import openpyxl

    wb = openpyxl.load_workbook(agent_review_jobs.run_dir(run_id) / "crs-internal.xlsx")
    cells = [
        str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value
    ]
    assert any(
        "The second reading of pages stopped early: 3 lines were not re-read" in c
        for c in cells
    )
    contractor = openpyxl.load_workbook(
        agent_review_jobs.run_dir(run_id) / "crs-contractor.xlsx"
    )
    assert not any(
        "second reading" in str(c.value)
        for ws in contractor
        for row in ws.iter_rows()
        for c in row
    )


def _line_dicts_with_marks(run_id):
    rows = db.connect().execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ?", (run_id,)
    )
    return {
        r["item_id"]: (json.loads(r["line_json"]).get("reread") or {}).get("outcome")
        for r in rows
    }


def test_the_field_is_null_when_the_step_is_off_and_when_it_ran_fully(
    five, monkeypatch
):
    client, run_id = _routed(five, {"found": False})
    assert (
        client.get(f"/api/reviews/runs/{run_id}/agent/summary").json()[
            "page_reread_stopped"
        ]
        is None
    )
    assert set(_line_dicts_with_marks(run_id).values()) == {"no_value"}
    monkeypatch.setattr(settings, "agent_review_reread_silent_enabled", False)
    db.reset_connection()
    client, run_id = _routed(five, {"found": False})
    assert (
        client.get(f"/api/reviews/runs/{run_id}/agent/summary").json()[
            "page_reread_stopped"
        ]
        is None
    )
    assert set(_line_dicts_with_marks(run_id).values()) == {None}


def test_calls_already_paid_in_a_refused_step_are_charged_to_the_line(w, monkeypatch):
    _refuse_in_step(monkeypatch, "lead")
    lines, _ = review(w, {**s.ANSWERS, "R-frame": SILENT}, FOUND_NUMBER, AGAIN_NUMBER)
    stored = line_json(lines["R-frame"])
    assert stored["reread"]["outcome"] == "step_off" and stored["usd"] > 0
