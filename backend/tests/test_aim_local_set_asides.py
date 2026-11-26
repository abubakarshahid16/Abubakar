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
from tests.test_aim_local_fixes import _AttackCut, _Book, _Retry, _Runaway, _sel

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


def test_a_cut_attack_batch_is_counted_once():
    sel = _sel(120)
    made = {"items": [{"id": f"C{k:03d}", "topic": "t", "what_to_check": "w", "book": "B1", "clause": "4.1", "page": 1,
                       "rule_quote": "q", "applies_when": "always", "paper_fields": [], "kind": "limit",
                       "source": "held standard"} for k in range(1, 9)]}  # fmt: skip
    calls: list = []
    with faults.recording(calls), budget.using(budget.LOCAL):
        CL.s3_attack(_AttackCut(), IDENT, sel, made, None, "local")
    said = _said(calls)["aim_attack_cut"]
    assert said["count"] == 1
    assert said["sentence"] == (
        "1 attack batch was not used (answer cut): the checklist was not attacked on those rules."
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
    assert capped["sentence"] == (
        f"{14 - CL.RETRY_LOCAL} checklist items were left out: their rule quote was not found on the book page and were not "
        "asked again (the local model makes one retry call per batch)."
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
        aim_review_gate.LOCAL_MEASURED_WORDS in line
        and aim_review_gate.LOCAL_TEST_NOTE in line
        and aim_review_gate.NOT_YET_SCORED
        not in line  # a measured model never says "not yet scored"
    )
    assert line.index(aim_review_gate.LOCAL_MEASURED_WORDS) < line.index(
        aim_review_gate.LOCAL_TEST_NOTE
    )
    other = {"local": True, "models": ["invented-local:1b"], "by_step": {}}
    line = aim_review_local_view.measured({"kind": "datasheet"}, other)["sentence"]
    assert aim_review_gate.LOCAL_TEST_NOTE not in line
    assert "Local model (invented-local:1b): not yet scored." in line
    assert aim_review_gate.LOCAL_NOT_SCORED in line
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
