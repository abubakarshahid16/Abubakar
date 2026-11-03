"""Mutations of the contractor copy's engineer-free wording (item 14c, PR 1662)."""

from __future__ import annotations

from ._base import REPO, Mutation

_E = REPO / "backend" / "app" / "crs_export.py"
_T = "tests/test_crs_contractor_words.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1662-01",
        phase=1662,
        description="the engineer-free wording is applied to the internal copy as well",
        path=_E,
        anchor="    else:  # item 14c: before the no-text rule, so an emptied comment is withheld and counted\n",
        replacement="    if True:  # item 14c: before the no-text rule, so an emptied comment is withheld and counted\n",
        target=_T,
        keyword="internal_copy_is_unchanged",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M1662-02",
        phase=1662,
        description="the contractor copy keeps its engineer wording",
        path=_E,
        anchor="        findings = [quality.contractor_words(f) for f in findings]\n",
        replacement="        findings = findings\n",
        target=_T,
        keyword="names_the_engineer",
        tags=("crs", "honesty"),
    ),
)
