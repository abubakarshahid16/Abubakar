"""Order 161 item A (PR #1210): a form-reader value whose quote the code found
on the page is trusted. `comparison.py` is in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_ai_reader_default.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1210-01",
        phase=1210,
        description="only the AI reader's own name counts as a proved quote, so every proved form reading is held again",
        path=APP / "comparison.py",
        anchor="""_PROVED_QUOTE_READERS = frozenset({"datasheet_ai", "form_reader"})""",
        replacement="""_PROVED_QUOTE_READERS = frozenset({"datasheet_ai"})""",
        target=_T,
        keyword="form_reader_value_whose_quote",
        tags=("honesty",),
    ),
    Mutation(
        id="M1210-02",
        phase=1210,
        description="any named reader's value counts as proved, so a reader no check stands behind is trusted",
        path=APP / "comparison.py",
        anchor="""box.get("reader") in _PROVED_QUOTE_READERS and""",
        replacement="""box.get("reader") and""",
        target=_T,
        keyword="form_reader_value_whose_quote",
        tags=("honesty",),
    ),
)
