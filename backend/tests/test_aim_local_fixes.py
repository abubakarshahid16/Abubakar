"""The local model's first valve run (26 Nov 2026): 31 checklist items against Claude's 93, 58 of 61 points "Question", numbers on
5 and none compared. The fixes: the same rule material on every model (read in smaller calls, never cut), the attack per batch
on the local model, and code reading the numbers when unambiguous. Invented rules and papers; no model, no network."""

from __future__ import annotations

from app.aim_review import budget
from app.aim_review import checklist as CL
from app.aim_review import code_numbers as CN
from app.aim_review import material as MT
from app.aim_review import steps as S
from app.aim_review.paper import Paper

RULE = "The corrosion allowance of pressure parts shall be not less than 3 mm."


def _sel(n_rules: int) -> dict:
    pool = [{"book": "b1", "subject": "s", "tagged": True, "page": 1 + k // 10, "clause": f"4.{k}", "id": f"r{k}",
             "source_text": f"Invented rule {k}: the invented value shall be not less than {k} mm. " + "x" * 400,
             "requirement_text": ""} for k in range(n_rules)]  # fmt: skip
    return {
        "_pool": pool,
        "books": [
            {
                "book": "b1",
                "alias": "B1",
                "identifier": "Invented Book",
                "chosen_subjects": "all",
            }
        ],
    }


def test_the_local_model_reads_the_same_rule_material_as_claude_in_smaller_calls():
    sel = _sel(120)
    claude_rows, claude_stats = MT.material(sel, None)
    with budget.using(budget.LOCAL):
        local_rows, local_stats = MT.material(sel, None)
        local_batches = MT._batches(local_rows)
    assert [r["req_id"] for r in local_rows] == [
        r["req_id"] for r in claude_rows
    ]  # nothing cut
    assert (
        local_stats == claude_stats
        and len(local_batches) > len(MT._batches(claude_rows)) > 0
    )
    assert all(
        sum(len(MT._material_line(r)) for r in b) <= budget.LOCAL.batch_chars
        for b in local_batches
    )


class _Attack:
    def __init__(self):
        self.calls = []

    def ask(self, **kw):
        self.calls.append(kw)
        return {
            "remove": [{"id": f"C{len(self.calls):03d}", "why": "invented"}],
            "fix": [],
            "add": [],
        }


def test_the_attack_reads_every_batch_on_the_local_model_and_once_on_claude():
    sel = _sel(120)
    made = {"items": [{"id": f"C{k:03d}", "topic": "t", "what_to_check": "w", "book": "B1", "clause": "4.1", "page": 1,
                       "rule_quote": "q", "applies_when": "always", "paper_fields": [], "kind": "limit",
                       "source": "held standard"} for k in range(1, 9)]}  # fmt: skip
    ident = {
        "kind": "datasheet",
        "equipment_type": None,
        "subject": "invented",
        "service": "",
    }
    claude = _Attack()
    CL.s3_attack(claude, ident, sel, made, None, "claude-sonnet-5-5")
    local = _Attack()
    with budget.using(budget.LOCAL):
        got = CL.s3_attack(local, ident, sel, made, None, "local")
        n = len(MT._batches(MT.material(sel, None)[0]))
    assert len(claude.calls) == 1 and len(local.calls) == n > 1
    assert len(got["attack"]["removed"]) == n  # every batch's answer counted


def test_code_reads_the_numbers_only_when_the_rule_and_the_quote_hold_one_each():
    assert CN.numbers(RULE, "Corrosion allowance (pressure parts): 1.5 mm") == {
        "paper_value": "1.5", "paper_unit": "mm", "operator": ">=", "rule_value": "3", "rule_unit": "mm"}  # fmt: skip
    assert (
        CN.numbers(RULE, "Corrosion allowance: 1.5 mm shell, 3 mm head") is None
    )  # two values: the judge pairs them
    assert (
        CN.numbers("Values shall be between 3 mm and 6 mm.", "Allowance: 1.5 mm")
        is None
    )  # no single limit
    assert CN.numbers(RULE, "Design pressure: 20 barg") is None  # another quantity


