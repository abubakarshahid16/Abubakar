"""PR 1312 (order 228.4): a CRS row with no datasheet page says "Not found on pages 1-N" with
at most three tags; a value that was read is never called "not found"."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_228_page_column.py"
_P = APP / "crs_page_words.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1312-01",
        phase=1312,
        description="a row with no page prints the field and every tag again: nothing is ever 'not found'",
        path=_P,
        anchor="    if pages or read or not (field or tags):\n",
        replacement="    if True:\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1312-02",
        phase=1312,
        description="a value that was read but has no page recorded is called 'not found'",
        path=_P,
        anchor="    if pages or read or not (field or tags):\n",
        replacement="    if pages or not (field or tags):\n",
        target=_T,
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1312-03",
        phase=1312,
        description="the tag list of a not-found row is not cut to three and a count",
        path=_P,
        anchor="    shown = tags[:MAX_TAGS]\n",
        replacement="    shown = tags\n",
        target=_T,
        tags=("honesty",),
    ),
    Mutation(
        id="M1312-04",
        phase=1312,
        description="a not-found row says 'pages 1-0' when the page count is unknown",
        path=_P,
        anchor='        else "Not found on the datasheet"\n',
        replacement='        else "Not found on pages 1-0"\n',
        target=_T,
        tags=("honesty",),
    ),
)
