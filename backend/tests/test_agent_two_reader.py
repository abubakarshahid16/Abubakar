"""The class "AI verdict, two readers agree" (owner order 13, point 10): invented paper, rule book and models; no network.

The stubbed lane answers the second reader (a lead-system request sent to the second model) from a table, records every request
body, and counts the calls. Nothing here reads a key or a real document."""

# ruff: noqa: F811
from __future__ import annotations

import itertools
import json
import sqlite3

import openpyxl
import pytest

from app import agent_claude, crs_layout, db
from app import agent_review_pair as pair
from app import agent_review_request as request_mod
from app import agent_review_run as run_mod
from app import agent_review_schema as schema
from app import agent_review_two_reader as two
from app import agent_review_wording as W
from app import crs_ai_words as words
from app import crs_ai_workbook as WB
from app.api import agent_review_schemas as contract
from app.config import settings
from tests import agent_review_support as s
from tests.test_agent_review_crs import META, OK, SK, mk, rows_of
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of

CLASS = "AI verdict, two readers agree"


class TwoLane(s.FakeModel):
    """The first reader's answers come from `answers`; the SECOND reader (the lead's request sent to the second model) from
    `second`. `reader2` holds every second-reader request body. `fail` makes the second reader's call raise."""

    def __init__(self, second=None, fail=None, second_reply_model=None, **kw):
        kw.setdefault(
            "agree", None
        )  # the old second opinion gives no answer, so no line is proven: all are candidates
        super().__init__(**kw)
        self.second = dict(s.ANSWERS if second is None else second)
        self.fail, self.reader2 = fail, []
        self.reply_model = second_reply_model or self.SECOND

    def __call__(self, url, *, headers, body, timeout):
        system = json.dumps(body.get("system"))
        reader2 = (
            "CONTEXT CHECK" not in system
            and "independent senior engineer" not in system
            and body.get("model") == agent_claude.SECOND_MODEL
        )
        if not reader2:
            return super().__call__(url, headers=headers, body=body, timeout=timeout)
        self.reader2.append(body)
        self.kinds.append("reader2")
        if self.fail:
            raise self.fail
        last = body["messages"][0]["content"][-1]["text"]
        ids = [q["item_id"] for q in json.loads(last.split("\n\n")[0])["items"]]
        usage = {"input_tokens": 3000, "output_tokens": 600}
        got = [{"item_id": i, **self.second[i]} for i in ids if i in self.second]
        return self._reply(self.reply_model, usage, json.dumps({"answers": got}))


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)


def lane(w, **kw):
    w["fake"] = TwoLane(**kw)
    return w["fake"]


def stored(run_id, iid):
    return json.loads(lines_of(run_id)[iid]["line_json"])


def step_of(run_id):
    row = (
        db.connect()
        .execute("SELECT counts_json FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["counts_json"]).get("two_reader_step")


# ---------------------------------------------------------------- the class itself


def test_two_readers_agree_and_every_quote_of_both_is_verified_gives_the_class(w, on):
    fake = lane(w)
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
    line = stored(run_id, "R-coat")
    assert (
        line["verdict"] == "Query"
        and line["two_reader"]["quotes_checked"]["both"] is True
    )
    assert len(fake.reader2) == 1  # both candidates in ONE call
    assert step_of(run_id) == {
        "candidates": 2,
        "asked": 2,
        "calls": 2,
        "agreed": 2,
        "disagreed": 0,
        "unconfirmed": 0,
        "skipped": 0,
        "off": None,
    }


def test_the_class_is_never_a_pass_or_a_fail_in_the_stored_row(w, on):
    lane(w)
    for iid, row in lines_of(run_review()).items():
        if row["verdict_class"] == CLASS:
            assert row["word"] not in ("Pass", "Fail")


def test_one_quote_of_the_second_reader_not_verified_keeps_ai_thinks(w, on):
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {**s.ANSWERS["R-coat"], "paper_quote": "Coating layers three"},
        },
    )
    got = lines_of(run_review())
    assert (got["R-coat"]["verdict_class"], got["R-coat"]["word"]) == (
        "AI opinion, engineer to confirm",
        "AI thinks: met",
    )
    assert (
        got["R-mark"]["verdict_class"] == CLASS
    )  # the other line is not touched by it


def test_a_clause_quote_of_the_second_reader_not_in_the_rule_keeps_ai_thinks(w, on):
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-mark": {
                **s.ANSWERS["R-mark"],
                "clause_quote": "The marking shall be green always.",
            },
        },
    )
    assert lines_of(run_review())["R-mark"]["word"] == "AI thinks: not met"


def test_different_verdicts_make_a_query_with_the_two_readers_disagree_reason(w, on):
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {
                **s.ANSWERS["R-coat"],
                "verdict": "Fail",
                "reason_code": "not_met",
            },
        },
    )
    run_id = run_review()
    row = lines_of(run_id)["R-coat"]
    assert (row["verdict_class"], row["word"]) == ("Query for the engineer", "Query")
    assert row["reason"] == "two AI readers disagree on this line"
    assert step_of(run_id)["disagreed"] == 1


def test_the_second_reader_cannot_tell_leaves_the_line_as_it_is(w, on):
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {
                **s.ANSWERS["R-coat"],
                "verdict": "Query",
                "reason_code": "other",
            },
        },
    )
    run_id = run_review()
    assert lines_of(run_id)["R-coat"]["word"] == "AI thinks: met"
    assert step_of(run_id)["unconfirmed"] == 1