PAPER = Paper(
    paper_id="doc_inv_sheet",
    pages={2: "Invented sheet.\nCorrosion allowance (pressure parts): 1.5 mm\n"},
)
ITEM = {"id": "C001", "book": "B1", "book_id": "b1", "clause": "6.4", "source": S.HELD, "topic": "corrosion allowance",
        "what_to_check": "corrosion allowance at least the rule's minimum", "rule_quote": RULE, "applies_when": "always",
        "paper_fields": ["Corrosion allowance"], "paper_pages": [2], "kind": "limit"}  # fmt: skip
ANSWER = {"id": "C001", "label": "Question", "field": "Corrosion allowance", "page": 2,
          "quote": "Corrosion allowance (pressure parts): 1.5 mm", "comment": "Please confirm the allowance."}  # fmt: skip


def test_on_the_local_model_a_question_on_a_stated_value_that_breaks_the_rule_is_a_fail_by_code():
    with budget.using(budget.LOCAL):
        line = S._decide(ITEM, dict(ANSWER), PAPER, {}, "")
    assert line["label"] == "Not met" and CN.NOTE in line["code"]
    on_claude = S._decide(ITEM, dict(ANSWER), PAPER, {}, "")
    assert on_claude["label"] == "Question" and CN.NOTE not in (
        on_claude.get("code") or ""
    )  # Claude: unchanged until scored


def test_a_value_left_open_or_an_unverified_quote_is_never_compared_by_code():
    with budget.using(budget.LOCAL):
        open_ = S._decide(ITEM, {**ANSWER, "deferred": True}, PAPER, {}, "")
        unfound = S._decide(
            ITEM, {**ANSWER, "quote": "Corrosion allowance: 1.0 mm"}, PAPER, {}, ""
        )
    assert open_["label"] == "Question" and unfound["label"] == "Question"
    assert CN.NOTE not in (open_.get("code") or "") + (unfound.get("code") or "")


def test_on_the_local_model_a_chosen_book_offers_every_subject():
    """The rerun of 26 Nov: the same 20 books as Claude, but the 14B chose narrow subjects (40k characters of material)."""
    cat = [{"alias": "B1", "book": "b1", "subjects": ["s1", "s2", "s3"], "required": True},
           {"alias": "B2", "book": "b2", "subjects": ["s1", "s2"], "required": False}]  # fmt: skip
    out = {
        "books": [
            {"alias": "B1", "subjects": ["s1"]},
            {"alias": "B2", "subjects": ["s2"]},
        ]
    }
    on_claude = {
        b["book"]: b["chosen_subjects"] for b in CL._chosen(out, cat, {"b1": "governs"})
    }
    with budget.using(budget.LOCAL):
        local = {
            b["book"]: b["chosen_subjects"]
            for b in CL._chosen(out, cat, {"b1": "governs"})
        }
    assert on_claude == {"b1": ["s1"], "b2": ["s2"]} and local == {
        "b1": "all",
        "b2": "all",
    }


TWO_LINES = Paper(
    paper_id="doc_inv_two_lines",
    pages={1: "Invented sheet.\nCorrosion allowance (pressure parts)\n1.5 mm\n"},
)


