"""PR #914 (#883, PF3): an incomplete reading cannot be approved. `comparison.py`
is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_883_reading_coverage.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M914-01", phase=914,
             description="an approval is recommended although the reading is incomplete",
             path=_C,
             anchor='    if reading.get("status") == page_ledger.READING_INCOMPLETE and result["code"] in (codes[0], codes[1]):\n',
             replacement="    if False:\n",
             target=_T, keyword="incomplete_reading_cannot_be_approved or not_a_way_round", tags=("honesty", "critical")),
    Mutation(id="M914-02", phase=914,
             description="an approval WITH COMMENTS is allowed through an incomplete reading",
             path=_C,
             anchor='    if reading.get("status") == page_ledger.READING_INCOMPLETE and result["code"] in (codes[0], codes[1]):\n',
             replacement='    if reading.get("status") == page_ledger.READING_INCOMPLETE and result["code"] in (codes[0],):\n',
             target=_T, keyword="not_a_way_round", tags=("honesty", "critical")),
    Mutation(id="M914-03", phase=914,
             description="an incomplete reading downgrades a proven breach too",
             path=_C,
             anchor='    if reading.get("status") == page_ledger.READING_INCOMPLETE and result["code"] in (codes[0], codes[1]):\n',
             replacement='    if reading.get("status") == page_ledger.READING_INCOMPLETE:\n',
             target=_T, keyword="proven_breach_stays_a_breach", tags=("honesty", "critical")),
    Mutation(id="M914-04", phase=914,
             description="the reading status is not carried into the stored page coverage",
             path=_C,
             anchor="    return {**pages, **page_ledger.reading_gaps(datasheets.latest_reader_summary(submittal_id), pages)}\n",
             replacement="    return pages\n",
             target=_T, keyword="stored_page_coverage", tags=("honesty", "critical")),
)