def test_the_second_reader_saying_not_applicable_is_not_agreement_and_not_disagreement(
    w, on
):
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {
                **s.ANSWERS["R-coat"],
                "verdict": "Query",
                "reason_code": "not_applicable",
            },
        },
    )
    assert lines_of(run_review())["R-coat"]["word"] == "AI thinks: met"


def test_an_absence_by_the_second_reader_is_never_agreement_for_a_not_met(w, on):
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-mark": {
                **s.ANSWERS["R-mark"],
                "reason_code": "absent",
                "pages_searched": [1],
            },
        },
    )
    assert lines_of(run_review())["R-mark"]["word"] == "AI thinks: not met"


def test_a_guard_objecting_to_the_second_answer_alone_stops_the_class(w, on):
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {
                **s.ANSWERS["R-coat"],
                "reasoning": "the value is not stated on the sheet",
            },
        },
    )
    assert lines_of(run_review())["R-coat"]["word"] == "AI thinks: met"


def test_a_guard_objecting_to_the_first_answer_means_the_line_is_never_asked(w, on):
    w["fake"] = fake = TwoLane()
    fake.answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "paper_quote": "Coating layers",
    }  # only the field's name, no value
    run_id = run_review()
    assert lines_of(run_id)["R-coat"]["verdict_class"] == "Query for the engineer"
    asked = json.loads(
        fake.reader2[0]["messages"][0]["content"][-1]["text"].split("\n\n")[0]
    )["items"]
    assert [q["item_id"] for q in asked] == ["R-mark"]


def test_an_unapproved_rule_never_produces_the_class_and_is_never_asked(w, on):
    with db.connect() as conn:
        conn.execute("DROP TRIGGER IF EXISTS rule_label_no_delete")
        conn.execute(
            "DELETE FROM rule_label WHERE rule_ref IN ('req-R-coat', 'req-R-mark')"
        )
        conn.commit()
    fake = lane(w)
    got = lines_of(run_review())
    assert {got[i]["verdict_class"] for i in ("R-coat", "R-mark")} == {
        "AI opinion, rule not yet approved"
    }
    assert fake.reader2 == []


def test_a_proven_pass_and_fail_are_untouched_and_buy_no_call(w, on):
    fake = lane(w, agree=True)  # the old second opinion agrees
    got = lines_of(run_review())
    # a Pass the code did not compare is "AI verdict: met" (owner, 12 Nov 2026); the Fail stays as it was
    assert (got["R-coat"]["word"], got["R-mark"]["word"]) == ("AI verdict: met", "Fail")
    assert (got["R-coat"]["verdict_class"], got["R-mark"]["verdict_class"]) == (
        CLASS,
        "Proven by code",
    )
    assert fake.reader2 == []


def test_a_number_rule_is_never_asked_a_number_is_compared_by_code(w, on):
    fake = lane(w)
    got = lines_of(run_review())
    assert got["R-frame"]["verdict_class"] != CLASS
    asked = json.loads(
        fake.reader2[0]["messages"][0]["content"][-1]["text"].split("\n\n")[0]
    )["items"]
    assert "R-frame" not in [q["item_id"] for q in asked]


def test_the_two_paper_quotes_on_different_pages_are_not_the_same_evidence(w, on):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,2,?,?,0)",
            (s.PAPER, "Coating layers two, repeated", 28),
        )
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {
                **s.ANSWERS["R-coat"],
                "paper_page": 2,
                "paper_quote": "Coating layers two",
            },
        },
    )
    assert lines_of(run_review())["R-coat"]["word"] == "AI thinks: met"


def test_the_same_family_as_the_first_reader_gives_no_class(w, on):
    fake = lane(
        w, second_reply_model="claude-sonnet-5-5-20260101"
    )  # the second reader names the lead's own family
    fake.LEAD = "claude-sonnet-5-5"
    run_id = run_review()
    assert lines_of(run_id)["R-coat"]["word"] == "AI thinks: met"


def test_an_unknown_first_reader_model_means_the_step_does_not_run(w, on):
    fake = lane(w)
    fake.LEAD = "unknown"
    run_id = run_review()
    assert fake.reader2 == [] and step_of(run_id)["off"] == two.OFF_LEAD_UNKNOWN
    assert lines_of(run_id)["R-coat"]["word"] == "AI thinks: met"


# ---------------------------------------------------------------- the request cannot hold the first answer


def test_the_second_readers_request_holds_nothing_the_first_reader_said(w, on):
    fake = lane(w)
    fake.answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "reasoning": "SENTINEL-LEAD-REASONING-71",
        "comment": "SENTINEL-LEAD-COMMENT-72",
    }
    fake.answers["R-mark"] = {
        **s.ANSWERS["R-mark"],
        "reasoning": "SENTINEL-LEAD-REASONING-73",
    }
    run_review()
    body = fake.reader2[0]
    text = json.dumps(body, ensure_ascii=False)
    assert "SENTINEL-LEAD" not in text
    items = json.loads(body["messages"][0]["content"][-1]["text"].split("\n\n")[0])[
        "items"
    ]
    for q in items:  # the question holds the item's own fields only
        assert set(q) <= {
            "item_id",
            "question",
            "field_roles",
            "standard",
            "clause",
            "rule_kind",
            "comparator",
            "value",
            "unit",
            "page_hint",
            "requirement_ref",
            "clause_ref",
        }
    blocks = body["messages"][0]["content"]
    assert all(
        b["text"].startswith(("<paper", "<requirement", "<clause", '{"items"'))
        for b in blocks
    )
    assert (
        body["system"][0]["text"] == request_mod.SYSTEM
    )  # the SAME question as the first reader's


