"""R15 part 1 (#779): every CRS comment carries its permanent number; machine
drafts are numbered NOT issued (crs_numbers, danger zone). Ids M795-01..05
(CLAUDE.md rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_779_crs_numbers_at_review_end.py"
_P = APP / "crs_numbers.py"
_TAG = ("w7", "crs")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M795-01", phase=795, description="a review's drafts are numbered as issued",
             path=_P, anchor="                         OPEN, 1 if issued else 0, scope_key)).rowcount",
             replacement="                         OPEN, 1, scope_key)).rowcount",
             target=_T, keyword="numbers_every_crs_row_as_a_draft", tags=_TAG),
    Mutation(id="M795-02", phase=795, description="an unissued draft no longer raised is carried forward",
             path=_P, anchor='" WHERE scope_key = ? AND status = ? AND issued = 1 ORDER BY seq"',
             replacement='" WHERE scope_key = ? AND status = ? ORDER BY seq"',
             target=_T, keyword="not_carried_forward", tags=_TAG),
    Mutation(id="M795-03", phase=795, description="confirming a numbered draft does not issue it",
             path=_P, anchor='                    "UPDATE crs_comment_numbers SET issued = 1"',
             replacement='                    "UPDATE crs_comment_numbers SET issued = 0"',
             target=_T, keyword="confirming_the_draft_issues", tags=_TAG),
    Mutation(id="M795-04", phase=795, description="a review un-issues an engineer's number",
             path=_P, anchor="        if issued:\n            # The engineer made a numbered draft theirs",
             replacement="        if True:\n            # The engineer made a numbered draft theirs",
             target=_T, keyword="numbers_every_crs_row_as_a_draft or never_un_issued", tags=_TAG),
    Mutation(id="M795-05", phase=795, description="the issued flag is not read back, so every number reads as issued",
             path=_P, anchor='            " last_review_run_id, issued")',
             replacement='            " last_review_run_id")',
             target=_T, keyword="numbers_every_crs_row_as_a_draft or never_un_issued", tags=_TAG),
)
