"""Mutations for `backend/app/kind_standards.py` (PR 1687): which standards a document kind may leave out of a review."""

from __future__ import annotations

from ._base import APP, TESTS, Mutation

_T = str(TESTS / "test_standard_roles_by_kind.py")
_TAG = ("kind_standards",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1687-01",
        phase=1687,
        description="a standard a person or the project chose is left out of a procedure's review",
        path=APP / "kind_standards.py",
        anchor='        if row.get("method") in spared or not applicability.is_included(row):\n',
        replacement="        if not applicability.is_included(row):\n",
        target=_T,
        keyword="never_left_out",
        tags=_TAG,
    ),
    Mutation(
        id="M1687-02",
        phase=1687,
        description="a row that was never included, or is held or excluded, is counted and its reason rewritten",
        path=APP / "kind_standards.py",
        anchor='        if row.get("method") in spared or not applicability.is_included(row):\n',
        replacement='        if row.get("method") in spared:\n',
        target=_T,
        keyword="only_rows_that_were_included",
        tags=_TAG,
    ),
    Mutation(
        id="M1687-03",
        phase=1687,
        description="an equipment design standard stays in a procedure's review",
        path=APP / "kind_standards.py",
        anchor="        if role is not None and role not in allowed_roles:\n",
        replacement="        if False:\n",
        target=_T,
        keyword="leaves_out_equipment_design",
        tags=_TAG,
    ),
)