def test_the_second_request_is_built_only_from_items_pages_and_held_text(w, on):
    """No parameter of `build_parts` can carry a first answer: the step calls it with items, page text and held rule text."""
    import inspect

    from app import agent_review_two_reader_run as step

    src = inspect.getsource(step.TwoReaderMixin._two_reader_batch)
    parts_line = next(ln for ln in src.splitlines() if "build_parts(" in ln)
    assert (
        parts_line.strip()
        == "parts = build_parts(self.paper, pages, clauses, batch, held_of)"
    )
    assert "answer" not in parts_line and "line" not in parts_line


# ---------------------------------------------------------------- the switch, the calls, the optional step


def test_switch_off_stores_no_second_reader_field_and_makes_no_extra_call(w):
    fake = lane(w)
    run_id = run_review()
    assert fake.reader2 == [] and "reader2" not in fake.kinds
    for iid in lines_of(run_id):
        assert "two_reader" not in stored(run_id, iid)
    assert step_of(run_id) is None
    assert {r["verdict_class"] for r in lines_of(run_id).values()} & {CLASS} == set()


def test_the_default_of_the_switch_is_off():
    from app.settings_ext import SettingsExt

    assert (
        SettingsExt.model_fields["agent_review_two_reader_verdict_enabled"].default
        is False
    )


def test_switch_on_without_candidates_makes_no_call(w, on):
    fake = lane(w, agree=True)
    run_id = run_review()
    assert (
        fake.reader2 == []
        and step_of(run_id)["calls"] == 0
        and step_of(run_id)["candidates"] == 0
    )


def test_calls_are_bounded_batches_of_at_most_eight_candidates():
    assert two.MAX_BATCH == request_mod.MAX_BATCH == 8
    from app import agent_review_items as items_mod

    batches = items_mod.batch_by_page(
        [{"item_id": f"R-{n}", "page_hint": [1]} for n in range(19)], two.MAX_BATCH
    )
    assert [len(b) for b in batches] == [
        8,
        8,
        3,
    ]  # 19 candidates on one page group: ceil(19 / 8) = 3 calls


def test_a_cap_refusal_inside_the_step_switches_it_off_and_the_run_completes(
    w, on, monkeypatch
):
    fake = lane(w)
    orig = run_mod.Runner.call

    def call(self, model, parts, max_tokens, once=False):
        if (
            model == agent_claude.SECOND_MODEL
            and parts["system"][0]["text"] == request_mod.SYSTEM
        ):
            raise request_mod.StepCapStop("invented cap")
        return orig(self, model, parts, max_tokens, once)

    monkeypatch.setattr(run_mod.Runner, "call", call)
    run_id = run_review()
    run = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert run["stop_reason"] is None and run["partial"] == 0  # the run completed
    assert step_of(run_id)["off"] == two.OFF_CAP and step_of(run_id)["agreed"] == 0
    got = lines_of(run_id)
    assert (got["R-coat"]["word"], got["R-mark"]["word"]) == (
        "AI thinks: met",
        "AI thinks: not met",
    )
    assert fake.reader2 == []


def test_a_failed_call_inside_the_step_switches_it_off_and_leaves_the_lines(w, on):
    fake = lane(w, fail=TimeoutError("invented timeout"))
    run_id = run_review()
    assert step_of(run_id)["off"] == two.OFF_CALL_FAILED
    assert len(fake.reader2) == 1  # sent once, never again
    assert lines_of(run_id)["R-coat"]["word"] == "AI thinks: met"


def test_a_reply_that_leaves_every_item_out_changes_no_line(w, on):
    fake = lane(w)
    fake.second = {}  # a reply with no answer for any item
    run_id = run_review()
    assert (
        step_of(run_id)["unconfirmed"] == 2
        and lines_of(run_id)["R-coat"]["word"] == "AI thinks: met"
    )


def test_a_resumed_line_with_a_stored_second_answer_is_never_asked_again(w, on):
    fake = lane(w)
    run_id = run_review()
    assert len(fake.reader2) == 1
    from app import agent_review_jobs

    done = {
        k: v
        for k, v in agent_review_jobs.stored_lines(run_id).items()
        if not v.get("error")
    }
    plan = {"items": s.item_doc()[0]["items"], "cache": s.item_doc()[1]}
    runner = run_mod.Runner(
        paper=s.PAPER, items=plan["items"], pages=request_mod.DbPages(db.connect(), s.PAPER),
        clauses=request_mod.ClauseCache(plan["cache"]), model=agent_claude.LEAD_MODEL, send=fake, env=s.ENV,
        done_lines=done, paper_kind="datasheet", two_reader=True,
    )  # fmt: skip
    assert (
        runner.two_reader_candidates() == []
    )  # the stored answers are kept, nothing is asked again


# ---------------------------------------------------------------- the pure rule: brute force over the class table


def _oracle(
    ai,
    verdict,
    code,
    paper,
    clause,
    strong,
    hold,
    second_ok,
    sec_verdict,
    sec_paper,
    sec_clause,
    differ,
    same_ev,
    absent,
    tier,
    guards,
):
    """The rule written again in the test, from the owner's words."""
    if (
        ai not in ("Pass", "Fail")
        or verdict != "Query"
        or hold
        or not tier
        or not second_ok
    ):
        return False
    if (
        code != ("met" if ai == "Pass" else "not_met")
        or not (paper and clause)
        or (ai == "Fail" and not strong)
    ):
        return False
    if absent or not differ or not same_ev or not (sec_paper and sec_clause):
        return False
    if ai == "Fail" and not guards:  # a not met needs the Fail-side guards (F1, F3, F4)
        return False
    return sec_verdict == ("met" if ai == "Pass" else "not met")


