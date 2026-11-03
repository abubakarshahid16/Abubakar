"""Mutations of figure_compare (Part of #805, step 3): the one place a document figure is judged against a clause figure."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_figure_compare.py"
_P = APP / "figure_compare.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1689-01",
        phase=1689,
        description="figure_compare: a floor is always met",
        path=_P,
        anchor='        ">=": a >= b - tolerance,\n',
        replacement='        ">=": True,\n',
        target=_T,
        keyword="direction_and_the_units",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1689-02",
        phase=1689,
        description="figure_compare: a ceiling is always met",
        path=_P,
        anchor='        "<=": a <= b + tolerance,\n',
        replacement='        "<=": True,\n',
        target=_T,
        keyword="direction_and_the_units",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1689-03",
        phase=1689,
        description="figure_compare: a placeholder or a negation in the document quote is compared",
        path=_P,
        anchor="    if blank_markers.names_a_marker(text) or _NEGATED.search(text):\n",
        replacement="    if False:\n",
        target=_T,
        keyword="cannot_be_compared",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1689-04",
        phase=1689,
        description="figure_compare: a range or a list in the document quote is compared",
        path=_P,
        anchor="    if len({numparse.canonical(n) for n in numparse.find_numbers(text)}) != 1:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="cannot_be_compared",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1689-05",
        phase=1689,
        description="figure_compare: a gauge value is compared with an absolute limit",
        path=_P,
        anchor='    if (\n        asked.dimension == "pressure"\n        and (value.reference or asked.reference)\n        and value.reference != asked.reference\n    ):\n',
        replacement="    if False:\n",
        target=_T,
        keyword="cannot_be_compared",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1689-06",
        phase=1689,
        description="figure_compare: a value equal to a strict limit is decided",
        path=_P,
        anchor="    if (\n        abs(a - b) <= tolerance\n        and _STRICT.search(clause_quote)\n        and not _NOT_STRICT.search(clause_quote)\n    ):\n",
        replacement="    if False:\n",
        target=_T,
        keyword="cannot_be_compared",
        tags=("honesty",),
    ),
    Mutation(
        id="M1689-07",
        phase=1689,
        description="figure_compare: a clause with no readable comparator is compared anyway",
        path=_P,
        anchor='    if direction not in (">=", "<=", "="):\n',
        replacement="    if False:\n",
        target=_T,
        keyword="cannot_be_compared",
        tags=("honesty",),
    ),
)
