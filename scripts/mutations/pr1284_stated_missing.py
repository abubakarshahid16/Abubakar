"""PR #1284 (order 210 FIX 1): a clause that only asks to be stated on the
datasheet, with no field on the sheet, is missing information.
backend/tests/test_210_stated_clause_missing.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_210_stated_clause_missing.py"
_PATH = APP / "comparison.py"
_COND = (
    "                and not field_links.asks_only_to_be_stated(\n"
    '                    requirement.get("source_text") or requirement.get("requirement_text")):\n'
)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1284-01",
        phase=1284,
        description="the exception is dropped: a clause asking only to be stated is again 'another document's question'",
        path=_PATH,
        anchor=_COND,
        replacement=":\n",
        target=_T,
        keyword="stated_clause_with_no_field_is_missing_information",
        tags=("pr1284", "comparison"),
    ),
    Mutation(
        id="M1284-02",
        phase=1284,
        description="every unmatched statement becomes an omission (the exception is inverted)",
        path=_PATH,
        anchor=_COND,
        replacement=(
            "                and field_links.asks_only_to_be_stated(\n"
            '                    requirement.get("source_text") or requirement.get("requirement_text")):\n'
        ),
        target=_T,
        keyword="stated_clause_with_no_field_is_missing_information or another_documents_question",
        tags=("pr1284", "comparison"),
    ),
)
