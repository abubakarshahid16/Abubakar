"""PR #1319: the contractor's Standard Reference and Page/Section columns
(order 228). backend/tests/test_228_crs_contractor_columns.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_228_crs_contractor_columns.py"
_M = APP / "crs_columns.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1319-01",
        phase=1319,
        description="a checklist row prints its check id again instead of the clause",
        path=_M,
        anchor="    if cited:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="not_the_check_id",
        tags=("pr1319", "crs_columns"),
    ),
    Mutation(
        id="M1319-02",
        phase=1319,
        description="the located page is dropped from a checklist reference",
        path=_M,
        anchor='return cited + (f" (p.{page})" if page else "")',
        replacement="return cited",
        target=_T,
        keyword="located_page",
        tags=("pr1319", "crs_columns"),
    ),
    Mutation(
        id="M1319-03",
        phase=1319,
        description="the engine's note is read as part of the standard name again",
        path=_M,
        anchor='.split(" Written by ", 1)[0]',
        replacement="",
        target=_T,
        keyword="names_the_standard_not_the_engine",
        tags=("pr1319", "crs_columns"),
    ),
    Mutation(
        id="M1319-04",
        phase=1319,
        description="a field read on a page is called not found",
        path=_M,
        anchor='return not pages and not any(g.get("fact_id") for g in group)',
        replacement="return not pages",
        target=_T,
        keyword="read_but_has_no_page",
        tags=("pr1319", "crs_columns"),
    ),
)
