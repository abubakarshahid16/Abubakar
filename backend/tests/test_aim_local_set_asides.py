"""Review of update 9, M5 and M6 (lead-4, 26 Nov 2026). On the local model a cut answer is never used: each one it sets aside
(a checklist batch, an attack batch, a retry item, a repeating answer) is a row of the run's calls and is said, with its count,
under "Steps that did not run" on the page and the team file. On Claude nothing changes. The local model's measured note is in
the score line the page draws. Invented values only."""

from __future__ import annotations

import pytest

from app import aim_review_gate, aim_review_local_view, aim_review_view
from app.aim_review import budget, faults
from app.aim_review import checklist as CL
from app.aim_review import retry as RT
from app.aim_review.engine import StepFailed
from tests.test_aim_local_fixes import _Book, _Retry, _Runaway, _sel

IDENT = {
    "kind": "datasheet",
    "equipment_type": None,
    "subject": "invented",
    "service": "",
}


def _said(calls) -> dict:
    rows = [c.as_dict() if hasattr(c, "as_dict") else c for c in calls]
    return {x["step"]: x for x in aim_review_view.steps_not_applied(rows)}


def _books(sel):
    sel["books"] = [
        {**b, "committee": "", "why": "invented", "required": False}
        for b in sel["books"]
    ]
    return sel


class _RetryAlwaysCut(_Retry):
    def ask(self, **kw):
        self.calls.append(kw)
        if kw["step"] == "aim_checklist_retry":
            raise StepFailed("aim_checklist_retry: stop_max_tokens")
        return super().ask(**kw)


def test_cut_checklist_batches_are_counted_under_steps_that_did_not_run():
    calls: list = []
    with faults.recording(calls), budget.using(budget.LOCAL):
        got = CL.s3_checklist(_Runaway(), IDENT, _books(_sel(6)), _Book(), "local")
    n = sum(1 for c in calls if c.step == "aim_checklist_cut")
    assert got["items"] == [] and n >= 1
    said = _said(calls)["aim_checklist_cut"]
    assert said["count"] == n
    assert said["sentence"].startswith(
        f"{n} checklist batch{'' if n == 1 else 'es'} gave no items (answer cut)"
    )


def test_an_attack_item_cut_or_given_no_verdict_is_counted_and_kept():
    one = [
        {
            "step": "aim_attack_item_cut",
            "ok": False,
            "code": "an attack item not applied: answer cut",
        }
    ]
    assert _said(one)["aim_attack_item_cut"]["sentence"] == (
        "1 checklist item was not attacked (answer cut) and was kept as the first engineer wrote it."
    )
    two = [
        {
            "step": "aim_attack_no_verdict",
            "ok": False,
            "code": "an attack item not applied: no verdict in the answer",
        }
    ] * 2
    assert _said(two)["aim_attack_no_verdict"]["sentence"] == (
        "2 checklist items got no attack verdict (no verdict in the answer) and were kept as the first engineer "
        "wrote them."
    )


def test_retry_items_whose_answer_stays_cut_are_left_out_counted_and_never_stop_the_run():
    calls: list = []
    with faults.recording(calls), budget.using(budget.LOCAL):
        got = CL.s3_checklist(
            _RetryAlwaysCut(), IDENT, _books(_sel(3)), _Book(), "local"
        )
    said, capped = _said(calls)["aim_retry_dropped"], _said(calls)["aim_retry_capped"]
    # the 14 invented items all quote the rule wrongly: the one retry call asks RETRY_LOCAL of them and every answer is cut;
    # the rest are not asked (one retry call per batch). None is kept, each is counted once.
    assert said["count"] == CL.RETRY_LOCAL and capped["count"] == 14 - CL.RETRY_LOCAL
    assert not [i for i in got["items"] if i["source"] == "held standard"]
    assert said["sentence"].startswith(
        f"{CL.RETRY_LOCAL} checklist items were left out: their rule quote was not found"
    )
    assert (
        capped["sentence"]
        == (  # with its cause (lead-4, 26 Nov 2026: the 117 of the 9B run could not be broken down)
            f"{14 - CL.RETRY_LOCAL} checklist items were left out without a second ask (the local model makes one retry call per "
            "batch): the quote is not in the book's words (paraphrased)."
        )
    )
    with pytest.raises(StepFailed):  # Claude: a cut is raised, as before
        CL.s3_checklist(
            _RetryAlwaysCut(), IDENT, _books(_sel(3)), _Book(), "claude-sonnet-5-5"
        )