@pytest.mark.parametrize("ai", ["Pass", "Fail", "Query"])
def test_the_class_is_reachable_only_by_the_rule_brute_force(ai):
    flags = [False, True]
    n = 0
    for verdict, code_ok, paper, clause, strong, hold, second_ok, sec_verdict, sec_paper, sec_clause, differ, same_ev, absent, tier, guards in itertools.product(
        ["Query", "Fail" if ai == "Fail" else "Pass"], flags, flags, flags, flags, flags, flags,
        ["met", "not met", "cannot tell"], flags, flags, flags, flags, flags, flags, flags,
    ):  # fmt: skip
        code = ("met" if ai == "Pass" else "not_met") if code_ok else "other"
        item = (
            OK
            if tier
            else {
                "source": "rule",
                "rule_tier": "not_approved",
                "rule_unapproved_why": "x",
            }
        )
        line = mk(
            "R-9", verdict, ai, item=item, reason_code=code, model="lead-m", paper_page=2, field_label_ai="Nameplate material",
            quotes_checked={"paper": paper, "clause": clause, "clause_strong": strong},
            second_opinion={"agree": None, "model": "m"} if second_ok else {"agree": False, "model": "m"},
            conditional_hold=hold, pass_guard={"ok": True}, paper_quote="Nameplate: steel plate", reasoning="It is steel.",
            two_reader={
                "verdict": sec_verdict, "model": "second-m" if differ else "lead-m-20260101",
                "reason_code": "met" if ai == "Pass" else "not_met", "paper_quote": "Nameplate: steel plate",
                "paper_page": 2, "spans": {"first": [0, 20], "second": [5, 25] if same_ev else [30, 50]},
                "fail_guards": {"ok": guards}, "pass_guard": {"ok": True}, "clause_quote": "Nameplates shall be steel and fixed",
                "field_label": "Other label",
                "quotes_checked": {"paper": sec_paper, "clause": sec_clause, "clause_strong": sec_clause},
                "says_absent": absent,
            },
        )  # fmt: skip
        got = W.apply(line)
        want = _oracle(
            ai,
            verdict,
            code,
            paper,
            clause,
            strong,
            hold,
            second_ok,
            sec_verdict,
            sec_paper,
            sec_clause,
            differ,
            same_ev,
            absent,
            tier,
            guards,
        )
        assert (got["verdict_class"] == CLASS) is want, (
            ai,
            verdict,
            code,
            paper,
            clause,
            strong,
            hold,
            second_ok,
            sec_verdict,
            sec_paper,
            sec_clause,
            differ,
            same_ev,
            absent,
            tier,
            guards,
        )
        if got["verdict_class"] == CLASS:
            n += 1
            assert got["verdict_label"] in two.WORDS and got["verdict_label"] not in (
                "Pass",
                "Fail",
            )
            assert (
                pair.contract_class_and_word(line)[1] == got["verdict_label"]
            )  # the contract table gives the same pair
            assert W.writer_refusal(line) is None and line["verdict"] == "Query"
            assert WB.status_of(line)[0] == words.STATUS_AI_VERDICT
    assert n == (0 if ai == "Query" else n)


# ---------------------------------------------------------------- same evidence


PAGE = (
    "Maximum allowable working pressure 10 barg\n"
    "Maximum allowable working temperature 200 C\n"
    "Design pressure (barg) 10\n"
    "Design pressure (barg) 25\n"
    "Seat leakage class IV\n"
    "Set pressure 10 barg 12 barg\n"
)


def _pair(first, second, page=2, page2=None, label="Design pressure"):
    """A first-reader line and a second-reader record whose spans were computed on PAGE by the step's own function."""
    line = {"paper_page": page, "paper_quote": first, "field_label_ai": label}
    rec = {
        "paper_page": page2 or page,
        "paper_quote": second,
        "field_label": label,
        "spans": two.evidence_spans(PAGE, first, second),
    }
    return line, rec


@pytest.mark.parametrize(
    "first,second,want",
    [
        (
            "Design pressure (barg) 10",
            "design pressure (barg) 10",
            True,
        ),  # the same place, the same value
        (
            "Set pressure 10 barg",
            "10 barg",
            True,
        ),  # one holds the other, same value and unit
        # near misses (the review's scenarios): each must NOT earn the class
        (
            "Maximum allowable working pressure 10 barg",
            "Maximum allowable working temperature 200 C",
            False,
        ),  # three words in a row, another field
        (
            "Design pressure (barg) 10",
            "Design pressure (barg) 25",
            False,
        ),  # same field label, another place and another value
        (
            "Design pressure (barg) 10",
            "Seat leakage class IV",
            False,
        ),  # same self-reported label, unrelated quotes
        (
            "Set pressure 10 barg",
            "pressure 10 barg 12 barg",
            False,
        ),  # the same place but another value
        (
            "Set pressure 10 barg",
            "Set pressure 10 barg 12 barg",
            False,
        ),  # the same place, an extra figure
    ],
)
def test_same_evidence_is_the_same_place_and_the_same_value_never_a_label_or_shared_words(
    first, second, want
):
    line, rec = _pair(first, second)
    assert two.same_evidence(line, rec) is want


