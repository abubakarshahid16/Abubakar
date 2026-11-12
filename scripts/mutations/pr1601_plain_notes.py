"""#1592 items d and e / PR 1601 (crs_export is danger zone): the notice names its parts, so
the workbook must not clip it. The test file must notice."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1601-01",
        phase=1601,
        description="the notice row stays 30 high and clips the named parts",
        path=APP / "crs_normal.py",
        anchor="quality.notice_height(view))]",
        replacement="30)]",
        target="tests/test_crs_plain_notes.py",
        keyword="notice_row_is_tall",
        tags=("pr1601", "crs_plain_notes"),
    ),
    Mutation(
        id="M1601-02",
        phase=1601,
        description="a safety row carries no tick state, so a ticked row says it waits",
        path=APP / "crs_mapping.py",
        anchor="        rows[-1].update(crs_decider.tick_state(f))\n",
        replacement="",
        target="tests/test_crs_plain_notes.py",
        keyword="ticked_row_through_the_real_path",
        tags=("pr1601", "crs_plain_notes"),
    ),
)
