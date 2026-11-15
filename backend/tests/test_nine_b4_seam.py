"""B4 through B1's REAL seam (`nine_call.ask`) with a fake Messages transport: what a call really sent, a held block, the role budget.
Invented documents; no network, no key, no model. Uses B1's world (a database with the run, the stored list and three documents)."""

from __future__ import annotations

import json
from typing import ClassVar

from app import agent_review_pass_guards as G
from app import agent_review_standards as standards
from app import nine_call, nine_record
from app import nine_checklist as checklist
from app import nine_findings as nf
from app import nine_reviewer as rev
from app.nine_call import FakeTransport
from tests.test_nine_call_record import (
    world,  # noqa: F401  (B1's world: documents "paper", "book" on the list, "held" off it)
)

RULE = "The coating thickness shall be at least 0.2 mm on every outside surface."
OTHER_RULE = "The housing shall be painted in a single colour on every outside surface."
PAPER = {
    1: "DATA SHEET Coating thickness: 0.35 mm",
    2: "Notes Housing painted in two colours",
}


def group(book="book", chapter="4", pages=(4,), text=RULE):
    return [rev.ChapterText(book, chapter, 1, 1, pages, text)]


def finding(clause_quote=RULE, verdict="not_met", label="Coating thickness", **kw):
    return {
        "issue": "x", "field_label": label, "paper_page": 1, "paper_quote": "Coating thickness: 0.35 mm", "clause": "4.1",
        "clause_quote": clause_quote, "verdict": verdict, "reasoning": "r", "comment": "c", "fact_ids": [], **kw,
    }  # fmt: skip


def reply(*findings):
    return json.dumps({"findings": list(findings)})


def prefix():
    return rev.prefix_blocks("paper", PAPER, "digest of values", "no context")


def run_review(answers, groups, **kw):
    t = FakeTransport(answers)
    got = rev.review(
        "run1", prefix(), groups, send=t, env=FakeTransport.ENV, concurrency=1, **kw
    )
    return got, t


def test_what_a_call_sent_is_read_from_the_answer_and_matches_the_body():
    got, t = run_review([reply(finding())], [group()])
    sent = got.raw[0][1]
    assert (
        sent.paper_pages == frozenset({1, 2})
        and sent.book_pages == {"book": frozenset({4})}
        and sent.read_refs == (("book", "4", 1),)
    )
    body = json.dumps(t.bodies[0])
    assert (
        RULE in body and "digest of values" in body
    )  # the prefix and the chapter really went
    assert got.ok and got.answered == 1 and got.state() == ("ran", None)


def test_a_block_the_gate_held_is_not_sent_and_a_quote_from_its_pages_is_unverified():
    held = group(
        "held", "9", (7,), OTHER_RULE
    )  # "held" is not on the run's stored list
    got, t = run_review(
        [reply(finding(), finding(clause_quote=OTHER_RULE, label="Housing colour"))],
        [[*group(), *held]],
    )
    assert got.not_sent == [("held", "not_approved")] and OTHER_RULE not in json.dumps(
        t.bodies[0]
    )
    sent = got.raw[0][1]
    assert "held" not in sent.book_pages and sent.book_pages == {"book": frozenset({4})}
    books = standards.BookPages()
    books._books["book"] = G.Book({4: RULE})
    books._books["held"] = G.Book(
        {7: OTHER_RULE}
    )  # the book exists locally, but its pages were never sent
    checked = [nf.check_raw(raw, s, PAPER, books) for raw, s in got.raw]
    assert checked[0].clause_ok is True
    assert checked[1].clause_ok is False and checked[1].clause_why in (
        nf.NO_BOOK,
        nf.CLAUSE_NOT_FOUND,
        G.NOT_FOUND,
    )
    assert (
        got.partly
        and got.state()[0] == "ran_partly"
        and "held by the gate" in got.state()[1]
    )


class OnceGate(nine_call.RoleGate):
    """A role gate that lets the first call through and holds every later one ("role_budget")."""

    seen: ClassVar[list[int]] = [0]

    def fits(self, run_id, worst_usd, conn=None):
        OnceGate.seen[0] += 1
        return OnceGate.seen[0] <= 1