def test_same_evidence_needs_the_same_page_and_stored_spans():
    line, rec = _pair("Design pressure (barg) 10", "Design pressure (barg) 10")
    assert two.same_evidence(line, rec)
    assert not two.same_evidence(line, {**rec, "paper_page": 3})
    assert not two.same_evidence(
        {**line, "paper_page": None}, {**rec, "paper_page": None}
    )
    assert not two.same_evidence(
        line, {**rec, "spans": None}
    )  # code cannot establish it: the line stays what it was
    assert not two.same_evidence(
        line, {**rec, "spans": {"first": [0, 5], "second": [9, 12]}}
    )


def test_the_step_stores_the_spans_and_the_line_before_the_step_in_its_record(w, on):
    lane(w)
    run_id = run_review()
    rec = stored(run_id, "R-coat")["two_reader"]
    assert rec["spans"]["first"] == rec["spans"]["second"] and rec["base"] == {
        "verdict_class": "AI opinion, engineer to confirm",
        "verdict_label": "AI thinks: met",
    }  # one run gives the before and the after


def test_a_near_miss_second_quote_stored_by_the_run_does_not_earn_the_class(w, on):
    """A second reader that quotes ANOTHER line of the same page (every quote verified) is not the same evidence."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ?, char_count = 99 WHERE document_id = ?",
            (s.PAPER_PAGE + "\nCoating layers three", s.PAPER),
        )
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-coat": {**s.ANSWERS["R-coat"], "paper_quote": "Coating layers three"},
        },
    )
    assert lines_of(run_review())["R-coat"]["word"] == "AI thinks: met"


def test_a_header_only_quote_never_earns_met_or_not_met(w, on):
    fake = lane(w)
    fake.answers["R-mark"] = {
        **s.ANSWERS["R-mark"],
        "paper_quote": "Marking",
    }  # the first reader quotes only the header
    fake.second["R-mark"] = {**s.ANSWERS["R-mark"], "paper_quote": "Marking"}
    run_id = run_review()
    assert lines_of(run_id)["R-mark"]["verdict_class"] != CLASS
    lane(
        w,
        second={
            **s.ANSWERS,
            "R-mark": {**s.ANSWERS["R-mark"], "paper_quote": "Marking"},
        },
    )
    assert (
        lines_of(run_review())["R-mark"]["verdict_class"] != CLASS
    )  # the second reader quotes only the header


def test_a_not_met_runs_the_fail_guards_and_each_guard_objecting_keeps_the_line(
    w, on, monkeypatch
):
    from app import agent_review_two_reader_run as stepmod

    fake = lane(w)
    run_id = run_review()
    assert (
        fake.kinds.count("context") >= 1
        and stored(run_id, "R-mark")["two_reader"]["fail_guards"].get("ok") is True
    )
    assert lines_of(run_id)["R-mark"]["verdict_class"] == CLASS
    # the context check (F4) holds the Fail: the line stays "AI thinks: not met"
    monkeypatch.setattr(
        stepmod.TwoReaderMixin,
        "_fail_guards",
        lambda self, *a, **k: {
            "ok": False,
            "why": "a condition on the rule-book page limits this rule",
        },
    )
    lane(w)
    row = lines_of(run_review())["R-mark"]
    assert (row["verdict_class"], row["word"]) == (
        "AI opinion, engineer to confirm",
        "AI thinks: not met",
    )


def test_the_fail_guards_are_the_ones_a_code_fail_passes_not_a_copy():
    import inspect

    from app import agent_review_two_reader_run as stepmod

    src = inspect.getsource(stepmod.TwoReaderMixin._fail_guards)
    assert (
        "verdict.apply_holds(" in src
        and "self.context_check_fail(" in src
        and "halt=False" in src
    )


def test_a_conditional_clause_quote_of_the_second_reader_keeps_the_not_met(
    w, on, monkeypatch
):
    quote = "The marking shall be in red when the unit is installed outdoors."
    monkeypatch.setitem(s.RULES, "R-mark", (quote, "4.3", None, None, None, None))
    w["doc"], w["cache"] = s.item_doc()
    fake = lane(w)
    fake.answers["R-mark"] = {**s.ANSWERS["R-mark"], "clause_quote": quote}
    fake.second["R-mark"] = {**s.ANSWERS["R-mark"], "clause_quote": quote}
    assert lines_of(run_review())["R-mark"]["verdict_class"] != CLASS


# ---------------------------------------------------------------- the table, the database copy, the old table


def test_the_class_and_its_two_words_are_in_the_one_table_and_the_database_copy():
    assert contract.LINE_TABLE[CLASS][0] == (
        "AI verdict: met",
        "AI verdict: not met",
        "AI verdict: not stated",
    )
    assert CLASS in schema.CLASSES and {
        "AI verdict: met",
        "AI verdict: not met",
    } <= set(schema.WORDS)
    assert CLASS in contract.RULE_REVIEW_ONLY
    with pytest.raises(ValueError):
        contract.AgentLine(
            item_id="x",
            verdict_class=CLASS,
            word="Pass",
            clause="1",
            rule_book="b",
            reason="r",
            rule_tier="Owner",
        )


def test_the_database_refuses_the_new_words_outside_the_class_and_the_class_with_other_words(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    conn = sqlite3.connect(":memory:")
    for stmt in schema._STATEMENTS:
        conn.execute(stmt)

    def put(cls, word, tier=None):
        conn.execute(
            "INSERT INTO agent_review_line (run_id, item_id, verdict_class, word, line_json, decided_at, rule_tier) VALUES ('r','i',?,?,'{}','t',?)",
            (cls, word, tier),
        )
        conn.execute("DELETE FROM agent_review_line")

    put(CLASS, "AI verdict: met")
    put(CLASS, "AI verdict: not met", "AI approved")
    for cls, word, tier in [
        (CLASS, "Pass", None), (CLASS, "Fail", None), (CLASS, "AI thinks: met", None), (CLASS, "AI verdict: met", "Not AI approved"),
        ("Proven by code", "AI verdict: met", None), ("AI opinion, engineer to confirm", "AI verdict: not met", None),
        ("Query for the engineer", "AI verdict: met", None),
    ]:  # fmt: skip
        with pytest.raises(sqlite3.IntegrityError):
            put(cls, word, tier)


def _old_database(path):
    """A database whose `agent_review_line` was made before the class existed (the class removed from its SQL), with three rows."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE audit_events (id INTEGER PRIMARY KEY, at TEXT, actor_user_id, actor_username TEXT, action TEXT, resource_type TEXT, resource_id TEXT, outcome TEXT, detail TEXT)"
    )
    for stmt in schema._STATEMENTS:
        conn.execute(stmt.replace(CLASS, "AI verdict, REMOVED"))
    for n, (cls, word, page) in enumerate(
        [
            ("Query for the engineer", "Query", 3),
            ("Proven by code", "Pass", None),
            ("Not applicable", "Not applicable", 7),
        ]
    ):
        conn.execute(
            "INSERT INTO agent_review_line (run_id,item_id,verdict_class,word,page,clause,rule_book,reason,rule_tier,line_json,trace_json,decided_at)"
            " VALUES ('r',?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"i{n}",
                cls,
                word,
                page,
                f"4.{n}",
                "Book A",
                f"reason {n}",
                "Owner",
                json.dumps({"n": n}),
                f"trace {n}",
                f"t{n}",
            ),
        )
    conn.commit()
    return conn


