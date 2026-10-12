"""Mutations for the own-designation credit (2026-10-02, M1950-M1955): in a
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
             anchor="        if have != wanted and not (fragment_ok and wanted in have):\n            return False",
             replacement="        if have != wanted and not (fragment_ok and wanted in have):\n            continue",
             target=_T, keyword="foreign_file or wider_scope", tags=_TAG),
    Mutation(id="M1952", phase=1952,
             description="a standard held as two files loses the designation credit",
             path=APP / "lexical.py",
             anchor="    if len(rows) != len(scope):\n        return False\n    # A long designation",
             replacement="    if len(rows) != 1:\n        return False\n    # A long designation",
             target=_T, keyword="two_files", tags=_TAG),
)

# --- stranded citation (M1953-M1954) and designation fragment (M1955) --------
_V = "tests/test_verify_claims_stranded_citation.py"
MUTATIONS = MUTATIONS + (
    Mutation(id="M1953", phase=1953,
             description="a citation after the full stop is no longer joined to its sentence",
             path=APP / "answer.py",
             anchor="        for segment in _join_stranded_citations(_SEGMENT.split(line)):",
             replacement="        for segment in _SEGMENT.split(line):",
             target=_V, keyword="after_the_full_stop_is_kept", tags=("stranded_citation",)),
    Mutation(id="M1954", phase=1954,
             description="any segment after the first is joined to the one before it",
             path=APP / "answer.py",
             anchor="        if joined and _ONLY_CITATIONS.match(segment):",
             replacement="        if joined:",
             target=_V, keyword="not_absorbed or wrong_figure or unquoted", tags=("stranded_citation",)),
    Mutation(id="M1955", phase=1955,
             description="a fragment of a designation no longer counts as naming the document",
             path=APP / "lexical.py",
             anchor="        if have != wanted and not (fragment_ok and wanted in have):",
             replacement="        if have != wanted:",
             target=_T, keyword="long_designation", tags=_TAG),
)
