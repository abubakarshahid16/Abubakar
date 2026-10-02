"""Mutations for the own-designation credit (2026-10-02, M1950-M1952): in a
one-document scope the document's own designation counts as shared for every
passage of it. File: backend/app/lexical.py. Target:
tests/test_lexical_own_designation.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_lexical_own_designation.py"
_TAG = ("own_designation",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1950", phase=1950,
             description="the designation of a scope named wholly by it is no longer credited",
             path=APP / "lexical.py",
             anchor="        if _scope_wholly_named(term, scope_ids):",
             replacement="        if False and _scope_wholly_named(term, scope_ids):",
             target=_T, keyword="cover_only or answering_page_passes", tags=_TAG),
    Mutation(id="M1951", phase=1951,
             description="the designation credit is given although another document is in scope",
             path=APP / "lexical.py",
             anchor="        if not designation or _norm_id(designation) != wanted:",
             replacement="        if not designation:",
             target=_T, keyword="foreign_file or wider_scope", tags=_TAG),
    Mutation(id="M1952", phase=1952,
             description="a standard held as two files loses the designation credit",
             path=APP / "lexical.py",
             anchor="    if len(rows) != len(scope):\n        return False\n    for row in rows:",
             replacement="    if len(rows) != 1:\n        return False\n    for row in rows:",
             target=_T, keyword="two_files", tags=_TAG),
)
