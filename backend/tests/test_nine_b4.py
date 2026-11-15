"""Nine-role reviewer, builder B4: the reviewer's findings, the match, the join, the checklist coverage (SPEC D, E, G.4 row B4).

Invented books, rules and papers; a fake call seam; no network, no model. Every test here fails without the change it names."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

from app import agent_claude, db
from app import agent_review_pass_guards as G
from app import agent_review_request as request_mod
from app import agent_review_run as run_mod
from app import agent_review_standards as standards
from app import agent_review_verdict as V
from app import nine_checklist as checklist
from app import nine_findings as nf
from app import nine_match as match
from app import nine_reviewer as rev
from tests import agent_review_support as s

BOOK, OTHER = "doc_book_a", "doc_book_b"
RULE_A = "The coating thickness shall be at least 0.2 mm on every outside surface."
RULE_B = "The housing shall be painted in a single colour on every outside surface."
FILL = (
    "Invented filler sentence about the nameplate and the casing of the invented unit."
)
PAPER = {
    1: "DATA SHEET\nCoating thickness: 0.35 mm\nMarking blue",
    2: "Notes\nHousing painted in two colours",
}


def books_of(**pages):
    """A `BookPages` already holding invented books (no database)."""
    bp = standards.BookPages()
    for book_id, rows in pages.items():
        bp._books[book_id] = G.Book(rows)
    return bp


def sent(call="c1", paper=(1, 2), **book_pages):
    return nf.Sent(
        call,
        frozenset(paper),
        {k: frozenset(v) for k, v in book_pages.items()},
        "m1",
        (),
    )


def raw(**kw):
    base = {
        "issue": "coating", "field_label": "Coating thickness", "paper_page": 1, "paper_quote": "Coating thickness: 0.35 mm",
        "clause": "4.1", "clause_quote": RULE_A, "verdict": "met", "reasoning": "stated", "comment": "none", "fact_ids": [],
    }  # fmt: skip
    base.update(kw)
    return base


# ---------------------------------------------------------------- match


RULES = [
    {"id": "1", "standard_document_id": BOOK, "source_text": RULE_A},
    {"id": "2", "standard_document_id": BOOK, "source_text": RULE_B},
    {"id": "9", "standard_document_id": OTHER, "source_text": RULE_A},
]


def lookup_ai(item):
    return V.AI_TIER


def test_a_quote_inside_one_rule_of_the_same_book_is_a_match_with_that_rules_current_tier():
    got = match.match(
        BOOK, "coating thickness shall be at least 0.2 mm", RULES, lookup_ai
    )
    assert (got.matched, got.item_id, got.tier) == (True, "R-1", V.AI_TIER)


def test_a_quote_that_holds_the_rule_whole_is_a_match():
    got = match.match(BOOK, f"Clause 4.1. {RULE_A} See table 2.", RULES, lookup_ai)
    assert got.item_id == "R-1"


def test_two_candidate_rules_are_no_match_and_code_never_picks_one():
    dup = [*RULES, {"id": "3", "standard_document_id": BOOK, "source_text": RULE_A}]
    got = match.match(BOOK, RULE_A, dup, lookup_ai)
    assert (got.matched, got.why, got.candidates) == (False, match.WHY_MANY, 2)


def test_a_rule_of_another_book_or_a_short_quote_is_no_match():
    assert match.match(BOOK, RULE_B[:15], RULES, lookup_ai).matched is False
    assert match.match("doc_none", RULE_A, RULES, lookup_ai).why == match.WHY_NONE
    assert match.match(None, RULE_A, RULES, lookup_ai).why == match.WHY_NO_QUOTE


@pytest.mark.parametrize(
    ("given", "want"),
    [
        (V.AI_TIER, V.AI_TIER),
        (V.OWNER_TIER, V.OWNER_TIER),
        (None, V.RULE_NOT_APPROVED),
        ("junk", V.RULE_NOT_APPROVED),
    ],
)
def test_a_match_takes_the_rules_current_tier_never_a_better_one(given, want):
    got = match.match(BOOK, RULE_A, RULES, lambda _item: given)
    assert got.matched and got.tier == want
    assert (
        match.match(BOOK, RULE_A, RULES, None).tier == V.RULE_NOT_APPROVED
    )  # no label table: nothing is approved


# ---------------------------------------------------------------- the clause quote on a page that was SENT


def test_a_clause_quote_found_only_on_a_page_that_was_not_sent_is_unverified():
    books = books_of(**{BOOK: {1: FILL, 2: RULE_A}})
    got = nf.verify_sent(BOOK, RULE_A, [1], frozenset({1}), books)
    assert (got.found, got.why) == (False, nf.CLAUSE_NOT_SENT)
    got = nf.verify_sent(BOOK, RULE_A, [2], frozenset({2}), books)
    assert (got.found, got.page) == (True, 2)


def test_the_same_text_on_a_sent_and_an_unsent_page_is_verified_on_the_sent_one():
    books = books_of(**{BOOK: {1: RULE_A, 2: FILL, 3: RULE_A}})
    got = nf.verify_sent(
        BOOK, RULE_A, [3], frozenset({3}), books
    )  # the first place verify() finds it is page 1
    assert (got.found, got.page) == (True, 3)


def test_a_quote_that_is_not_in_the_book_at_all_says_so():
    books = books_of(**{BOOK: {1: FILL}})
    got = nf.verify_sent(BOOK, RULE_A, [1], frozenset({1}), books)
    assert (got.found, got.why) == (False, G.NOT_FOUND)


def test_check_raw_verifies_the_paper_quote_on_a_sent_paper_page_and_the_clause_in_the_book():
    books = books_of(**{BOOK: {1: RULE_A}})
    got = nf.check_raw(raw(), sent(**{BOOK: {1}}), PAPER, books)
    assert (got.paper_ok, got.clause_ok, got.clause_page, got.book_id) == (
        True,
        True,
        1,
        BOOK,
    )
    far = nf.check_raw(
        raw(paper_page=2, paper_quote="Coating thickness: 0.35 mm"),
        sent(paper=(1,), **{BOOK: {1}}),
        PAPER,
        books,
    )
    assert (
        far.paper_ok is False and far.paper_why == nf.PAPER_NOT_SENT
    )  # page 2 was not sent in that call
    miss = nf.check_raw(
        raw(paper_quote="Coating thickness: 0.99 mm"), sent(**{BOOK: {1}}), PAPER, books
    )
    assert miss.paper_ok is False and miss.clause_ok is True


def test_a_quote_in_two_books_of_one_call_is_unverified_unless_the_finding_names_its_book():
    books = books_of(**{BOOK: {1: RULE_A}, OTHER: {1: RULE_A}})
    call = sent(**{BOOK: {1}, OTHER: {1}})
    assert nf.check_raw(raw(), call, PAPER, books).clause_why == nf.CLAUSE_AMBIGUOUS
    named = nf.check_raw(raw(book_id=OTHER), call, PAPER, books)
    assert (named.clause_ok, named.book_id) == (True, OTHER)


def test_a_finding_whose_quotes_are_not_verified_is_kept_as_a_finding_not_dropped():
    books = books_of(**{BOOK: {1: FILL}})
    c = nf.check_raw(raw(), sent(**{BOOK: {1}}), PAPER, books)
    assert not c.clause_ok and len(nf.join([c])) == 1


# ---------------------------------------------------------------- join


def _checked(verdict="met", call="c1", clause="4.1", label="Coating thickness", **kw):
    books = books_of(**{BOOK: {1: RULE_A}})
    return nf.check_raw(
        raw(verdict=verdict, clause=clause, field_label=label, **kw),
        sent(call, **{BOOK: {1}}),
        PAPER,
        books,
    )


def test_the_same_issue_found_in_two_calls_with_one_verdict_is_one_finding_with_its_members():
    got = nf.join([_checked(call="c1"), _checked(call="c2")])
    assert (
        len(got) == 1
        and len(got[0].members) == 2
        and got[0].contradiction is False
        and got[0].ai_verdict == "met"
    )


def test_the_same_issue_with_different_verdicts_is_ONE_query_never_a_winner():
    got = nf.join(
        [_checked("met", "c1"), _checked("not_met", "c2"), _checked("met", "c3")]
    )
    assert (
        len(got) == 1
        and got[0].contradiction is True
        and got[0].ai_verdict == "cannot_tell"
    )
    built = nf.build(
        got[0], rules=[], plan_items={}, tier_lookup=None, book_text=lambda *_a: RULE_A
    )
    assert (
        built.answer["verdict"] == "Query" and built.answer["reasoning"] == nf.DISAGREE
    )


def test_different_clause_field_or_tag_are_different_issues():
    a = _checked(clause="4.1")
    assert len(nf.join([a, _checked(clause="4.2")])) == 2
    assert len(nf.join([a, _checked(label="Marking")])) == 2
    tags = {"f:1:1": "TAG-1", "f:1:2": "TAG-2"}
    both = nf.join(
        [_checked(fact_ids=["f:1:1"]), _checked(fact_ids=["f:1:2"])], fact_tags=tags
    )
    assert len(both) == 2 and {j.tag for j in both} == {"TAG-1", "TAG-2"}


def test_a_finding_with_no_verdict_word_of_the_five_says_nothing_and_is_not_joined():
    assert nf.join([_checked(verdict="maybe")]) == []


def test_the_field_key_is_the_registry_role_else_the_folded_label():
    key, roles = nf.field_key("Design pressure")
    assert key == "design_pressure" and roles == ("design_pressure",)
    assert nf.field_key("Zzq invented label") == ("zzq invented label", ())
    assert (
        nf.finding_id(BOOK, "4.1", key, None)
        == nf.finding_id(BOOK, "4.1", key, None)
        != nf.finding_id(BOOK, "4.2", key, None)
    )


# ---------------------------------------------------------------- the item and the answer


def _built(
    verdict="met", *, rules=RULES, plan=None, tier=lookup_ai, clause_ok=True, **kw
):
    books = books_of(**{BOOK: {1: RULE_A if clause_ok else FILL}})
    c = nf.check_raw(raw(verdict=verdict, **kw), sent(**{BOOK: {1}}), PAPER, books)
    j = nf.join([c])[0]
    return nf.build(
        j,
        rules=rules,
        plan_items=plan or {},
        tier_lookup=tier,
        book_text=lambda b, p: books.book(b).pages.get(p, ""),
    )


def test_a_finding_with_no_matching_rule_is_an_F_item_with_no_tier_and_says_why():
    b = _built(rules=[])
    assert (
        b.item["item_id"].startswith("F-")
        and b.item["rule_tier"] == V.RULE_NOT_APPROVED
    )
    assert (
        b.item["rule_unapproved_why"] == nf.NO_RULE_WHY
        and b.finding.rule_tier is None
        and b.finding.matched_rule_id is None
    )


def test_a_finding_matched_to_a_plan_rule_keeps_that_items_comparator_and_takes_its_tier():
    plan = {"R-1": {"item_id": "R-1", "source": "rule", "rule_version_id": "1", "comparator": ">=", "value": 0.2, "unit": "mm", "field_roles": ["coating_thickness"],
                    "rule_quote_ref": "Q-1", "clause_quote_ref": "C-1", "clause": "4.1", "standard": "STD"}}  # fmt: skip
    b = _built(plan=plan)
    assert (
        b.item["item_id"] == "R-1"
        and b.item["comparator"] == ">="
        and b.finding.rule_tier == V.AI_TIER
        and b.finding.matched_rule_id == "1"
    )
    assert (
        b.item["clause_quote_ref"] == f"N-{b.finding.finding_id}"
        and b.cache[b.item["clause_quote_ref"]]["text"].count(RULE_A[:30]) == 1
    )


def test_a_rule_the_plan_does_not_carry_stays_an_F_item_it_cannot_be_decided_as_that_rule():
    b = _built(plan={})  # matched to rule 1 by text, but the plan has no R-1 item
    assert (
        b.item["item_id"].startswith("F-")
        and b.finding.matched_rule_id is None
        and b.finding.rule_tier is None
    )


def test_an_unverified_clause_quote_gets_no_clause_entry_so_the_exit_cannot_verify_it():
    b = _built(clause_ok=False)
    assert b.cache == {} and b.item["clause_quote_ref"] is None


def test_not_stated_names_only_pages_that_were_sent_and_the_finding_carries_roles_and_page():
    b = _built("not_stated", field_label="Design pressure")
    assert (
        b.answer["verdict"] == "Fail"
        and b.answer["reason_code"] == "absent"
        and b.answer["pages_searched"] == [1, 2]
    )
    assert (
        b.finding.field_roles == ("design_pressure",)
        and b.item["field_roles"] == ["design_pressure"]
        and b.finding.paper_page == 1
    )


# ---------------------------------------------------------------- coverage (role 5)


def _finding(
    rule="1", clause_page=1, verdict="met", contradiction=False, origin="reviewer"
):
    return nf.Finding(
        finding_id="F-x", item_id=f"R-{rule}", origin=origin, book_id=BOOK, clause="4.1", clause_page=clause_page, clause_where=None, clause_scanned=False, field_label="x", field_roles=(),
        tag=None, paper_page=1, paper_quote="q", clause_quote="c", ai_verdict=verdict, matched_rule_id=rule, rule_tier=V.AI_TIER, members=("c1",),
        contradiction=contradiction, read_refs=(),
    )  # fmt: skip


ITEMS = [{"item_id": "R-1"}, {"item_id": "R-2"}, {"item_id": "S-3"}]


def ids(items):
    return [i["item_id"] for i in items]


def test_a_rule_item_is_skipped_only_when_a_finding_matched_its_own_rule_id():
    cov = checklist.plan(ITEMS, [_finding("1")])
    assert ids(cov.to_ask) == ["R-2", "S-3"] and cov.skipped == {"R-1": "F-x"}


def test_an_S_item_is_never_skipped():
    cov = checklist.plan(ITEMS, [_finding("3"), _finding("1"), _finding("2")])
    assert "S-3" in ids(cov.to_ask) and ids(cov.to_ask) == ["S-3"]


def test_when_the_reviewer_returns_nothing_or_fails_every_item_is_asked():
    assert ids(checklist.plan(ITEMS, []).to_ask) == ["R-1", "R-2", "S-3"]
    assert ids(checklist.plan(ITEMS, [_finding("1")], reviewer_ok=False).to_ask) == [
        "R-1",
        "R-2",
        "S-3",
    ]


def test_a_finding_that_cannot_stand_does_not_cover_its_rule():
    for f in (
        _finding("1", clause_page=None),
        _finding("1", contradiction=True),
        _finding("1", verdict="cannot_tell"),
        _finding("1", origin="checklist"),
    ):
        assert ids(checklist.plan(ITEMS, [f]).to_ask) == ["R-1", "R-2", "S-3"], f


def test_a_carried_field_with_no_fact_is_a_required_item_and_a_query_line():
    cov = checklist.plan(
        ITEMS,
        [],
        carried=frozenset({"design_pressure", "design_temperature"}),
        fact_roles=frozenset({"design_temperature"}),
    )
    assert cov.stated_missing == ["design_pressure"] and (
        "Q-design_pressure",
        "field this kind of sheet must carry",
        None,
    ) in [(r.item_id, r.source, r.mentioned_by) for r in cov.required]
    line = checklist.not_stated_lines(cov.stated_missing, 5)[0]
    assert (
        line.item["item_id"] == "Q-design_pressure"
        and "required item not stated: design pressure; pages searched 1 to 5"
        in line.answer["reasoning"]
    )
    assert (
        line.answer["verdict"] == "Query"
        and line.item["rule_tier"] == V.RULE_NOT_APPROVED
    )


# ---------------------------------------------------------------- the reviewer: blocks, the answer, the seam


def test_the_sent_record_is_derived_from_the_blocks_not_from_the_answer():
    group = [
        rev.ChapterText(BOOK, "4", 1, 2, (1, 2), "text a"),
        rev.ChapterText(OTHER, "7", 2, 2, (5,), "text b"),
    ]
    blocks = [
        *rev.prefix_blocks("doc_paper", PAPER, "digest", "context", "run-1"),
        *rev.chapter_blocks(group),
    ]
    got = rev.sent_of("c1", blocks, "m")
    assert got.paper_pages == frozenset({1, 2}) and got.book_pages == {
        BOOK: frozenset({1, 2}),
        OTHER: frozenset({5}),
    }
    assert got.read_refs == (
        (BOOK, "4", 1),
        (OTHER, "7", 2),
    )  # the digest and the note are records, not documents


def test_chapters_are_packed_in_order_under_the_token_limit():
    big = "x" * 3000
    chapters = [
        rev.ChapterText(BOOK, str(i), 1, 1, (i,), big) for i in range(5)
    ]  # 1,000 tokens each
    groups = rev.group_chapters(chapters, limit=2500)
    assert [[c.chapter_id for c in g] for g in groups] == [
        ["0", "1"],
        ["2", "3"],
        ["4"],
    ]
    assert rev.group_chapters(
        [rev.ChapterText(BOOK, "9", 1, 1, (1,), "y" * 9000)], limit=100
    ) == [[rev.ChapterText(BOOK, "9", 1, 1, (1,), "y" * 9000)]]


def test_the_answer_is_parsed_strictly_and_nothing_is_invented():
    good = json.dumps(
        {
            "findings": [
                {
                    "issue": "a b c",
                    "field_label": "F",
                    "paper_page": "2",
                    "verdict": "Not Met",
                    "fact_ids": ["f:1:1", 4],
                },
                {"verdict": "maybe"},
                "junk",
            ]
        }
    )
    got = rev.parse_findings(good)
    assert (
        len(got) == 1
        and got[0]["paper_page"] == 2
        and got[0]["verdict"] == "Not Met"
        and got[0]["fact_ids"] == ["f:1:1"]
    )
    assert rev.parse_findings(json.dumps({"findings": []})) == []
    for bad in (
        None,
        "",
        "no json here",
        json.dumps({"answers": []}),
        '{"findings": "x"}',
    ):
        assert rev.parse_findings(bad) is None
    assert (
        len(rev.parse_findings("Here: " + good + " thanks")) == 1
    )  # an object inside prose is read


class FakeSeam:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, role, blocks, question, *, system, max_tokens):
        self.calls.append((role, blocks, question, system))
        return (
            self.replies[len(self.calls) - 1]
            if len(self.calls) <= len(self.replies)
            else rev.SeamResult(None, "no_reply")
        )


def _ok(findings, call, usd=0.1):
    return rev.SeamResult(json.dumps({"findings": findings}), None, "m1", call, usd)


def test_one_call_per_group_each_with_the_same_prefix_and_its_own_chapters():
    groups = [
        [rev.ChapterText(BOOK, "4", 1, 1, (1,), "t1")],
        [rev.ChapterText(OTHER, "7", 1, 1, (3,), "t2")],
    ]
    prefix = rev.prefix_blocks("doc_paper", PAPER, "digest", "", "run-1")
    seam = FakeSeam(
        [_ok([{"verdict": "met", "field_label": "A"}], "c1"), _ok([], "c2")]
    )
    run = rev.review(seam, prefix, groups, concurrency=1)
    assert [c[0] for c in seam.calls] == [4, 4] and [
        c[1][: len(prefix)] for c in seam.calls
    ] == [prefix, prefix]
    assert [b["document_id"] for b in seam.calls[0][1][len(prefix) :]] == [BOOK] and [
        b["document_id"] for b in seam.calls[1][1][len(prefix) :]
    ] == [OTHER]
    assert (
        run.ok
        and run.answered == 2
        and len(run.raw) == 1
        and run.raw[0][1].book_pages == {BOOK: frozenset({1})}
        and run.usd == pytest.approx(0.2)
    )


def test_when_every_call_fails_or_nothing_is_found_the_reviewer_is_not_ok_and_cost_unknown_is_never_zero():
    groups = [[rev.ChapterText(BOOK, "4", 1, 1, (1,), "t")]]
    prefix = rev.prefix_blocks("doc_paper", PAPER, "", "", "run-1")
    failed = rev.review(
        FakeSeam([rev.SeamResult(None, "reader_budget")]), prefix, groups
    )
    assert (
        not failed.ok
        and failed.failed == 1
        and failed.errors == ["reader_budget"]
        and failed.partly
    )
    empty = rev.review(FakeSeam([_ok([], "c1")]), prefix, groups)
    assert not empty.ok and empty.answered == 1 and empty.raw == []
    unknown = rev.review(
        FakeSeam(
            [rev.SeamResult(json.dumps({"findings": []}), None, "m1", "c1", None)]
        ),
        prefix,
        groups,
    )
    assert unknown.usd is None


def test_a_group_is_not_asked_once_the_stop_says_so_and_the_run_says_partly():
    groups = [[rev.ChapterText(BOOK, str(i), 1, 1, (i,), "t")] for i in (1, 2)]
    stops = iter([False, True])
    seam = FakeSeam([_ok([{"verdict": "met"}], "c1")])
    run = rev.review(
        seam,
        rev.prefix_blocks("doc_paper", PAPER, "", "", "r"),
        groups,
        should_stop=lambda: next(stops),
        concurrency=1,
    )
    assert len(seam.calls) == 1 and run.not_asked == 1 and run.partly and run.ok


# ---------------------------------------------------------------- the exit: today's runner (database world)


@pytest.fixture
def world(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    return s.FakeModel()


def _runner(fake, tier=V.AI_TIER, items=None):
    doc, cache = s.item_doc()
    plan = {i["item_id"]: i for i in doc["items"]}
    runner = run_mod.Runner(
        paper=s.PAPER, items=list(plan.values()) if items is None else items, pages=request_mod.DbPages(db.connect(), s.PAPER),
        clauses=request_mod.ClauseCache(cache), model=agent_claude.LEAD_MODEL, send=fake, env=s.ENV, paper_kind="datasheet",
        tier_lookup=lambda _item: tier,
    )  # fmt: skip
    return runner, plan


def _finding_through(
    world,
    verdict,
    *,
    clause=None,
    paper_quote="Coating thickness: 0.35 mm",
    figs=True,
    tier=V.AI_TIER,
    clause_pages=(1,),
):
    runner, plan = _runner(world, tier)
    quote = clause or s.RULES["R-frame"][0]
    books = standards.BookPages()
    call = nf.Sent("c1", frozenset({1}), {s.STD: frozenset(clause_pages)}, "m1", ())
    extra = (
        {
            "paper_figure": "Coating thickness: 0.35 mm",
            "clause_figure": "coating thickness shall be at least 0.2 mm",
        }
        if figs
        else {}
    )
    rows = [
        {
            "id": "frame",
            "standard_document_id": s.STD,
            "source_text": s.RULES["R-frame"][0],
        }
    ]
    pages = {1: s.PAPER_PAGE}
    built = nf.process(
        [(raw(clause_quote=quote, paper_quote=paper_quote, verdict=verdict, field_label="Design pressure", **extra), call)],
        paper_pages=pages, books=books, rules=rows, plan_items=plan, tier_lookup=lambda _i: tier,
    )  # fmt: skip
    lines = nf.decide_all(runner, built, pages, "fake-lead-model-1")
    return built, lines, runner


def test_a_number_rule_finding_is_decided_by_code_through_the_runners_own_exit(world):
    built, lines, _r = _finding_through(world, "met")
    assert built[0].item["item_id"] == "R-frame" and len(lines) == 1
    line = lines[0]
    assert (
        line["verdict_class"] == "Proven by code"
        and line["verdict"] == "Pass"
        and line["compare"]["decided"] is True
    )
    assert (
        line["field_roles"] == ["design_pressure"]
        and line["paper_page"] == 1
        and line["item_id"] == "R-frame"
    )


def test_the_same_finding_with_a_quote_the_book_does_not_hold_is_never_a_decision(
    world,
):
    built, lines, _r = _finding_through(
        world,
        "met",
        clause="A sentence that no page of the invented rule book holds at all.",
    )
    assert built[0].item["item_id"].startswith("F-")
    assert lines[0]["verdict_class"] not in (
        "Proven by code",
        "AI verdict, two readers agree",
    )
    assert lines[0]["not_proven_reason"]


def test_a_clause_quote_on_a_page_that_was_not_sent_is_never_a_decision(world):
    _b, lines, _r = _finding_through(
        world, "met", clause_pages=(2,)
    )  # the rule stands on page 1; only page 2 was sent
    assert lines[0]["verdict_class"] not in (
        "Proven by code",
        "AI verdict, two readers agree",
    )


def test_a_chapter_finding_with_no_approved_rule_row_stays_an_opinion(world):
    rows_none = None
    _b, lines, _r = _finding_through(
        world, "not_met", tier=None
    )  # the label table does not approve the rule
    assert lines[0]["verdict_class"] in (
        "AI opinion, rule not yet approved",
        "AI opinion, engineer to confirm",
        "Query for the engineer",
    ), lines[0]["verdict_class"]
    assert lines[0]["verdict_class"] != "Proven by code" and rows_none is None


def test_every_non_decision_line_of_a_finding_has_a_reason(world):
    for verdict in ("met", "not_met", "not_stated", "not_applicable", "cannot_tell"):
        _b, lines, _r = _finding_through(world, verdict, figs=False)
        line = lines[0]
        if line["verdict_class"] not in (
            "Proven by code",
            "AI verdict, two readers agree",
        ):
            assert line.get("not_proven_reason"), (verdict, line["verdict_class"])


# ---------------------------------------------------------------- the decision rule: brute force and the source scan


def test_brute_force_a_finding_gives_pass_or_fail_only_with_a_decided_compare_and_the_class_only_when_agreed(
    world,
):
    """Every combination of the finding's verdict, its clause quote, its quote on a sent page, the tier and the second reader's answer."""
    seen = 0
    for verdict, found, sent_page, tier, agree in itertools.product(
        ("met", "not_met", "not_stated", "cannot_tell"),
        (True, False),
        (True, False),
        (V.AI_TIER, None),
        (True, False),
    ):
        world.agree = agree
        quote = (
            s.RULES["R-mark"][0]
            if found
            else "A sentence that no page of the invented rule book holds at all, not even one."
        )
        runner, plan = _runner(world, tier)
        call = nf.Sent(
            "c1",
            frozenset({1}),
            {s.STD: frozenset({1} if sent_page else {2})},
            "m1",
            (),
        )
        rows = [
            {
                "id": "mark",
                "standard_document_id": s.STD,
                "source_text": s.RULES["R-mark"][0],
            }
        ]
        built = nf.process(
            [(raw(clause_quote=quote, paper_quote="Marking blue", paper_page=1, verdict=verdict, field_label="Marking"), call)],
            paper_pages={1: s.PAPER_PAGE}, books=standards.BookPages(), rules=rows, plan_items=plan, tier_lookup=lambda _i: tier,
        )  # fmt: skip
        line = nf.decide_all(runner, built, {1: s.PAPER_PAGE}, "fake-lead-model-1")[0]
        seen += 1
        # a text rule: the code compared no value, so it is never "Proven by code", whatever the readers said
        assert line["verdict_class"] != "Proven by code", (
            verdict,
            found,
            sent_page,
            tier,
            agree,
        )
        verified = found and sent_page
        if line["verdict_class"] == "AI verdict, two readers agree":
            assert (
                verified
                and tier == V.AI_TIER
                and line["quotes_checked"]["paper"]
                and line["quotes_checked"]["clause"]
            )
        if not verified:
            assert line[
                "verdict_class"
            ] != "AI verdict, two readers agree" and line.get("not_proven_reason")
        if line["verdict_class"] != "Proven by code":
            assert line.get("not_proven_reason"), (
                verdict,
                found,
                sent_page,
                tier,
                agree,
            )  # every non-decision says why
    assert seen == 64


def test_no_nine_module_of_this_part_names_a_class_or_a_word_or_sets_a_decision():
    """Source scan (SPEC E): the four modules never name a verdict class or word, never import the wording or the schema, never write a
    line's decided_by."""
    root = Path(__file__).resolve().parent.parent / "app"
    for name in (
        "nine_reviewer.py",
        "nine_findings.py",
        "nine_match.py",
        "nine_checklist.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert not re.search(
            r"\bCLASS_[A-Z_]+|\bWORD_[A-Z_]+|THINKS_(MET|NOT_MET)\b", text
        ), name
        assert (
            "agent_review_wording" not in text and "agent_review_schema" not in text
        ), name
        assert not re.search(
            r"\[\s*[\"'](verdict_class|word|decided_by|verdict_label)[\"']\s*\]\s*=|[\"'](verdict_class|verdict_label|decided_by)[\"']\s*:",
            text,
        ), name
