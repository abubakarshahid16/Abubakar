"""Order 141 (#1177 extension, builder E): a division of a standard limited by
its own scope sentence to one construction applies only to equipment of that
construction; unsure is held for the engineer. The hook is in `comparison.py`,
in the danger zone (rule 6). Placeholder ids M141E-NN until the PR number is
known (rule 12: renamed to M<PR>-NN then)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_141_division_scope.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M141E-01",
        phase=141,
        description="a division limited to another construction is checked again",
        path=_C,
        anchor='    requirements = divided["kept"]\n',
        replacement="",
        target=_T,
        keyword="review_does_not_apply_a_division",
        tags=("scope",),
    ),
    Mutation(
        id="M141E-02",
        phase=141,
        description="a requirement taken out by the division scope has no ledger decision (silent loss)",
        path=_C,
        anchor='    extra_not_applied.extend(divided["items"])\n',
        replacement="",
        target=_T,
        keyword="review_does_not_apply_a_division",
        tags=("scope", "honesty", "critical"),
    ),
    Mutation(
        id="M141E-03",
        phase=141,
        description="an unsure division is not held for the engineer (silent loss)",
        path=_C,
        anchor='    held_items.extend(divided["held"])\n',
        replacement="",
        target=_T,
        keyword="holds_an_unsure_division",
        tags=("scope", "honesty", "critical"),
    ),
)
