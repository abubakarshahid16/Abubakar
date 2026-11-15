"""B4 through B1's STRICT seam (`nine_call.ask`) with a fake Messages transport: blocks are NAMED (the seam loads the stored text), what a call
really sent comes from `Answer.reads`, a held block or source is dropped and named, the role budget. Invented documents; no network, no key."""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from app import (
    agent_claude,
    db,
    nine_call,
    nine_record,
    review_engine,
    review_shown,
    submittal_review,
)
from app import agent_review_pass_guards as G
from app import agent_review_standards as standards
from app import nine_checklist as checklist
from app import nine_findings as nf
from app import nine_reviewer as rev
from app.config import settings
from app.nine_call import FakeTransport

NOW = "2026-11-16T00:00:00Z"
RULE = "The coating thickness shall be at least 0.2 mm on every outside surface."
OTHER_RULE = "The housing shall be painted in a single colour on every outside surface."
HELD_RULE = "The nameplate shall be stainless steel and fixed with four rivets."
PAPER = {
    1: "DATA SHEET Coating thickness: 0.35 mm",
    2: "Notes Housing painted in two colours",
}
PAGES = {"paper": PAPER, "book": {4: RULE, 5: OTHER_RULE}, "held": {7: HELD_RULE}}


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "nine.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    agent_claude.reset_shared_meter_for_tests()
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc, pages in PAGES.items():
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',?,?)",
                (doc, f"{doc}.pdf", doc * 8, f"{doc}.pdf", max(pages), NOW),
            )
            for n, text in pages.items():
                conn.execute(
                    "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
                    (doc, n, text, len(text)),
                )
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('run1','paper','running',?,?)",
            (NOW, NOW),
        )
        review_shown.record_in(
            conn, "run1", ["paper", "book"], NOW
        )  # the stored list names the paper and the book, not "held"
        review_engine.record_in(
            conn,
            "run1",
            {"choice": "claude", "text_leaves": True, "parts": []},
            "starter1",
            then_ai=False,
            bar_claude=False,
            now=NOW,
        )  # default deny: only a stored Claude decision opens the lane
    nine_record.start_run("run1")
    yield
    db.reset_connection()


def group(book="book", chapter="4", pages=(4,)):
    return [rev.ChapterText(book, chapter, 1, 1, pages, 100)]


def finding(clause_quote=RULE, verdict="not_met", label="Coating thickness", **kw):
    return {
        "issue": "x", "field_label": label, "paper_page": 1, "paper_quote": "Coating thickness: 0.35 mm", "clause": "4.1",
        "clause_quote": clause_quote, "verdict": verdict, "reasoning": "r", "comment": "c", "fact_ids": [], **kw,
    }  # fmt: skip


def reply(*findings):
    return json.dumps({"findings": list(findings)})


DIGEST = [("f:1:1", "Coating thickness", "0.35 mm", "p1")]


def prefix(parts=()):
    return rev.prefix_blocks("paper", [1, 2], DIGEST, parts)


def run_review(answers, groups, pre=None, **kw):
    t = FakeTransport(answers)
    got = rev.review(
        "run1",
        pre or prefix(),
        groups,
        send=t,
        env=FakeTransport.ENV,
        concurrency=1,
        **kw,
    )
    return got, t


def test_blocks_are_named_not_copied_and_the_seam_sends_the_stored_words():
    for b in [*prefix(), *rev.chapter_blocks(group())]:
        assert not hasattr(b, "text")  # no caller text: the seam loads it
    pre = prefix()
    assert pre[-1].cache is True and not any(
        b.cache for b in pre[:-1]
    )  # the shared part ends at the digest
    got, t = run_review([reply(finding())], [group()])
    body = json.dumps(t.bodies[0])
    assert (
        RULE in body and PAPER[1] in body and "Coating thickness | 0.35 mm" in body
    )  # stored pages and the digest row, rendered by code
    sent = got.raw[0][1]
    assert (
        sent.paper_pages == frozenset({1, 2})
        and sent.book_pages == {"book": frozenset({4})}
        and sent.read_refs == (("book", "4", 1),)
    )
    assert got.ok and got.state() == (
        "ran_partly",
        "project context not passed (none offered)",
    )


def test_the_prompt_goes_as_registered_templates_and_nothing_else():
    assert (
        nine_call._TEMPLATES[rev.SYSTEM_ID][0].format() == rev.SYSTEM
        and nine_call._TEMPLATES[rev.QUESTION_ID][0].format() == rev.ANSWER_SHAPE
    )
    _got, t = run_review([reply()], [group()])
    body = t.bodies[0]
    assert rev.SYSTEM in [c["text"] for c in body["system"]] and rev.ANSWER_SHAPE in [
        c.get("text") for c in body["messages"][0]["content"]
    ]
    with pytest.raises(
        ValueError
    ):  # a free string is refused by the seam (it is not a (template id, params) pair)
        nine_call.ask(
            "run1",
            4,
            [*prefix(), *rev.chapter_blocks(group())],
            "a free question",
            send=FakeTransport(["{}"]),
            env=FakeTransport.ENV,
        )