def _rows(conn, table="agent_review_line"):
    return [tuple(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY item_id')]


def test_an_older_line_table_is_upgraded_only_when_the_switch_is_on_and_keeps_every_row(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    conn = _old_database(tmp_path / "old.sqlite")
    before = _rows(conn)
    # the class is written whatever the switches say (a Pass the code did not compare): the old table is upgraded by default
    for flag in (False, True):
        monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", flag)
        assert schema.line_check_is_old(conn) and schema.shape_problem(conn)
    schema.create_tables(conn)
    assert not schema.line_check_is_old(conn) and schema.shape_problem(conn) is None
    # every row, every column, equal (the new columns are NULL and sit after the old ones)
    after = [r[: len(before[0])] for r in _rows(conn)]
    assert after == before
    kept = conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'agent_review_line_before_general_%'"
    ).fetchall()
    assert (
        len(kept) == 1 and _rows(conn, kept[0][0]) == before
    )  # the old table is kept, never dropped, with its rows
    audit = conn.execute(
        "SELECT action, resource_id, detail FROM audit_events"
    ).fetchall()
    assert [tuple(a) for a in audit] == [
        (
            "agent_review_tables_upgraded",
            kept[0][0],
            "rows copied: 3; the older table is kept under this name",
        )
    ]
    schema.create_tables(
        conn
    )  # a second call finds nothing old: no second kept table, no second audit row
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'agent_review_line_before_general_%'"
        ).fetchone()[0]
        == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
    conn.execute(
        "INSERT INTO agent_review_line (run_id,item_id,verdict_class,word,line_json,decided_at) VALUES ('r','j',?,'AI verdict: met','{}','t')",
        (CLASS,),
    )


def test_a_failed_upgrade_rolls_back_and_leaves_the_old_table_and_its_rows(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    conn = _old_database(tmp_path / "old.sqlite")
    before, old_sql = (
        _rows(conn),
        conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'agent_review_line'"
        ).fetchone()[0],
    )

    def boom(*_a, **_k):
        raise sqlite3.IntegrityError("the copy holds a different number of rows")

    monkeypatch.setattr(schema, "_copy_old_rows", boom)
    with pytest.raises(schema.UpgradeFailed):
        schema.create_tables(conn)
    assert (
        _rows(conn) == before
        and conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'agent_review_line'"
        ).fetchone()[0]
        == old_sql
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'agent_review_line_before_general_%'"
        ).fetchone()[0]
        == 0
    )
    assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
    assert schema.shape_problem(
        conn
    )  # still refused: no run may start on the old shape


# ---------------------------------------------------------------- the CRS


def _two(iid, ai, **kw):
    code, verdict_word = ("met", "met") if ai == "Pass" else ("not_met", "not met")
    kw.setdefault("rule_kind", None)
    return mk(
        iid, "Query", ai, reason_code=code, why="no second opinion", pass_guard={"ok": True},
        quotes_checked={"paper": True, "clause": True, "clause_strong": True}, second_opinion=None,
        two_reader={
            "verdict": verdict_word, "model": "second-m", "reason_code": code, "paper_quote": "Nameplate: steel plate",
            "paper_page": 2, "clause_quote": "Nameplates shall be steel and fixed", "field_label": None,
            "spans": {"first": [0, 16], "second": [0, 22]}, "fail_guards": {"ok": True}, "pass_guard": {"ok": True},
            "quotes_checked": {"paper": True, "clause": True, "clause_strong": True, "both": True}, "says_absent": False,
        },
        **kw,
    )  # fmt: skip


CRS_LINES = [
    mk("R-1", "Fail", "Fail"),
    mk("R-2", "Pass", "Pass"),
    mk("R-3", "Query", "Fail", why="no second opinion"),
    mk("R-4", "Query", "Pass", why="no second opinion"),
    _two("R-5", "Pass"),
    _two("R-6", "Fail"),
    _two("R-7", "Fail", rule_kind="advice"),
    mk("R-8", "Query", None, why="the AI did not give pass or fail"),
]


