"""#882 (PR 1251): a Required column the CODE readers recorded (the geometry
reader's `value_column`, the table reader's "<label> - <header>") is never the
contractor's submitted value, like the AI reader's `model:required` (#1246)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_882_required_never_submitted.py"
_R = APP / "required_values.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1251-01",
        phase=1251,
        description="a Required column recorded by the code readers is no longer recognised as the purchaser's",
        path=_R,
        anchor='    return datasheet_ai.rule_kind(fact) == "required"\n',
        replacement="    return False\n",
        target=_T,
        keyword="code_read",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1251-02",
        phase=1251,
        description="a Required column is recognised only when it is the cell's last words, not by the column header",
        path=_R,
        anchor='    return datasheet_ai.rule_kind(fact) == "required"\n',
        replacement='    return datasheet_ai.rule_kind(fact) == "offered"\n',
        target=_T,
        keyword="code_read",
        tags=("honesty",),
    ),
)