def test_a_book_the_gate_held_is_not_sent_and_a_quote_from_its_pages_is_unverified():
    held = group("held", "9", (7,))  # "held" is not on the run's stored list
    got, t = run_review(
        [reply(finding(), finding(clause_quote=HELD_RULE, label="Nameplate"))],
        [[*group(), *held]],
    )
    assert any(
        doc == "held" for doc, _code in got.not_sent
    ) and HELD_RULE not in json.dumps(t.bodies[0])
    sent = got.raw[0][1]
    assert "held" not in sent.book_pages and sent.book_pages == {"book": frozenset({4})}
    books = standards.BookPages()
    books._books["book"] = G.Book({4: RULE})
    books._books["held"] = G.Book(
        {7: HELD_RULE}
    )  # the pages exist locally but were never sent
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


def test_a_context_part_with_a_held_source_is_dropped_and_named_the_others_go_on():
    ok = rev.ContextPart(
        "override_list",
        ("paper",),
        (("coating", "Coating thickness: 0.35 mm"),),
        ("key", "source"),
    )
    held = rev.ContextPart(
        "project_spec", ("held",), (("rule", "token of the held doc"),)
    )
    got, t = run_review([reply(finding())], [group()], pre=prefix([ok, held]))
    body = json.dumps(t.bodies[0])
    assert "Coating thickness: 0.35 mm" in body and "token of the held doc" not in body
    assert (
        got.context_offered == ("override_list", "project_spec")
        and got.context_dropped == ["project_spec"]
        and got.context_passed is False
    )
    state, why = got.state()
    assert (
        state == "ran_partly"
        and "project context not passed (1 part(s) held: project_spec)" in why
    )
    assert (
        got.produced()["context_parts"] == 2
        and got.produced()["context_parts_held"] == 1
    )


def test_context_is_passed_only_when_every_offered_part_went_and_none_offered_is_said_in_words():
    ok = rev.ContextPart(
        "override_list",
        ("paper",),
        (("coating", "Coating thickness: 0.35 mm"),),
        ("key", "source"),
    )
    got, _t = run_review([reply(finding())], [group()], pre=prefix([ok]))
    assert (
        got.context_passed is True
        and got.state() == ("ran", None)
        and got.produced()["context_passed"] == 1
    )
    none, _t2 = run_review([reply(finding())], [group()])
    assert (
        none.context_passed is False
        and none.context_offered == ()
        and none.state() == ("ran_partly", "project context not passed (none offered)")
    )


def test_no_context_available_is_ran_not_partly_and_is_said_in_words():
    """Case (b): role 2 found nothing to pass (no project paper held). The reviewer RAN; the record says why there is no context."""
    got, _t = run_review([reply(finding())], [group()], no_context_available=True)
    assert got.state() == ("ran", None) and got.context_passed is False
    p = got.produced()
    assert (
        p["context_parts"] == 0 and p["context"] == "no project context was available"
    )
    # case (a) with the same empty prefix and the flag off is a gap, not a clean run
    gap, _t2 = run_review([reply(finding())], [group()])
    assert gap.state()[0] == "ran_partly" and "context" not in gap.produced()


def test_available_flag_does_not_hide_a_held_part():
    ok = rev.ContextPart(
        "override_list", ("held",), (("coating", "four rivets"),), ("key", "source")
    )
    got, _t = run_review(
        [reply(finding())], [group()], pre=prefix([ok]), no_context_available=True
    )
    assert got.state()[0] == "ran_partly" and "held: override_list" in got.state()[1]
    assert "context" not in got.produced()


class OnceGate(nine_call.RoleGate):
    """A role gate that lets the first call through and holds every later one ("role_budget")."""

    seen: ClassVar[list[int]] = [0]

    def fits(self, run_id, worst_usd, conn=None):
        OnceGate.seen[0] += 1
        return OnceGate.seen[0] <= 1