def test_the_role_budget_ends_the_reviewer_ran_partly_and_the_checklist_asks_what_the_unread_chapter_would_cover():
    OnceGate.seen[0] = 0
    g1, g2 = group("book", "4", (4,), RULE), group("book", "5", (5,), OTHER_RULE)
    got, t = run_review([reply(finding())], [g1, g2], gate=OnceGate(4, 4.0))
    assert len(t.bodies) == 1  # the second call was not made
    assert (
        got.budget_stopped
        and got.answered == 1
        and got.not_asked == 1
        and got.unread == [g2]
    )
    state, why = got.state()
    assert (
        state == "ran_partly"
        and "role budget reached" in why
        and "1 of 2 chapter group(s) not read" in why
    )
    # role 5: only the rule the read chapter covered is skipped; the rule of the unread chapter is asked (never weaker than today's)
    books = standards.BookPages()
    books._books["book"] = G.Book({4: RULE})
    rules = [
        {"id": "1", "standard_document_id": "book", "source_text": RULE},
        {"id": "2", "standard_document_id": "book", "source_text": OTHER_RULE},
    ]
    plan = {
        "R-1": {"item_id": "R-1", "source": "rule"},
        "R-2": {"item_id": "R-2", "source": "rule"},
    }
    built = nf.process(
        got.raw,
        paper_pages=PAPER,
        books=books,
        rules=rules,
        plan_items=plan,
        tier_lookup=lambda _i: "AI approved",
    )
    cov = checklist.plan(
        list(plan.values()), [b.finding for b in built], reviewer_ok=got.ok
    )
    assert [i["item_id"] for i in cov.to_ask] == ["R-2"] and cov.skipped == {
        "R-1": built[0].finding.finding_id
    }


def test_a_role_budget_reached_before_any_call_is_not_run_and_every_item_is_asked():
    class Never(nine_call.RoleGate):
        def fits(self, run_id, worst_usd, conn=None):
            return False

    got, t = run_review([reply(finding())], [group()], gate=Never(4, 0.0))
    assert (
        t.bodies == []
        and got.answered == 0
        and not got.ok
        and got.state()[0] == "not_run"
        and "role budget" in got.state()[1]
    )
    items = [{"item_id": "R-1"}, {"item_id": "S-2"}]
    assert [
        i["item_id"] for i in checklist.plan(items, [], reviewer_ok=got.ok).to_ask
    ] == ["R-1", "S-2"]


def test_a_failed_call_is_counted_unread_and_never_a_finding():
    got, _t = run_review(["this is not json"], [group()])
    assert (
        got.failed == 1
        and got.unread == [group()]
        and not got.ok
        and got.state()[0] == "not_run"
    )
    assert got.errors == ["unreadable_reply"] or got.errors


def test_the_prefix_is_the_same_in_every_call_and_the_calls_are_in_the_record():
    got, t = run_review(
        [reply(), reply()], [group(chapter="4"), group(chapter="5", pages=(5,))]
    )
    assert len(t.bodies) == 2 and got.answered == 2
    first, second = (json.dumps(b["messages"][0]["content"][:4]) for b in t.bodies)
    assert first == second  # the cached prefix (paper pages) is byte-identical
    rec = nine_record.load_record("run1")
    assert (
        len(rec.calls) == 2
        and {c.step for c in rec.calls} == {"nine_reviewer"}
        and all(c.state == "answered" for c in rec.calls)
    )
    assert got.produced() == {
        "raw_findings": 0,
        "chapter_groups": 2,
        "answered": 2,
        "failed": 0,
        "not_asked": 0,
        "unread_groups": 0,
    }


def test_a_stop_asks_no_further_group_and_the_run_says_partly():
    stops = iter([False, True])
    t = FakeTransport([reply(finding())])
    got = rev.review(
        "run1",
        prefix(),
        [group(chapter="4"), group(chapter="5")],
        send=t,
        env=FakeTransport.ENV,
        concurrency=1,
        should_stop=lambda: next(stops),
    )
    assert len(t.bodies) == 1 and got.not_asked == 1 and got.partly and got.ok


def test_cost_unknown_is_never_zero_on_the_local_engine():
    local = []

    def local_send(body):
        local.append(body)
        return {"text": reply(finding()), "model": "local-a"}

    got = rev.review(
        "run1",
        prefix(),
        [group()],
        engine="local",
        local_send=local_send,
        concurrency=1,
    )
    assert got.answered == 1 and got.usd is None