def test_on_the_local_model_a_label_and_its_value_on_two_lines_are_one_quote_and_code_compares_it():
    """The rerun of 26 Nov: the 14B joined a label and its value with a colon; 17 of 52 quotes failed, so code compared none and
    a Met or Not met fell back to a Question."""
    from app.aim_review import verify as V

    joined = "Corrosion allowance (pressure parts): 1.5 mm"
    answer = {**ANSWER, "page": 1, "quote": joined, "label": "Not met",
              "numbers": {"paper_value": "1.5", "paper_unit": "mm", "operator": ">=", "rule_value": "3", "rule_unit": "mm"}}  # fmt: skip
    claude = S._decide(ITEM, dict(answer), TWO_LINES, {}, "")
    with budget.using(budget.LOCAL):
        local = S._decide(ITEM, dict(answer), TWO_LINES, {}, "")
        asked = S._decide(
            ITEM, {**ANSWER, "page": 1, "quote": joined}, TWO_LINES, {}, ""
        )  # a Question, no numbers given
        assert not V.quote_in(
            "Corrosion allowance (pressure parts): 2.5 mm", TWO_LINES.pages[1]
        )  # a changed number: never
        assert not V.quote_in(
            "1.5 mm Corrosion allowance (pressure parts)", TWO_LINES.pages[1]
        )  # out of order: never
    assert (
        claude["label"] == "Question"
        and "paper quote not found by code" in claude["code"]
    )  # Claude: word for word, unchanged
    assert local["label"] == "Not met" and V.LOOSE_NOTE in local["code"]
    assert (
        asked["label"] == "Not met" and CN.NOTE in asked["code"]
    )  # code read the numbers from the joined quote


class _Retry:
    """A checklist answer whose 14 held items all quote the rule wrongly, then a retry answer per call."""

    def __init__(self):
        self.calls = []

    def ask(self, **kw):
        self.calls.append(kw)
        if kw["step"] == "aim_checklist":
            return {"items": [{"topic": f"t{k}", "what_to_check": "w", "book": "B1", "clause": "4.1", "page": 1,
                               "rule_quote": "words no rule holds", "applies_when": "always", "paper_fields": ["f"],
                               "paper_pages": [1], "kind": "limit", "source": "held standard"} for k in range(14)]}  # fmt: skip
        return {"items": []}


class _Book:
    def page(self, _doc, _n):
        return "Invented rule page."

    def pages(self, _doc):
        return {1: "Invented rule page."}


def test_the_checklist_retry_asks_in_small_groups_on_the_local_model_and_once_on_claude():
    """The 14B run at 7522b5dd stopped: one retry answer for every item with an unfound quote passed its 8,000 tokens."""
    sel = _sel(3)
    sel["books"] = [
        {**b, "committee": "", "why": "invented", "required": False}
        for b in sel["books"]
    ]
    ident = {
        "kind": "datasheet",
        "equipment_type": None,
        "subject": "invented",
        "service": "",
    }
    claude = _Retry()
    CL.s3_checklist(claude, ident, sel, _Book(), "claude-sonnet-5-5")
    local = _Retry()
    with budget.using(budget.LOCAL):
        CL.s3_checklist(local, ident, sel, _Book(), "local")
    retries = lambda m: [c for c in m.calls if c["step"] == "aim_checklist_retry"]  # noqa: E731
    # local: ONE retry call per batch since F's run 09105c4b (18 retry calls ran it past the swap rule); was one per group
    assert len(retries(claude)) == 1 and len(retries(local)) == 1
    assert retries(local)[0]["prompt"].count('"topic"') == CL.RETRY_LOCAL


class _Knowledge:
    def __init__(self):
        self.calls = []

    def ask(self, **kw):
        self.calls.append(kw)
        return {"items": []}


def test_the_knowledge_step_asks_one_not_held_standard_per_call_on_the_local_model():
    """The 9B's knowledge answer ran past its limit on every run (0 of 6 items): one standard per call on local."""
    sel = {
        **_sel(1),
        "not_held": [
            {"name": "Invented Std A"},
            {"name": "Invented Std B"},
            {"name": "Invented Std C"},
        ],
    }
    ident = {
        "kind": "datasheet",
        "equipment_type": None,
        "subject": "invented",
        "service": "",
    }
    made = {"items": []}
    claude = _Knowledge()
    CL.s3_knowledge(claude, ident, sel, made, "claude-sonnet-5-5")
    local = _Knowledge()
    with budget.using(budget.LOCAL):
        CL.s3_knowledge(local, ident, sel, made, "local")
    assert len(claude.calls) == 1 and len(local.calls) == 3
    assert all(
        p in c["prompt"]
        for c, p in zip(
            local.calls,
            ("Invented Std A", "Invented Std B", "Invented Std C"),
            strict=True,
        )
    )


