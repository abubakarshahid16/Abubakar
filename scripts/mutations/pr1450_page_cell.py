"""Order 307 extension (PR #1450): a held row whose field was read elsewhere never says "Not read from the
datasheet" (crs_page_words.read_pages / where, crs_mapping call). Ids M1450-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_P = APP / "crs_page_words.py"
_T = "tests/test_307_page_cell.py"
_TAG = ("crs", "page-cell")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1450-01",
        phase=1450,
        description="a field read elsewhere is called not read again",
        path=_P,
        anchor="    if elsewhere:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="never_called_not_read",
        tags=_TAG,
    ),
    Mutation(
        id="M1450-02",
        phase=1450,
        description="a blank value counts as a value that was read",
        path=_P,
        anchor='" AND is_blank = 0",',
        replacement='"",',
        target=_T,
        keyword="blank_value_is_not_a_value",
        tags=_TAG,
    ),
    Mutation(
        id="M1450-03",
        phase=1450,
        description="another submittal's value counts",
        path=_P,
        anchor="WHERE submittal_document_id IN ({marks}) AND",
        replacement="WHERE 1 = 1 AND",
        target=_T,
        keyword="facts_of_another_submittal",
        tags=_TAG,
    ),
    Mutation(
        id="M1450-04",
        phase=1450,
        description="a one-word name matches by containment",
        path=_P,
        anchor="elif len(words) >= 2 and any(",
        replacement="elif len(words) >= 1 and any(",
        target=_T,
        keyword="one_word_names_are_never_matched",
        tags=_TAG,
    ),
    Mutation(
        id="M1450-05",
        phase=1450,
        description="a probable match is said as an exact one",
        path=_P,
        anchor='        what = "A value" if exact else "A value that may be this field"',
        replacement='        what = "A value"',
        target=_T,
        keyword="probable_match_is_said_as_one",
        tags=_TAG,
    ),
    Mutation(
        id="M1450-06",
        phase=1450,
        description="a value a later pass replaced counts as read (and an earlier read is not told apart)",
        path=_P,
        anchor="AND superseded_at IS {'NOT ' if replaced else ''}NULL\"",
        replacement="\"",
        target=_T,
        keyword="later_reading_replaced",
        tags=_TAG,
    ),
    Mutation(
        id="M1450-07",
        phase=1450,
        description="a value with no page recorded prints 'page None'",
        path=_P,
        anchor="    known = [p for p in pages if p is not None]",
        replacement="    known = list(pages)",
        target=_T,
        keyword="never_prints_page_none",
        tags=_TAG,
    ),
)
