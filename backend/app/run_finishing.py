"""A run whose job is still finishing is still running (order 236).

`comparison._store_run_outcome` stores the run's outcome with status
"completed" BEFORE the review job has written the AI engineering-check drafts,
the CRS numbers, the CRS wording and the trace (about a minute on the 35B
model). The app showed "Review ready" and offered Export in that gap, and the
owner's export came out without the AI rows and their wording. [found-on]

Until the job is done, every read of the run (`submittal_review.get_review_run`
and `list_review_runs`) says "running" - so "Review ready", the document
cards, the PDF report header (`export_status.latest_run`), the export's
incomplete-review note and the fact routes all wait.

A job left "running" by a worker that died keeps its run "running" (visible, and
the export says it is not finished); the restart recovery of order 231
(`review_recovery`) releases it.
"""

from __future__ import annotations

#: True while the run is "completed" and its job is still queued or running.
#: Needs the run table aliased `r`.
FINISHING = (
    "r.status = 'completed' AND EXISTS (SELECT 1 FROM jobs j"
    " WHERE j.review_run_id = r.id AND j.state IN ('queued', 'running'))"
)
#: The extra column of the run select (`shown` reads it).
COLUMN = f", ({FINISHING}) AS finishing"
#: The run's status as a reader sees it, for a query that reads the status
#: column directly (the document cards, the PDF report header).
STATUS = f"(CASE WHEN {FINISHING} THEN 'running' ELSE r.status END)"


def shown(row) -> dict:
    """A run row as readers see it: still `running` while its job finishes."""
    run = dict(row)
    if run.pop("finishing", 0):
        run["status"] = "running"
    return run