def test_on_the_local_model_a_met_code_could_not_prove_is_never_sent():
    from app import aim_review
    from app.aim_review import prompts as P
    from app.aim_review.engine import to_line

    unproven = {**ANSWER, "label": "Met", "numbers": {"paper_value": "2", "paper_unit": "mm", "operator": ">=",
                                                     "rule_value": "3", "rule_unit": "mm"}}  # fmt: skip
    with budget.using(budget.LOCAL):
        line = S._decide(
            ITEM, unproven, PAPER, {}, ""
        )  # 2 mm is not in the quote: code cannot prove it
    assert line["label"] == "Question" and aim_review.AI_MET_UNPROVEN in line["code"]
    assert not aim_review.sendable(to_line(1, line))
    with budget.using(budget.LOCAL):
        assert (
            "exactly as PRINTED (never converted or worked out" in P.s4_task()
        )  # the local model's judge line
    assert "exactly as PRINTED" not in P.s4_task()  # Claude: main's judge text


class _Cuts(_Retry):
    """The retry answer is cut whenever it is asked about more than 2 items; the attack answer is cut on its first call."""

    def ask(self, **kw):
        from app.aim_review.engine import StepFailed

        self.calls.append(kw)
        if kw["step"] == "aim_checklist":
            self.calls.pop()
            return super().ask(**kw)
        if kw["step"] == "aim_checklist_retry" and kw["prompt"].count('"topic"') > 2:
            raise StepFailed("aim_checklist_retry: stop_max_tokens")
        return {"items": []}


def test_on_the_local_model_a_cut_retry_answer_is_never_used_its_group_is_asked_again_in_halves():
    """Lead-4 (26 Nov 2026): a cut answer must never be used; it is retried smaller. Claude: a cut is raised, as before."""
    import pytest

    from app.aim_review.engine import StepFailed

    sel = _sel(3)
    sel["books"] = [
        {**b, "committee": "", "why": "invented", "required": False}
        for b in sel["books"]
    ]
    ident = {
        "kind": "datasheet",
        "equipment_type": None,
        "subject": "invented",
        "service": "",
    }
    local = _Cuts()
    with budget.using(budget.LOCAL):
        CL.s3_checklist(
            local, ident, sel, _Book(), "local"
        )  # completes: every cut group was split until it fit
    sizes = [
        c["prompt"].count('"topic"')
        for c in local.calls
        if c["step"] == "aim_checklist_retry"
    ]
    # every item of the one retry call (RETRY_LOCAL of the 14; the rest are counted, not asked) asked once in an uncut answer
    assert max(sizes) > 2 and sum(s for s in sizes if s <= 2) == CL.RETRY_LOCAL
    with pytest.raises(StepFailed):
        CL.s3_checklist(_Cuts(), ident, sel, _Book(), "claude-sonnet-5-5")


class _AttackCut(_Attack):
    def ask(self, **kw):
        from app.aim_review.engine import StepFailed

        self.calls.append(kw)
        if len(self.calls) == 1:
            raise StepFailed("aim_attack: stop_max_tokens")
        return {
            "remove": [{"id": f"C{len(self.calls):03d}", "why": "invented"}],
            "fix": [],
            "add": [],
        }


