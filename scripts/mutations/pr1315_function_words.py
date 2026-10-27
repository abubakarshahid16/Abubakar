"""PR 1315 (order 228.5): a function word before "service" or "application" names no
condition, so "put into service" is not a service the datasheet must state."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_228_function_word_conditions.py"
_P = APP / "clause_support.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1315-01",
        phase=1315,
        description="words before a linking word are read as a service again ('maintained during', 'into')",
        path=_P,
        anchor='            return " ".join(words[i + 1 :])\n',
        replacement="            return phrase\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1315-02",
        phase=1315,
        description="the first word of the phrase counts as a break: 'used before lethal service' loses 'lethal'",
        path=_P,
        anchor="        if words[i].casefold() in _BREAK:\n",
        replacement="        if True:\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
)
