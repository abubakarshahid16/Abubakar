"""PR #1814 (lead's order of 15 Nov 2026, R48n): a checklist result that rests on a value in conflict, needing an engineer, or carrying two readings is a question,
never a Pass or Fail, in the classic path and the calculator alike (`untrusted_value`, the second exit of `datasheet_checks.evaluate`: danger zone). Each entry deletes one
control; `tests/test_1814_untrusted_value.py` must notice. Ids M1814-01 onwards (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1814_untrusted_value.py"
_U = APP / "untrusted_value.py"
_TAGS = ("honesty", "critical", "checklist")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1814-01",
        phase=1814,
        description="the evaluator's exit does not call the untrusted-value hold: a result on a value in conflict stays a Pass or Fail, in the classic path and the calculator",
        path=APP / "deferred_value.py",
        anchor="    results = untrusted_value.hold_results(results, facts, rules, wanted)  # a value nobody can trust yet is no verdict\n",
        replacement="    pass\n",
        target=_T,
        keyword="reviewers_case or classic_path",
        tags=_TAGS,
    ),
    Mutation(
        id="M1814-02",
        phase=1814,
        description="a value carrying two readings, or in a state of conflict or needing an engineer, is trusted",
        path=_U,
        anchor='    return fact.get("reading_conflict") or comparison.low_trust_reason(dict(fact))\n',
        replacement="    return None\n",
        target=_T,
        keyword="each_kind_of_untrusted_value",
        tags=_TAGS,
    ),
    Mutation(
        id="M1814-03",
        phase=1814,
        description="a result is held only for the fact it is about, not for the fact it is checked against",
        path=_U,
        anchor='        roles = {r.get("role"), right_of.get(r.get("rule_id"))} | (',
        replacement='        roles = {r.get("role"), None} | (',
        target=_T,
        keyword="each_kind_of_untrusted_value or checked_against",
        tags=_TAGS,
    ),
    Mutation(
        id="M1814-04",
        phase=1814,
        description="an untrusted reading is ignored unless it is the fact the result is about (no role lookup)",
        path=_U,
        anchor='        if role:\n            bad[(f.get("equipment_tag"), role)]',
        replacement='        if False:\n            bad[(f.get("equipment_tag"), role)]',
        target=_T,
        keyword="each_kind_of_untrusted_value",
        tags=_TAGS,
    ),
    Mutation(
        id="M1814-05",
        phase=1814,
        description="a presence check that passes on an untrusted value stays a Pass (only a breach is held)",
        path=_U,
        anchor='        if r.get("status") not in _DECIDED:\n',
        replacement='        if r.get("status") != "NON_COMPLIANT":\n',
        target=_T,
        keyword="presence_check",
        tags=_TAGS,
    ),
)
