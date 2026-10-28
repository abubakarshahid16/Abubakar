"""PR #1434 (order 298.3, CRS-008): a checklist field the label search could not find is worded as what was
searched, not as an absence on the sheet."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_checklist_text_search.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1434-01",
        phase=1434,
        description="the label search that finds nothing says the value was not found on the sheet again",
        path=APP / "datasheet_checks.py",
        anchor='                    f"{_pretty(field)} was not read as a value, and no label for it was found in the text of pages "\n',
        replacement='                    f"{_pretty(field)} was not found in the fields read or in the text of pages "\n',
        target=_T,
        keyword="says_what_it_searched",
        tags=("checklist", "honesty", "critical"),
    ),
    Mutation(
        id="M1434-02",
        phase=1434,
        description="the 'may state it in other words' caveat is dropped from the sentence",
        path=APP / "datasheet_checks.py",
        anchor='(searched by its name; the sheet may state it in other words); the contractor is to provide it.")',
        replacement='(searched by its name); the contractor is to provide it.")',
        target=_T,
        keyword="says_what_it_searched",
        tags=("checklist", "honesty"),
    ),
)