def test_a_repeating_answer_is_counted_and_claude_records_nothing():
    a, b = (
        {"topic": "t1", "what_to_check": "w", "rule_quote": "q"},
        {"topic": "t2", "what_to_check": "w", "rule_quote": "q"},
    )
    calls: list = []
    with faults.recording(calls):
        with budget.using(budget.LOCAL):
            RT.unique([a, b, dict(a)])
            RT.unique([a, dict(a)])
        RT.unique([a, b, dict(a)])  # Claude: unchanged and not recorded
    said = _said(calls)["aim_repeat_cut"]
    assert said["count"] == 2
    assert said["sentence"] == (
        "2 checklist answers repeated themselves and were cut at the first repeat (the items before the repeat were used)."
    )


def test_one_set_aside_is_said_in_the_singular_and_other_steps_keep_their_words():
    one = [
        {
            "step": "aim_checklist_cut",
            "ok": False,
            "code": "a checklist batch not applied: answer cut",
        }
    ]
    assert _said(one)["aim_checklist_cut"]["sentence"] == (
        "1 checklist batch gave no items (answer cut): the rules in it were not made checklist items."
    )
    two = [
        {
            "step": "aim_second_read",
            "ok": False,
            "code": "second reader not applied: no_json",
        }
    ] * 2
    assert _said(two)["aim_second_read"]["sentence"].startswith(
        "The second reader did not run on this sheet (no_json)"
    )


def test_the_run_page_score_line_of_a_local_run_holds_the_local_models_measured_note():
    """The note is the run's OWN model's (review of update 10, M4): the 9B's numbers on a 9B run, "not yet scored" on any
    other model, never another model's numbers."""
    nine = {"local": True, "models": ["qwen3.5:9b-q4_K_M"], "by_step": {}}
    line = aim_review_local_view.measured({"kind": "datasheet"}, nine)["sentence"]
    assert (
        aim_review_gate.LOCAL_ROUGH_DRAFT_SENTENCE in line
        and aim_review_gate.LOCAL_TEST_NOTE in line
        and aim_review_gate.NOT_YET_SCORED
        not in line  # a measured model never says "not yet scored"
    )
    assert line.index(aim_review_gate.LOCAL_ROUGH_DRAFT_SENTENCE) < line.index(
        aim_review_gate.LOCAL_TEST_NOTE
    )
    other = {"local": True, "models": ["invented-local:1b"], "by_step": {}}
    line = aim_review_local_view.measured({"kind": "datasheet"}, other)["sentence"]
    assert aim_review_gate.LOCAL_TEST_NOTE not in line
    assert "Local model (invented-local:1b): not yet scored." in line
    assert aim_review_gate.LOCAL_ROUGH_DRAFT_SENTENCE in line
    claude = aim_review_local_view.measured({"kind": "datasheet"}, {"local": False})
    assert claude is None or aim_review_gate.LOCAL_TEST_NOTE not in (
        claude.get("sentence") or ""
    )


class _BookHoldsRules:
    """A book whose stored page holds the invented rules' own words."""

    def __init__(self, sel):
        self.words = "\n".join(r["source_text"] for r in sel["_pool"])

    def page(self, _doc, _n):
        return self.words

    def pages(self, _doc):
        return {1: self.words}


def test_on_the_local_model_a_quote_not_found_takes_its_cited_clauses_words_by_code_with_no_retry_call():
    """F's 14B run 09105c4b: 18 retry calls of about 20 s each ran the review past the swap rule."""
    sel = _books(_sel(3))
    local = _Retry()
    with budget.using(budget.LOCAL):
        got = CL.s3_checklist(local, IDENT, sel, _BookHoldsRules(sel), "local")
    held = [i for i in got["items"] if i["source"] == "held standard"]
    rule = next(r["source_text"] for r in sel["_pool"] if r["clause"] == "4.1")
    assert not [c for c in local.calls if c["step"] == "aim_checklist_retry"]
    assert len(held) == 14 and {i["rule_quote"] for i in held} == {rule}
    claude = _Retry()  # Claude: asked again, as before
    CL.s3_checklist(
        claude, IDENT, _books(_sel(3)), _BookHoldsRules(sel), "claude-sonnet-5-5"
    )
    assert [c for c in claude.calls if c["step"] == "aim_checklist_retry"]


