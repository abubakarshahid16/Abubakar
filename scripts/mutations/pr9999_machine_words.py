"""Order 152.2: no machine wording in the contractor's copy
(`crs_machine_words`, wired into the `crs_issue` gate).
Danger zone (rule 6): crs_export / crs_issue. PR number not yet known: 9999 is
a placeholder to be renamed when the PR is opened."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_152_crs_machine_words.py"
_W = APP / "crs_machine_words.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M9999-01",
        phase=9999,
        description="the issue gate no longer blocks on machine wording",
        path=APP / "crs_issue.py",
        anchor="    if machine:\n        blockers.append(machine)\n",
        replacement="",
        target=_T,
        keyword="gate_blocks",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M9999-02",
        phase=9999,
        description="an engineer-edited row is scanned (an engineer's words are vetoed)",
        path=_W,
        anchor='        if row.get("edited") is True:\n            continue\n',
        replacement="",
        target=_T,
        keyword="engineer_edited",
        tags=("crs",),
    ),
    Mutation(
        id="M9999-03",
        phase=9999,
        description="rows the issue copy would not carry are scanned (false blocks)",
        path=_W,
        anchor="        if not _carried_by_issue_copy(row):\n            continue\n",
        replacement="",
        target=_T,
        keyword="does_not_carry",
        tags=("crs",),
    ),
    Mutation(
        id="M9999-04",
        phase=9999,
        description="snake_case identifiers are no longer machine words",
        path=_W,
        anchor='    re.compile(_EDGE_L + r"[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)+" + _EDGE_R),\n',
        replacement="",
        target=_T,
        keyword="machine_words_are_found",
        tags=("crs",),
    ),
    Mutation(
        id="M9999-05",
        phase=9999,
        description="model names are no longer read from the settings",
        path=_W,
        anchor='        if key.endswith("_model") and isinstance(value, str):',
        replacement='        if key.endswith("_nomodel") and isinstance(value, str):',
        target=_T,
        keyword="from_the_settings",
        tags=("crs",),
    ),
    Mutation(
        id="M9999-06",
        phase=9999,
        description="the blocker does not say what to do",
        path=_W,
        anchor="edit the wording of ",
        replacement="look at ",
        target=_T,
        keyword="gate_blocks",
        tags=("crs",),
    ),
)
