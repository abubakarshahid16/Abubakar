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
    said = _said(calls)["aim_retry_dropped"]
    # the 14 invented items all quote the rule wrongly and every retry answer is cut: none is kept, each is counted
    assert said["count"] == 14 and not [
        i for i in got["items"] if i["source"] == "held standard"
    ]
    assert said["sentence"].startswith(
        "14 checklist items were left out: their rule quote was not found"
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
    local = {"local": True, "models": ["invented-local:1b"], "by_step": {}}
    line = aim_review_local_view.measured({"kind": "datasheet"}, local)["sentence"]
    assert (
        aim_review_gate.LOCAL_NOT_SCORED in line
        and aim_review_gate.LOCAL_TEST_NOTE in line
    )
    assert line.index(aim_review_gate.LOCAL_NOT_SCORED) < line.index(
        aim_review_gate.LOCAL_TEST_NOTE
    )
    claude = aim_review_local_view.measured({"kind": "datasheet"}, {"local": False})
    assert claude is None or aim_review_gate.LOCAL_TEST_NOTE not in (
        claude.get("sentence") or ""
    )
