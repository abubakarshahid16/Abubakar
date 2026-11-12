"""PR #1804 (ONE-REVIEWER.md, owner decision 12 Nov 2026): the calculator of the one reviewer and the exit's second ask for code lines.
Each entry deletes one control that keeps a "Proven by code" Pass or Fail from existing without a compared value and both quotes found by code;
`tests/test_b1_calculator.py` must notice. Ids M1804-01 onwards, named after the PR (CLAUDE.md rule 12). The calculator calls `comparison.compare`
and `datasheet_checks.evaluate` (danger zone, rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_b1_calculator.py"
_K = APP / "agent_review_calculator.py"
_TAGS = ("honesty", "critical", "calculator")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1804-01",
        phase=1804,
        description="the clause quote is not checked: a Pass or Fail stands on a quote nobody found in the clause",
        path=_K,
        anchor='    if not base["quotes_checked"]["clause"]:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="anything_short_of_a_compared_value or brute_force",
        tags=_TAGS,
    ),
    Mutation(
        id="M1804-02",
        phase=1804,
        description="the paper quote is not checked: a Pass or Fail stands on a value not found on its page",
        path=_K,
        anchor='    if not base["quotes_checked"]["paper"]:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="anything_short_of_a_compared_value or fact_whose_quote or brute_force",
        tags=_TAGS,
    ),
    Mutation(
        id="M1804-03",
        phase=1804,
        description="a hold on the comparison no longer makes a Query",
        path=_K,
        anchor="    if got.get(hold_reason.KEY):\n",
        replacement="    if False:\n",
        target=_T,
        keyword="a_hold_on_the_comparison_is_a_query or brute_force",
        tags=_TAGS,
    ),
    Mutation(
        id="M1804-04",
        phase=1804,
        description="a comparison that is not decided (no limit or no observed value) still gives a Pass or Fail",
        path=_K,
        anchor='    if status not in (COMPLIANT, NON_COMPLIANT) or not (\n        got.get("limit") and got.get("observed")\n    ):\n',
        replacement="    if status not in (COMPLIANT, NON_COMPLIANT):\n",
        target=_T,
        keyword="brute_force",
        tags=_TAGS,
    ),
    Mutation(
        id="M1804-05",
        phase=1804,
        description="the exit no longer asks again for a code line: a forged Pass stays proven",
        path=APP / "agent_review_wording.py",
        anchor="    out = hold_unproven_code(hold_silence(line, paper_kind))\n",
        replacement="    out = hold_silence(line, paper_kind)\n",
        target=_T,
        keyword="exit_demotes_a_code_line",
        tags=_TAGS,
    ),
    Mutation(
        id="M1804-06",
        phase=1804,
        description="an approved-checklist marker is trusted without the id being in the approved file",
        path=APP / "agent_review_approved_code.py",
        anchor='        and item.get("rule_id") in approved_check_ids()\n',
        replacement="",
        target=_T,
        keyword="forged_approved_marker",
        tags=_TAGS,
    ),
    Mutation(
        id="M1804-07",
        phase=1804,
        description="a checklist value counts as found anywhere on the page, not next to its label",
        path=_K,
        anchor="        if val in t[start + len(lab) : start + len(lab) + NEAR_CHARS]:\n",
        replacement="        if val in t:\n",
        target=_T,
        keyword="not_on_its_page_next_to_its_label",
        tags=_TAGS,
    ),
)