def test_a_clause_that_names_no_rule_or_two_rules_is_still_asked_again():
    batch = [
        {
            "rule": "R0001",
            "book": "B1",
            "clause": "4.1",
            "page": 1,
            "text": "Rule one words.",
        },
        {
            "rule": "R0002",
            "book": "B1",
            "clause": "4.2",
            "page": 1,
            "text": "Rule two words.",
        },
        {
            "rule": "R0003",
            "book": "B1",
            "clause": "4.2",
            "page": 2,
            "text": "Rule three words [CUT: rule text longer than shown]",
        },
    ]
    items = [
        {"book": "B1", "clause": c, "rule_quote": "x"} for c in ("4.1.", "4.2", "9.9")
    ]
    with budget.using(budget.LOCAL):
        fixed, ask = RT.by_code(items, batch, lambda it: True)
        assert [i["rule_quote"] for i in fixed] == ["Rule one words."] and [
            i["clause"] for i in ask
        ] == ["4.2", "9.9"]
        assert RT.by_code(items[:1], batch, lambda it: False) == (
            [],
            items[:1],
        )  # not found on the page: asked again
    assert RT.by_code(items, batch, lambda it: True) == (
        [],
        items,
    )  # Claude: nothing by code


def _rule(rule, book, clause, page, text):
    return {"rule": rule, "book": book, "clause": clause, "page": page, "text": text}


BATCH = [
    _rule(
        "R0001",
        "B1",
        "5.2",
        4,
        "The invented gasket shall be rated for the flange class.",
    ),
    _rule(
        "R0002",
        "B1",
        "5.2",
        4,
        "The invented bolting shall be coated against rust in salt air.",
    ),
    _rule(
        "R0003",
        "B1",
        "5.2.1",
        5,
        "The invented bolting nuts shall carry the heat number stamp.",
    ),
    _rule(
        "R0004",
        "B2",
        "7.3",
        9,
        "The invented coating of the gasket shall be applied for the flange in three coats.",
    ),
]


def test_a_quote_with_a_wrong_page_takes_the_rule_of_its_own_book_and_clause_holding_most_of_its_words():
    """F's 14B run e19e3d8a: 126 quotes not found and almost none fixed by code, as a clause often holds several stored rules."""
    near = {
        "book": "B1",
        "clause": "5.2.1",
        "page": 2,
        "rule_quote": "invented bolting shall be coated against rust",
    }
    loose = {
        "book": "B1",
        "clause": "5.2",
        "page": 4,
        "rule_quote": "gaskets and bolts must suit the service conditions",
    }
    with budget.using(budget.LOCAL):
        fixed, ask = RT.by_code([near, loose], BATCH, lambda it: True)
    # the cited "5.2.1" is under "5.2": its parent's rule is taken, with the book unchanged
    assert [(i["book"], i["clause"], i["page"], i["rule_quote"]) for i in fixed] == [
        ("B1", "5.2", 4, BATCH[1]["text"])
    ]
    assert ask == [
        loose
    ]  # too few of its content words in any rule of its clause: asked again


def test_a_rule_of_another_book_or_clause_is_never_taken():
    """The update 10 reviewer's case: a coating item cited to book 1 clause 4.1 took a gasket rule of book 2 clause 7.3, and
    code then compared the paper against that rule's limit."""
    coating = {
        "book": "B1",
        "clause": "4.1",
        "page": 3,
        "rule_quote": "the invented coating of the gasket shall be applied for the flange",
    }
    other_clause = {
        "book": "B1",
        "clause": "6.1",
        "page": 4,
        "rule_quote": "invented bolting shall be coated against rust",
    }
    with budget.using(budget.LOCAL):
        assert RT.by_code([coating, other_clause], BATCH, lambda it: True) == (
            [],
            [coating, other_clause],
        )


def test_grammar_words_alone_never_make_a_match():
    words = {
        "book": "B1",
        "clause": "5.2",
        "page": 4,
        "rule_quote": "the shall be for the and with all of it",
    }
    with budget.using(budget.LOCAL):
        assert RT.by_code([words], BATCH, lambda it: True) == ([], [words])
    assert RT._words("The shall be for and of it") == set()


def test_the_local_checklist_shape_requires_the_book_clause_page_quote_and_source_of_every_item():
    """F's 9B run on update 10 (91f40e4f): optional keys were left out, so about 190 items had no book and no quote to find."""
    from app.aim_review import answer_schema as A

    for step in ("aim_checklist", "aim_checklist_retry", "aim_checklist_knowledge"):
        item = A.for_step(step)["properties"]["items"]["items"]
        assert (
            {"book", "clause", "page", "rule_quote", "source"}
            <= set(item["required"])
            <= set(item["properties"])
        )