def test_the_class_lines_are_the_fifth_status_with_the_stated_order_priority_and_wording(
    tmp_path,
):
    assert [ln["verdict_class"] for ln in CRS_LINES[4:7]] == [CLASS] * 3
    path = WB.write(CRS_LINES, tmp_path / "i.xlsx", META, "internal")
    rows = rows_of(path)
    order = [(r["Status"], r["Priority"]) for r in rows]
    assert [r["Status"] for r in rows] == [
        "Fail",
        "AI verdict",
        "AI verdict",
        "AI opinion",
        "Query",
        "AI verdict",
        "AI opinion",
        "Pass",
    ]
    verdict_rows = [r for r in rows if r["Status"] == "AI verdict"]
    assert [r["Priority"] for r in verdict_rows] == [
        "High",
        "Medium",
        None,
    ]  # not met: High when mandatory else Medium; met: blank
    assert (
        "two AI readers" in verdict_rows[0]["COMPANY Comments"]
        and "to be confirmed by an engineer" in verdict_rows[0]["COMPANY Comments"]
    )
    assert "the requirement is met" in verdict_rows[2]["COMPANY Comments"]
    assert order[1][0] == "AI verdict" and all(
        r["Status"] != "Pass" for r in verdict_rows
    )


def test_the_fifth_status_has_its_own_colour_and_is_counted_on_notes(tmp_path):
    path = WB.write(CRS_LINES, tmp_path / "i.xlsx", META, "internal")
    ws = openpyxl.load_workbook(path)["CRS"]
    fills = {
        ws.cell(r, 10).value: ws.cell(r, 1).fill.fgColor.rgb
        for r in range(1, ws.max_row + 1)
        if ws.cell(r, 10).value
    }
    assert fills["AI verdict"] == crs_layout.STATUS_FILLS["AI verdict"].fgColor.rgb
    assert fills["AI verdict"] not in {v for k, v in fills.items() if k != "AI verdict"}
    notes = {
        r[0]: r[1]
        for r in openpyxl.load_workbook(path)["Notes"].iter_rows(
            min_row=2, values_only=True
        )
    }
    assert (
        notes["Count: AI verdict"] == 3
        and notes["Count: Pass"] == 1
        and notes["Count: Fail"] == 1
    )


def test_the_evidence_sheet_holds_the_second_readers_verdict_quotes_and_both_checks(
    tmp_path,
):
    path = WB.write(CRS_LINES, tmp_path / "i.xlsx", META, "internal")
    ev = rows_of(path, "Evidence")
    mine = [r for r in ev if r["Status"] == "AI verdict"]
    assert len(mine) == 3
    assert {r["Independent reader: verdict"] for r in mine} == {"met", "not met"}
    assert all(
        r["Independent reader: paper quote"] and r["Independent reader: clause quote"]
        for r in mine
    )
    assert all(
        r["Independent reader: paper quote check"]
        == r["Independent reader: clause quote check"]
        == "verified"
        for r in mine
    )
    assert all(
        r["Independent reader: verdict"] is None
        for r in ev
        if r["Status"] != "AI verdict"
    )


def test_the_contractor_copy_never_holds_the_class_or_its_words(tmp_path):
    path = WB.write(CRS_LINES, tmp_path / "c.xlsx", META, "contractor")
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["CRS"]
    text = "\n".join(
        str(c)
        for row in wb["CRS"].iter_rows(values_only=True)
        for c in row
        if c is not None
    )
    for banned in (
        "AI verdict",
        "two AI readers",
        "AI opinion",
        "AI thinks",
        CLASS,
        "independent",
    ):
        assert banned not in text
    # #1767: the contractor copy has the company columns only (no Status); it holds exactly the internal copy's proven Fails
    contractor_rows = rows_of(path)
    assert "Status" not in contractor_rows[0]
    internal = WB.write(CRS_LINES, tmp_path / "i2.xlsx", META, "internal")
    assert (
        len(contractor_rows)
        == len([r for r in rows_of(internal) if r["Status"] == "Fail"])
        == 1
    )


def test_the_summary_counts_the_class_apart_and_never_as_a_pass_or_fail():
    counts = W.counts(CRS_LINES)
    assert (counts["ai_verdict_met"], counts["ai_verdict_not_met"]) == (1, 2)
    assert (counts["proven_pass"], counts["proven_fail"]) == (1, 1)
    assert counts["ai_thinks_met"] == 1 and counts["ai_thinks_not_met"] == 1


def test_no_producer_maps_the_class_to_a_pass_or_a_fail():
    for ln in CRS_LINES[4:7]:
        cls, word = pair.contract_class_and_word(ln)
        assert (cls, word) == (CLASS, ln["verdict_label"]) and word not in (
            "Pass",
            "Fail",
        )
        assert WB.status_of(ln)[0] == "AI verdict"
    assert not any(ln["verdict_label"] in ("Pass", "Fail") for ln in CRS_LINES[4:7])
    assert words.STATUS_PASS not in {WB.status_of(ln)[0] for ln in CRS_LINES[4:7]}


