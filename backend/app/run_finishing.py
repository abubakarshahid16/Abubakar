"""A run whose job is still finishing is still running (order 236).

`comparison._store_run_outcome` stores the run's outcome with status
"completed" BEFORE the review job has written the AI engineering-check drafts,
the CRS numbers, the CRS wording and the trace (about a minute on the 35B
model). The app showed "Review ready" and offered Export in that gap, and the
owner's export came out without the AI rows and their wording. [found-on]

Until the job is done, every read of the run (`submittal_review.get_review_run`
and `list_review_runs`) says "running" - so "Review ready", the document
cards, the export's incomplete-review note and the fact routes all wait.
"""

from __future__ import annotations

#: The extra column of the run select: true while the run is "completed" and
#: its job is still queued or running.
COLUMN = (
    ", (r.status = 'completed' AND EXISTS (SELECT 1 FROM jobs j"
    " WHERE j.review_run_id = r.id AND j.state IN ('queued', 'running')))"
    " AS finishing"
)


def shown(row) -> dict:
    """A run row as readers see it: still `running` while its job finishes."""
    run = dict(row)
    if run.pop("finishing", 0):
        run["status"] = "running"
    return run