def test_on_the_local_model_a_cut_attack_answer_of_one_batch_is_set_aside_and_the_others_count():
    sel = _sel(120)
    made = {"items": [{"id": f"C{k:03d}", "topic": "t", "what_to_check": "w", "book": "B1", "clause": "4.1", "page": 1,
                       "rule_quote": "q", "applies_when": "always", "paper_fields": [], "kind": "limit",
                       "source": "held standard"} for k in range(1, 9)]}  # fmt: skip
    ident = {
        "kind": "datasheet",
        "equipment_type": None,
        "subject": "invented",
        "service": "",
    }
    local = _AttackCut()
    with budget.using(budget.LOCAL):
        got = CL.s3_attack(local, ident, sel, made, None, "local")
        n = len(MT._batches(MT.material(sel, None)[0]))
    assert (
        len(local.calls) == n and len(got["attack"]["removed"]) == n - 1
    )  # the cut one is not used


def test_the_local_answer_shape_always_closes_items_and_text_are_bounded():
    """F's 14B run at 7dd97183: answers of 8,192 tokens out of 1,500 in, a list that never ended. The forced shape bounds it."""
    from app.aim_review import answer_schema as A

    items = A.for_step("aim_checklist")["properties"]["items"]
    assert items["maxItems"] == A.MAX_ITEMS and all(
        v.get("maxLength") or v.get("maxItems") or v.get("anyOf")
        for v in items["items"]["properties"].values()
    )
    assert (
        A.for_step("aim_judge")["properties"]["judgments"]["maxItems"]
        == A.MAX_JUDGMENTS
    )


class _Runaway(_Retry):
    def ask(self, **kw):
        from app.aim_review.engine import StepFailed

        self.calls.append(kw)
        if kw["step"] == "aim_checklist":
            raise StepFailed("aim_checklist: stop_max_tokens")
        return {"items": []}


def test_a_local_checklist_answer_still_cut_after_halving_is_set_aside_and_never_stops_the_run():
    import pytest

    from app.aim_review.engine import StepFailed

    sel = _sel(6)
    sel["books"] = [
        {**b, "committee": "", "why": "invented", "required": False}
        for b in sel["books"]
    ]
    ident = {
        "kind": "datasheet",
        "equipment_type": None,
        "subject": "invented",
        "service": "",
    }
    local = _Runaway()
    with budget.using(budget.LOCAL):
        got = CL.s3_checklist(
            local, ident, sel, _Book(), "local"
        )  # every answer cut: no items, but the run goes on
    assert (
        got["items"] == []
        and sum(c["step"] == "aim_checklist" for c in local.calls) > 1
    )  # halves were asked first
    with pytest.raises(StepFailed):
        CL.s3_checklist(
            _Runaway(), ident, sel, _Book(), "claude-sonnet-5-5"
        )  # Claude: raised, as before


def test_the_local_checklist_call_gets_an_item_cap_and_answer_room_from_its_batch():
    """Lead-4, 26 Nov 2026: a fixed cap and 8,192 tokens let the 14B loop on its SMALLEST batches."""
    from app.aim_review import answer_schema as A
    from app.aim_review import retry as RT

    with budget.using(budget.LOCAL):
        most, tokens = RT.room([{}] * 3, CL.S3_MAX_TOKENS)
        assert (most, tokens) == (6, RT.BASE_TOKENS + RT.TOKENS_PER_ITEM * 6)
        with A.items_at_most(most):
            assert A.for_step("aim_checklist")["properties"]["items"]["maxItems"] == 6
    assert (
        A.for_step("aim_checklist")["properties"]["items"]["maxItems"] == A.MAX_ITEMS
    )  # outside a call: the fixed cap
    assert RT.room([{}] * 3, CL.S3_MAX_TOKENS) == (
        None,
        CL.S3_MAX_TOKENS,
    )  # Claude: as before