def test_a_kept_items_clause_must_hold_its_quote_or_it_is_cited_to_the_one_clause_that_does():
    """F's 9B run on update 10: eleven items in a row cited one clause for unrelated subjects; the quote check read the page."""
    from app.aim_review import citing

    sel = _books(_sel(3))
    words = {r["clause"]: r["source_text"] for r in sel["_pool"]}

    class _Stamps(_Retry):  # every item quotes clause 4.2's words but cites clause 4.1
        def ask(self, **kw):
            self.calls.append(kw)
            return {"items": [{"topic": "t", "what_to_check": "w", "book": "B1", "clause": "4.1", "page": 1,
                               "rule_quote": words["4.2"][:60], "applies_when": "always", "paper_fields": ["f"],
                               "kind": "limit", "source": "held standard"}]}  # fmt: skip

    with budget.using(budget.LOCAL):
        got = CL.s3_checklist(_Stamps(), IDENT, sel, _BookHoldsRules(sel), "local")
    assert [i["clause"] for i in got["items"] if i["source"] == "held standard"] == [
        "4.2"
    ]
    claude = CL.s3_checklist(
        _Stamps(), IDENT, _books(_sel(3)), _BookHoldsRules(sel), "claude-sonnet-5-5"
    )
    assert [i["clause"] for i in claude["items"]] == ["4.1"]  # Claude: unchanged
    batch = [_rule("R1", "B1", "4.1", 1, "Rule one words of the invented item here."),
             _rule("R2", "B1", "4.2", 1, "Rule two words of the invented item here.")]  # fmt: skip
    nowhere = {
        "book": "B1",
        "clause": "4.1",
        "rule_quote": "words that are in no stored rule at all",
    }
    pages_only = {"book": "B9", "clause": "4.1", "rule_quote": "any words"}
    with budget.using(budget.LOCAL):
        assert (
            citing.cited(dict(nowhere), batch) is False
            and citing.cited(pages_only, batch) is True
        )
    assert citing.cited(dict(nowhere), batch) is True  # Claude: as before


def test_items_left_out_are_counted_by_cause_on_the_page_and_the_sheet():
    from app.aim_review import citing

    class _Text:
        def page(self, _b, n):
            return {3: "The invented rule words stand on page three of the book."}.get(
                n
            )

        def pages(self, _b):
            return {3: self.page(None, 3)}

    alias = {"B1": "doc_b1"}
    items = [
        {"book": "BX", "rule_quote": "q", "page": 3},
        {"book": "B1", "rule_quote": "", "page": 3},
        {
            "book": "B1",
            "rule_quote": "invented rule words stand on page three",
            "page": 9,
        },
        {
            "book": "B1",
            "rule_quote": "invented rule words stand on page three",
            "page": 3,
        },
        {"book": "B1", "rule_quote": "words of a paraphrase only", "page": 3},
        {"book": "B1", "rule_quote": "another paraphrase of the rule", "page": 3},
    ]
    why = [citing.cause(it, _Text(), alias) for it in items]
    assert why == [citing.NO_BOOK, citing.NO_QUOTE, citing.OTHER_PAGE, citing.NOT_IN_CLAUSE, citing.NOT_IN_BOOK,
                   citing.NOT_IN_BOOK]  # fmt: skip
    calls: list = []
    with faults.recording(calls), budget.using(budget.LOCAL):
        assert RT.capped(items, 0, lambda it: citing.cause(it, _Text(), alias)) == []
    rows = [c.as_dict() for c in calls]
    said = [
        x
        for x in aim_review_view.steps_not_applied(rows)
        if x["step"] == "aim_retry_capped"
    ]
    assert sorted(x["count"] for x in said) == [1, 1, 1, 1, 2] and sum(
        x["count"] for x in said
    ) == len(items)
    assert any(x["sentence"].startswith("2 checklist items were left out") and x["sentence"].endswith("(paraphrased).")
               for x in said)  # fmt: skip


def test_a_full_local_attack_answer_stays_under_the_answer_limit_even_at_one_token_per_character():
    from app.aim_review import answer_schema as A
    from app.aim_review import attack_local as AL

    shape = A.for_step("aim_attack_items")["properties"]["verdicts"]
    one = (
        sum(v.get("maxLength", 6) for v in shape["items"]["properties"].values()) + 80
    )  # keys, quotes, braces
    assert (
        shape["maxItems"] == AL.ATTACK_ITEMS
        and AL.ATTACK_ITEMS * one + 40 < budget.LOCAL.max_tokens
    )


