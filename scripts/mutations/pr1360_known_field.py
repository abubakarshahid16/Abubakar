"""Backlog 11 (PR 1360): a missing library requirement keeps its contractor row only when the
field it names is one the system knows."""

from __future__ import annotations

from ._base import APP, Mutation

_N = APP / "crs_no_field.py"
_T = "tests/test_245c_known_field_only.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1360-01",
        phase=1360,
        description="any clean noun phrase counts as a field again",
        path=_N,
        anchor="    return bool(label) and is_known_field(label)\n",
        replacement="    return bool(label)\n",
        target=_T,
        keyword="unknown_phrase_does_not_count",
        tags=("honesty",),
    ),
    Mutation(
        id="M1360-02",
        phase=1360,
        description="a known spelling no longer counts unless the role data reads it",
        path=_N,
        anchor="    if name in _known_spellings():\n",
        replacement="    if False:\n",
        target=_T,
        keyword="spelling_of_the_synonym_data",
        tags=("honesty",),
    ),
)