def test_a_repeating_local_answer_is_cut_at_its_first_repeat():
    from app.aim_review import retry as RT

    a, b = (
        {"topic": "t1", "what_to_check": "w", "rule_quote": "q"},
        {"topic": "t2", "what_to_check": "w", "rule_quote": "q"},
    )
    looping = [a, b, dict(a), dict(b), dict(a)]
    with budget.using(budget.LOCAL):
        assert RT.unique(looping) == [a, b]
        assert RT.unique([a, b]) == [a, b]
    assert RT.unique(looping) == looping  # Claude: unchanged


def _rules(book: str, clauses: list[str], chars: int = 600) -> list[dict]:
    return [{"rule": f"R{book}{i}", "book": book.upper(), "book_id": book, "clause": c, "page": 1, "text": "x" * chars,
             "req_id": f"r{book}{i}"} for i, c in enumerate(clauses)]  # fmt: skip


def test_on_the_local_model_a_call_takes_whole_books_and_clause_groups_never_split():
    """Owner via the planner (26 Nov 2026 05:20): one whole book or clause group per call, never a clause split; a group
    larger than the size is taken by its next clause level; a book with no stored rules is read with all its pages together."""
    rows = (_rules("b1", ["4.1", "4.2", "4.3", "5.1", "5.2"]) + _rules("b2", [f"6.{i}" for i in range(20)])
            + [{"page_of": "B3", "book_id": "b3", "page": p, "page_text": "y" * 900} for p in (1, 2, 3)])  # fmt: skip
    with budget.using(budget.LOCAL):
        batches = MT._batches(rows)
    where = {}
    for i, b in enumerate(batches):
        for r in b:
            key = (r["book_id"], str(r.get("clause", "pages")))
            where.setdefault(key, set()).add(i)
    assert all(len(v) == 1 for v in where.values())  # every group in exactly one call
    top = {}
    for i, b in enumerate(batches):
        for r in b:
            top.setdefault(
                (r["book_id"], str(r.get("clause", "pages")).split(".")[0]), set()
            ).add(i)
    assert (
        len(top[("b1", "4")]) == len(top[("b1", "5")]) == len(top[("b3", "pages")]) == 1
    )  # within the size: one call
    assert (
        len(top[("b2", "6")]) > 1
    )  # a group over the size: taken by its next clause level, each clause whole
    assert sum(len(b) for b in batches) == len(rows)  # nothing lost
    on_claude = MT._batches(rows)
    assert any(len({r["book_id"] for r in b}) > 1 for b in on_claude) or len(
        on_claude
    ) != len(batches)  # Claude packs rows


def test_a_cut_answer_is_asked_again_in_halves_at_a_group_boundary_on_the_local_model():
    rows = _rules("b1", ["4.1", "4.2", "5.1", "5.2", "5.3"])
    with budget.using(budget.LOCAL):
        one, two = MT.halves(rows)
    assert {r["clause"].split(".")[0] for r in one} == {"4"} and {
        r["clause"].split(".")[0] for r in two
    } == {"5"}
    assert MT.halves(rows) == (rows[:2], rows[2:])  # Claude: by rows, as before


def test_one_clause_larger_than_the_size_goes_whole_in_a_call_of_its_own():
    rows = _rules("b1", ["7.1"] * 3, chars=4_000) + _rules(
        "b1", ["8.1"]
    )  # one clause number, 12,000 characters
    with budget.using(budget.LOCAL):
        batches = MT._batches(rows)
    assert [len(b) for b in batches] == [3, 1] and {
        r["clause"] for r in batches[0]
    } == {"7.1"}


def test_a_no_rule_books_long_pages_split_only_where_a_page_begins_with_a_clause():
    pages = [{"page_of": "B1", "book_id": "b", "page": n, "page_text": ("4.1 Invented clause. " if n == 2 else "") + "z" * 4_000}
             for n in range(4)]  # fmt: skip
    with budget.using(budget.LOCAL):
        batches = MT._batches(pages)
    assert [[r["page"] for r in b] for b in batches] == [
        [0, 1],
        [2, 3],
    ]  # only before the page that opens clause 4.1