def test_the_role_budget_ends_the_reviewer_ran_partly_and_the_checklist_asks_what_the_unread_chapter_would_cover():
    OnceGate.seen[0] = 0
    g1, g2 = group("book", "4", (4,)), group("book", "5", (5,))
    got, t = run_review([reply(finding())], [g1, g2], gate=OnceGate(4, 4.0))
    assert len(t.bodies) == 1
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
    books = standards.BookPages()
    books._books["book"] = G.Book({4: RULE})
    rules = [
        {"id": "1", "standard_document_id": "book", "source_text": RULE},
        {"id": "2", "standard_document_id": "book", "source_text": OTHER_RULE},
    ]
    plan = {
        "R-1": {
            "item_id": "R-1",
            "source": "rule",
            "field_roles": ["coating_thickness"],
        },
        "R-2": {"item_id": "R-2", "source": "rule", "field_roles": ["housing_colour"]},
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
        and got.errors
    )


def test_the_prefix_is_the_same_in_every_call_and_the_calls_are_in_the_record():
    got, t = run_review(
        [reply(), reply()], [group(chapter="4"), group(chapter="5", pages=(5,))]
    )
    assert len(t.bodies) == 2 and got.answered == 2
    first, second = (json.dumps(b["messages"][0]["content"][:6]) for b in t.bodies)
    assert (
        first == second
    )  # the cached prefix (paper pages and digest) is byte-identical
    rec = nine_record.load_record("run1")
    assert (
        len(rec.calls) == 2
        and {c.step for c in rec.calls} == {"nine_reviewer"}
        and all(c.state == "answered" for c in rec.calls)
    )
    assert got.produced() == {
        "raw_findings": 0, "chapter_groups": 2, "answered": 2, "failed": 0, "not_asked": 0, "unread_groups": 0,
        "context_parts": 0, "context_parts_held": 0, "context_passed": 0,
    }  # fmt: skip


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
    def local_send(body):
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


# ---------------------------------------------------------------- R65c A3: a part of a long chapter is a character range


LONG = (
    "Clause 4.1 "
    + RULE
    + " "
    + "padding sentence of the invented chapter. " * 6
    + "Clause 4.2 "
    + OTHER_RULE
)


def _long_world():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at) VALUES ('long','long.pdf','l'||'l'||'l'||'l'||'l'||'l'||'l'||'l',1,'long.pdf','ready',1,?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES ('long', 3, ?, ?, 0)",
            (LONG, len(LONG)),
        )
        review_shown.record_in(conn, "run1", ["paper", "book", "long"], NOW)


def test_a_clause_quote_outside_the_character_range_that_was_sent_does_not_count_as_sent():
    _long_world()
    first_end = LONG.index("Clause 4.2")
    part1 = [
        rev.ChapterText("long", "4", 1, 2, (3,), first_end, 0, first_end)
    ]  # the first part only
    got, t = run_review(
        [reply(finding(), finding(clause_quote=OTHER_RULE, label="Housing colour"))],
        [part1],
    )
    assert RULE in json.dumps(t.bodies[0]) and OTHER_RULE not in json.dumps(
        t.bodies[0]
    )  # the seam really sliced the stored text
    sent = got.raw[0][1]
    assert sent.book_blocks == {
        "long": (((3,), 0, first_end),)
    }  # the range the part was offered with
    books = standards.BookPages()
    books._books["long"] = G.Book({3: LONG})  # the whole stored page exists locally
    checked = [nf.check_raw(raw, s, PAPER, books) for raw, s in got.raw]
    assert checked[0].clause_ok is True  # inside the range
    assert (
        checked[1].clause_ok is False and checked[1].clause_why == nf.CLAUSE_NOT_SENT
    )  # the same page, but outside the range that went
    whole = nf.Sent(
        "c9", frozenset({1, 2}), {"long": frozenset({3})}, "m", (), {}
    )  # a call that sent the whole page
    assert (
        nf.check_raw(
            raw=got.raw[1][0], call=whole, paper_pages=PAPER, books=books
        ).clause_ok
        is True
    )


def test_the_range_is_the_one_the_seam_reports_not_the_one_offered():
    _long_world()
    part = rev.ChapterText("long", "4", 1, 2, (3,), 10, 0, 10)
    answer = nine_call.ask(
        "run1", 4, [*rev.prefix_blocks("paper", [1], DIGEST), *rev.chapter_blocks([part])], (rev.QUESTION_ID, {}), system=(rev.SYSTEM_ID, {}),
        send=FakeTransport([reply()]), env=FakeTransport.ENV,
    )  # fmt: skip
    assert rev.sent_of(answer, [part]).book_blocks == {
        "long": (((3,), 0, 10),)
    }  # the offered range
    assert rev.sent_of(answer, []).book_blocks == {
        "long": (((3,), 0, 10),)
    }  # read from Answer.ranges: no offer needed
    import dataclasses as _dc

    old = _dc.replace(answer, ranges=())
    assert rev.sent_of(old, []).book_blocks == {
        "long": (((3,), None, None),)
    }  # an answer with no ranges and no offer: whole pages, never a wider range
