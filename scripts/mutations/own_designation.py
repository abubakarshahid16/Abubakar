"""Mutations for the own-designation credit (2026-10-02, M1950-M1951): in a
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
             description="the document's own designation is no longer credited in a one-document scope",
             path=APP / "lexical.py",
             anchor="        if one_document_scope is not None and _names_an_indexed_document(",
             replacement="        if False and one_document_scope is not None and _names_an_indexed_document(",
             target=_T, keyword="answering_page_passes", tags=_TAG),
    Mutation(id="M1951", phase=1951,
             description="the designation credit is given in any scope, not only a one-document scope",
             path=APP / "lexical.py",
             anchor="        else (allowed_document_ids if len(allowed_document_ids) == 1 else None))",
             replacement="        else allowed_document_ids)",
             target=_T, keyword="does_not_reach_a_wider_scope", tags=_TAG),
)