class _RemoveAll:
    """The update 11 reviewer's probe: the local attack answers "remove" for every item it is shown."""

    def __init__(self):
        self.calls = []

    def ask(self, **kw):
        import re

        self.calls.append(kw)
        shown = kw["prompt"].split("THE ITEMS:")[-1].split("Books:")[0]
        return {"verdicts": [{"id": i, "verdict": "remove", "why": "invented", "what_to_check": ""}
                             for i in re.findall(r'"id": "(C[0-9]+)"', shown)]}  # fmt: skip


def _item(n: int, clause: str, source: str = "held standard") -> dict:
    held = source == "held standard"
    return {"id": f"C{n:03d}", "topic": f"t{n}", "what_to_check": "w", "book": "B1" if held else "", "clause": clause if held else "",
            "page": 1, "rule_quote": "q" if held else "", "applies_when": "always", "paper_fields": [], "kind": "limit",
            "source": source}  # fmt: skip


def test_the_local_attack_removes_only_items_whose_own_rule_it_was_shown_and_never_touches_knowledge_items():
    """Review of update 11, B1: a fixed group of 12 under the 9,000-character material cut showed 11 of 12 rules, knowledge items
    got no material, and "remove" (the clause does not say it) was applied to items whose clause was never shown."""
    import re

    sel = _sel(40)
    shown = [
        _item(k + 1, f"4.{k}") for k in range(30)
    ]  # each cites a stored rule (about 470 characters)
    unheld = [
        _item(31, "9.9"),
        _item(32, "9.8"),
    ]  # held items whose clause has no stored rule: never shown
    knowledge = [
        _item(33, "", "not from a held standard"),
        _item(34, "", "engineering knowledge (book not held)"),
    ]
    made = {"items": shown + unheld + knowledge}
    calls: list = []
    model = _RemoveAll()
    with faults.recording(calls), budget.using(budget.LOCAL):
        got = CL.s3_attack(model, IDENT, sel, made, None, "local")
    kept = {i["id"] for i in got["items"]}
    assert {i["id"] for i in unheld + knowledge} <= kept  # kept as written
    assert not kept & {
        i["id"] for i in shown
    }  # each removed only after its own rule was shown
    for c in (
        model.calls
    ):  # every item in a prompt has its own clause's rule in that prompt's material
        items = c["prompt"].split("THE ITEMS:")[-1].split("Books:")[0]
        material = c["prompt"].split("THE CLAUSES:")[-1]
        for clause in re.findall(r'"clause": "([0-9.]+)"', items):
            assert f'"clause": "{clause}"' in material, clause
        assert (
            "C033" not in items and "C034" not in items
        )  # knowledge items are not in the local attack
    said = _said(calls)["aim_attack_not_shown"]
    assert said["count"] == 2 and said["sentence"] == (
        "2 checklist items were not attacked (its rule could not be shown) and were kept as the first engineer wrote them."
    )


def test_a_rule_with_no_clause_number_never_resolves_a_citation():
    from app.aim_review import citing

    rows = [
        _rule("R1", "B1", "", 1, "Words of an invented rule with no clause number.")
    ]
    it = {
        "book": "B1",
        "clause": "4.1",
        "rule_quote": "Words of an invented rule with no clause number.",
    }
    with budget.using(budget.LOCAL):
        assert (
            citing.cited(it, rows) is False and it["clause"] == "4.1"
        )  # treated as not found, never re-cited to ""


def test_items_asked_again_and_still_not_found_are_counted_by_cause():
    asked = [{"topic": "a"}, {"topic": "b"}, {"topic": "c", "_cut": True}]
    calls: list = []
    with faults.recording(calls), budget.using(budget.LOCAL):
        RT.unfound(
            asked,
            [{"topic": "a"}],
            lambda it: "the quote is not in the book's words (paraphrased)",
        )
    said = _said(calls)["aim_retry_not_found"]
    assert said["count"] == 1 and said["sentence"] == (
        "1 checklist item was left out after a second ask: the quote is not in the book's words (paraphrased)."
    )  # "b" only: "a" was fixed and "c" is counted as cut, never twice


def test_an_old_local_review_says_its_one_fixed_reason_once():
    old = [{"step": "aim_retry_capped", "ok": False,
            "code": "a checklist retry item not applied: the local model makes one retry call per batch"}] * 3  # fmt: skip
    assert _said(old)["aim_retry_capped"]["sentence"] == (
        "3 checklist items were left out without a second ask (the local model makes one retry call per batch)."
    )
