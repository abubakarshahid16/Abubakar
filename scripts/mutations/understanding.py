"""Mutations of `backend/app/understanding.py` and its wiring - B6C."""

from __future__ import annotations

from ._base import APP, Mutation

_U = APP / "understanding.py"
_T = "tests/test_b6c_understanding.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M804", phase=69, description="B6C: a document named in the question no longer scopes the search",
        path=_U,
        anchor="        if des and f\" {_norm(des)} \" in padded:\n",
        replacement="        if False:\n",
        target=_T, keyword="designation_scopes or naming_the_standard",
    ),
    Mutation(
        id="M805", phase=69, description="B6C: a named document outside the grants can scope the search",
        path=_U,
        anchor="    permitted = {d: f for d, f in documents.items() if d in allowed_document_ids}\n",
        replacement="    permitted = dict(documents)\n",
        target=_T, keyword="never_widens", tags=("access",),
    ),
    Mutation(
        id="M806", phase=69, description="B6C: a name matching several documents silently picks the first",
        path=_U,
        anchor="        if len(ids) == 1:\n",
        replacement="        if len(ids) >= 1:\n",
        target=_T, keyword="several_documents",
    ),
    # M807 RETIRED in B9: `understand` now drops a previous answer's context
    # whose document is not readable before this line runs (mutated by M843),
    # so the grant check here can no longer be observed on its own.
    Mutation(
        id="M808", phase=69, description="B6C: 'the next clause' steps backwards",
        path=_U,
        anchor='        clause, clause_reason = _step(context.clause, +1), "the clause after the previous answer\'s"\n',
        replacement='        clause, clause_reason = _step(context.clause, -1), "the clause after the previous answer\'s"\n',
        target=_T, keyword="clause_references",
    ),
    Mutation(
        id="M809", phase=69, description="B6C: identical text in several documents is no longer reported",
        path=_U,
        anchor="    return docs if len(docs) > 1 else []\n",
        replacement="    return []\n",
        target=_T, keyword="boilerplate",
    ),
    Mutation(
        id="M810", phase=69, description="B6C: the chat ignores the understood document scope",
        path=APP / "chat.py",
        anchor='        if understood.get("document_id") in allowed_document_ids:\n            document_id = understood["document_id"]\n',
        replacement='        if False:\n            document_id = understood["document_id"]\n',
        target=_T, keyword="naming_the_standard or this_standard_stays",
    ),
    Mutation(
        id="M811", phase=69, description="B6C: a dropped near-duplicate no longer says which chunk it repeats",
        path=APP / "search.py",
        anchor="                duplicate_of = existing_id\n",
        replacement="                duplicate_of = c.chunk_id\n",
        target=_T, keyword="boilerplate",
    ),
)
