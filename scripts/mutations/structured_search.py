"""Mutations of `backend/app/structured_search.py`."""

from __future__ import annotations

from ._base import APP, _B42_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B42_STRUCTURED_SCOPE ----------------------------------------
    #: B42: the one branch that never applied the scope mask, and the permissive
    #: default that would have let the next caller read the corpus by forgetting.
    Mutation(
        id="M338", phase=40,
        description="PUT B42 BACK: the stakeholder branch ignores the scope "
                    "mask, so a caller with no grants reads every email",
        path=APP / "structured_search.py",
        anchor='        where, scope_args = _scope_sql("d.document_id", allowed_document_ids,\n'
               '                                       include_unowned)',
        replacement='        where, scope_args = "", []',
        target=_B42_TEST,
        keyword="scoped_like_every_other_kind or empty_scope_sees_no_stakeholders",
        tags=("critical", "privacy"),
    ),
    Mutation(
        id="M339", phase=40,
        description="an empty scope means everything again: the mask that "
                    "matches nothing becomes no mask at all",
        path=APP / "structured_search.py",
        anchor='    if not parts:\n        return " AND 1=0", []',
        replacement='    if not parts:\n        return "", []',
        target=_B42_TEST, keyword="empty_scope_sees_no_stakeholders",
        tags=("critical", "privacy"),
    ),
    Mutation(
        id="M340", phase=40,
        description="restore the permissive default, so a caller that forgets "
                    "the mask silently reads the whole corpus",
        path=APP / "structured_search.py",
        anchor="def search(query: str, *, allowed_document_ids: frozenset[str],\n"
               "           include_unowned: bool, kind: str | None = None) -> list[dict]:",
        replacement="def search(query: str, *, allowed_document_ids: frozenset[str] = frozenset(),\n"
                    "           include_unowned: bool = True, kind: str | None = None) -> list[dict]:",
        target=_B42_TEST, keyword="scope_cannot_be_omitted",
        tags=("critical",),
    ),
)