def test_a_smaller_batch_limit_means_one_call_per_batch_and_each_call_stays_within_it(
    w, on, monkeypatch
):
    monkeypatch.setattr(two, "MAX_BATCH", 1)
    fake = lane(w)
    run_id = run_review()
    assert len(fake.reader2) == 2 and step_of(run_id)["calls"] == 2 + fake.kinds.count(
        "context"
    )  # + the F4 call
    for body in fake.reader2:
        assert (
            len(
                json.loads(body["messages"][0]["content"][-1]["text"].split("\n\n")[0])[
                    "items"
                ]
            )
            == 1
        )


def test_the_f4_call_of_an_agreeing_not_met_is_counted_in_the_steps_calls_and_cost_and_the_line(
    w, on
):
    fake = lane(w)
    run_id = run_review()
    step = step_of(run_id)
    assert (
        step["calls"] == len(fake.reader2) + fake.kinds.count("context") == 2
    )  # the reader call and the F4 call
    mark = stored(run_id, "R-mark")
    assert (
        mark["usd"]
        >= mark["two_reader"]["usd"] + mark["two_reader"]["fail_guards"]["usd"]
        > 0
    )  # a line never understates its cost


def test_a_figure_standing_in_two_rows_is_not_pinned_unless_the_other_quote_pins_it():
    page = "Row A design pressure (barg) 10\nRow B design pressure (barg) 10\nRow C set pressure 10 barg\n"
    dup = "design pressure (barg) 10"
    spans = two.evidence_spans(
        page, dup, dup
    )  # both readers quote a figure that stands in two rows
    assert spans["first"] is None and "more than one place" in spans["why"]
    line = {"paper_page": 2, "paper_quote": dup}
    assert not two.same_evidence(
        line, {"paper_page": 2, "paper_quote": dup, "spans": spans}
    )
    # the other reader's quote stands in exactly one place and holds exactly one occurrence: pinned without choosing
    pinned = two.evidence_spans(page, dup, "Row B design pressure (barg) 10")
    assert (
        pinned["first"] is not None
        and pinned["second"][0] < pinned["first"][0] < pinned["second"][1]
    )
    assert two.same_evidence(
        {"paper_page": 2, "paper_quote": dup},
        {
            "paper_page": 2,
            "paper_quote": "Row B design pressure (barg) 10",
            "spans": pinned,
        },
    )
    # a short value-only quote in several rows against a quote that spans two rows: two occurrences meet it, so nothing is chosen
    assert (
        two.evidence_spans(
            page, "design pressure (barg) 10\nRow B design pressure (barg) 10", "10"
        )["first"]
        is None
    )


def test_the_second_readers_label_only_quote_never_earns_the_class():
    """Revert `_guards_ok`'s label probe and this fails: the quotes overlap, the numbers agree, every check is verified."""
    page = "Coating layers two\nMarking blue\n"
    first = "Coating layers two"
    second = "Coating layers"  # only the field's own label
    base = {"item_id": "R-9", "source": "rule", "standard": "S", "clause": "1", "verdict": "Query", "ai_verdict": "Pass", "reason_code": "met",
            "model": "lead-m", "paper_page": 1, "paper_quote": first, "field_label_ai": "Coating layers", "field": "Coating layers",
            "quotes_checked": {"paper": True, "clause": True}, "reasoning": "r", "second_opinion": None, "pass_guard": {"ok": True}}  # fmt: skip
    rec = {"verdict": "met", "model": "second-m", "reason_code": "met", "paper_page": 1, "paper_quote": second, "field_label": "Coating layers",
           "spans": two.evidence_spans(page, first, second), "pass_guard": {"ok": True}, "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "says_absent": False}  # fmt: skip
    ok = W.apply(
        W.final_cap(
            {
                **base,
                "two_reader": {
                    **rec,
                    "paper_quote": "Coating layers two",
                    "spans": two.evidence_spans(page, first, first),
                },
            },
            OK,
            skill_ids=SK,
            paper_kind="datasheet",
        )
    )
    assert (
        ok["verdict_class"] == CLASS
    )  # the same line with a real second quote earns it
    got = W.apply(
        W.final_cap(
            {**base, "two_reader": rec}, OK, skill_ids=SK, paper_kind="datasheet"
        )
    )
    assert got["verdict_class"] != CLASS


def test_the_second_readers_label_only_quote_never_earns_a_not_met_either():
    """For a Fail the second reader's label probe in `_guards_ok` is the only guard of this kind: revert it and this fails."""
    page = "Marking blue\nCoating layers two\n"
    first, second = "Marking blue", "Marking"
    base = {"item_id": "R-9", "source": "rule", "standard": "S", "clause": "1", "verdict": "Query", "ai_verdict": "Fail", "reason_code": "not_met",
            "model": "lead-m", "paper_page": 1, "paper_quote": first, "field_label_ai": "Marking", "field": "Marking", "clause_quote": "x",
            "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "reasoning": "r", "second_opinion": None}  # fmt: skip

    def rec(quote):
        return {"verdict": "not met", "model": "second-m", "reason_code": "not_met", "paper_page": 1, "paper_quote": quote, "field_label": "Marking",
                "clause_quote": "The marking shall be red", "spans": two.evidence_spans(page, first, quote), "fail_guards": {"ok": True},
                "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}, "says_absent": False}  # fmt: skip

    ok = W.apply(
        W.final_cap(
            {**base, "two_reader": rec("Marking blue")},
            OK,
            skill_ids=SK,
            paper_kind="datasheet",
        )
    )
    assert ok["verdict_class"] == CLASS
    assert (
        W.apply(
            W.final_cap(
                {**base, "two_reader": rec(second)},
                OK,
                skill_ids=SK,
                paper_kind="datasheet",
            )
        )["verdict_class"]
        != CLASS
    )
