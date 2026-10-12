"""Mutations of `backend/app/blank_markers.py`.

CRS quick wins (2026-09-27, audit crs.md defect 12): ONE HOME for "this cell
says the value is not provided yet", read by the text extractor, the
geometry reader and the datasheet self-checks alike.
"""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1311", phase=96,
        description="a lone '*' (the enquiry-sheet convention) is no longer "
                    "recognised as blank",
        path=APP / "blank_markers.py",
        anchor='_WHOLE_CELL = re.compile(\n    r"^(?:\\*|-|',
        replacement='_WHOLE_CELL = re.compile(\n    r"^(?:-|',
        target="tests/test_blank_markers.py",
        keyword="test_a_lone_star_is_blank",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1312", phase=96,
        description="'N/A' is turned into a blank, asking a vendor for a "
                    "value the sheet has already said does not exist",
        path=APP / "blank_markers.py",
        anchor='    if folded in _ANSWERS:\n        return False, None\n',
        replacement='    if folded in _ANSWERS:\n        return True, folded\n',
        target="tests/test_blank_markers.py",
        keyword="test_na_is_an_answer_not_a_blank",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1313", phase=96,
        description="a marker inside a longer cell ('340 psig By Contractor') "
                    "is missed because only a whole-cell match is checked",
        path=APP / "blank_markers.py",
        anchor='    marker = _ANYWHERE.search(text)\n    if marker:\n        return True, marker.group(0).strip()\n',
        replacement='',
        target="tests/test_blank_markers.py",
        keyword="test_a_value_with_a_marker_anywhere_is_still_blank",
        tags=("honesty",),
    ),
)
