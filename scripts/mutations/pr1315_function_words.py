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
        description="a phrase ending in a function word is read as a service again ('into service')",
        path=_P,
        anchor="    return bool(words) and words[-1] in _FUNCTION_WORDS\n",
        replacement="    return False\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1315-02",
        phase=1315,
        description="every phrase before 'service' is dropped: a real service ('sour') is no longer held",
        path=_P,
        anchor="    return bool(words) and words[-1] in _FUNCTION_WORDS\n",
        replacement="    return True\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
)
