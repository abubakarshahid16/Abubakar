"""#1649: the CRS as drawn prints no reading part of a Word file as a page, in a comment,
a cell, a note or a sentence beside the rows. Numbered after the issue until the PR opens
(the coordinator holds it): the number moves to the PR's before anything merges."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1649_one_checked_ready.py"
_P = APP / "crs_mapping.py"


def _m(number: int, description: str, anchor: str, replacement: str) -> Mutation:
    return Mutation(
        id=f"M1649-{number:02d}",
        phase=1649,
        description=description,
        path=_P,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        tags=("honesty", "critical"),
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the rows keep a reading part as a page in comments and cells",
        "    return word_pages.crs_rows_for_reader(rows, document_id), shown\n",
        "    return rows, shown\n",
    ),
    _m(
        2,
        "a review note keeps a reading part as a page",
        '        "review_notes": word_pages.notes_for_reader(\n'
        '            meta.get("review_notes") or [], document_id\n'
        "        ),\n",
        '        "review_notes": meta.get("review_notes") or [],\n',
    ),
    _m(
        3,
        "the list of unchecked parts keeps a reading part as a page",
        "            word_pages.no_false_pages(line, document_id)\n"
        '            for line in meta.get("unchecked_parts") or []\n',
        '            line\n            for line in meta.get("unchecked_parts") or []\n',
    ),
    _m(
        4,
        "the sentences beside the rows keep a reading part as a page",
        '_META_TEXT = ("run_status_note", "incomplete_notice", "recommended_code_reason")\n',
        "_META_TEXT = ()\n",
    ),
)
