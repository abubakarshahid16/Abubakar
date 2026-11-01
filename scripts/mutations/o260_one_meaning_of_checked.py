"""Order 260.1 (PR 1392): one meaning of "checked". M1392-01 onward."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_260_one_meaning_of_checked.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1392-01",
        phase=1392,
        description="a requirement that only asks for another document is checked again",
        path=APP / "scope_ledger.py",
        anchor='    "needs_other_document": (\n        APPLIES_NOT_CHECKED,\n',
        replacement='    "needs_other_document": (\n        CHECKED,\n',
        target=_T,
        keyword="not_checked or another_document or coverage_agrees",
        tags=_TAGS,
    ),
    Mutation(
        id="M1392-02",
        phase=1392,
        description="a requirement with no value on the sheet is checked again",
        path=APP / "scope_ledger.py",
        anchor='    "missing_information": (APPLIES_NOT_CHECKED, "no value for it on this datasheet"),\n',
        replacement='    "missing_information": (CHECKED, "no value for it on this datasheet"),\n',
        target=_T,
        keyword="not_checked or coverage_agrees",
        tags=_TAGS,
    ),
    Mutation(
        id="M1392-03",
        phase=1392,
        description="a finding status nobody defined counts as a comparison",
        path=APP / "scope_ledger.py",
        anchor='    return REASONS[STATUS_REASON.get(status or "", "needs_engineer")]\n',
        replacement='    return REASONS[STATUS_REASON.get(status or "", "compared")]\n',
        target=_T,
        keyword="not_checked or no_finding",
        tags=_TAGS,
    ),
    Mutation(
        id="M1392-04",
        phase=1392,
        description="the split ignores the findings' statuses and counts every requirement checked",
        path=APP / "requirement_split.py",
        anchor='        group, words = scope_ledger.group_of(status_of.get(r.get("id")))\n',
        replacement="        group, words = CHECKED, ''\n",
        target=_T,
        keyword="split_counts or cannot_be_approved",
        tags=_TAGS,
    ),
    Mutation(
        id="M1392-05",
        phase=1392,
        description="the clause coverage counts a missing-information requirement as checked",
        path=APP / "clause_coverage.py",
        anchor='    "compared": CHECKED,\n    "needs_engineer"',
        replacement='    "compared": CHECKED, "missing_information": CHECKED,\n    "needs_engineer"',
        target=_T,
        keyword="coverage_agrees",
        tags=_TAGS,
    ),
)
