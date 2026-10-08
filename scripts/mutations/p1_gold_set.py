"""Mutations of `eval/p1/harness.py` - the P1 gold set, version 2 (2026-10-08).

Version 2 added multi-document questions. Each one passes only when EVERY
expected document is cited on an expected page, and each of its labels is
checked against the invented corpus like a single-document label. Each entry
deletes one of those rules; `tests/test_p1_question_set.py` must notice.
"""

from __future__ import annotations

from ._base import REPO, Mutation

_H = REPO / "eval" / "p1" / "harness.py"
_T = "tests/test_p1_question_set.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M2201", phase=2010,
        description="a multi-document answer that cites only one side passes",
        path=_H,
        anchor="        if not cited:\n            return False",
        replacement="        pass",
        target=_T, keyword="cites_only_one_side",
    ),
    Mutation(
        id="M2202", phase=2010,
        description="multi-document labels are never checked against the corpus",
        path=_H,
        anchor="            problems.extend(_check_sources(q))",
        replacement="            pass",
        target=_T, keyword="label_that_is_not_in_the_corpus",
    ),
    Mutation(
        id="M2203", phase=2010,
        description="a multi-document question is scored as a single-document one",
        path=_H,
        anchor='    if q.get("expected_sources"):\n        return row.get("sources_ok") is True',
        replacement="    pass",
        target=_T, keyword="cites_only_one_side",
    ),
)
