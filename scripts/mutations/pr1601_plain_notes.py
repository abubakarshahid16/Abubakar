"""#1592 items d and e / PR 1601 (crs_export is danger zone): the notice names its parts, so
the workbook must not clip it. The test file must notice."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1601-01",
        phase=1601,
        description="the notice row stays 30 high and clips the named parts",
        path=APP / "crs_export.py",
        anchor="        ws.row_dimensions[notice_row].height = quality.notice_height(view)\n",
        replacement="        ws.row_dimensions[notice_row].height = 30\n",
        target="tests/test_crs_plain_notes.py",
        keyword="notice_row_is_tall",
        tags=("pr1601", "crs_plain_notes"),
    ),
)
