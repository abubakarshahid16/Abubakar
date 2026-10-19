"""Order 139 fix 3 (#882): a standard's question with no datasheet field and
no datasheet page behind it is a Review note, never a CRS line. `crs_mapping.py`
is in the danger zone (rule 6). PLACEHOLDER ids M139C-01.. and phase 139: the
lead renames them M<PR number>-0N, phase=<PR number> once the PR is open."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_139_citation_scope.py"
_M = APP / "crs_mapping.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M139C-01",
        phase=139,
        description="a question with no datasheet field is a CRS line again",
        path=_M,
        anchor="    questions = [f for f in questions if not _no_datasheet_field(f)]  # #139\n",
        replacement="",
        target=_T,
        keyword="review_note_not_a_crs_line",
        tags=("crs", "honesty"),
    ),
    Mutation(
        id="M139C-02",
        phase=139,
        description="a question taken off the CRS is not noted for the engineer (silent loss)",
        path=_M,
        anchor="        if not _rejected(f) and _no_datasheet_field(f):\n",
        replacement="        if False:\n",
        target=_T,
        keyword="review_note_not_a_crs_line",
        tags=("crs", "honesty", "critical"),
    ),
    Mutation(
        id="M139C-03",
        phase=139,
        description="an engineer-confirmed question with no page is dropped from the CRS",
        path=_M,
        anchor="        and not _page_reader_only(finding)\n        and not _confirmed(finding)\n",
        replacement="        and not _page_reader_only(finding)\n",
        target=_T,
        keyword="engineer_confirmed_question",
        tags=("crs",),
    ),
    Mutation(
        id="M139C-04",
        phase=139,
        description="a question paired with a datasheet field leaves the CRS too",
        path=_M,
        anchor='        and not (finding.get("fact_id") or finding.get("contractor_page"))\n',
        replacement="",
        target=_T,
        keyword="review_note_not_a_crs_line",
        tags=("crs",),
    ),
)
