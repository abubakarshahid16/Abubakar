"""Mutations of P3: reviews on the job queue."""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_p3_review_jobs.py"
_R = APP / "review_jobs.py"
_V = FRONTEND_SRC / "views" / "ReviewRunsView.tsx"
_VT = "src/views/ReviewRunsView.jobs.test.tsx"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M880", phase=77, description="P3: the review runs inside the request again",
             path=APP / "main.py",
             anchor="        run_id, _job_id = review_jobs_mod.enqueue(\n",
             replacement="        run_id, _job_id = (lambda r: (review_jobs_mod.run(review_jobs_mod.claim_next('w'), 'w') and r))(review_jobs_mod.enqueue(\n",
             target=_T, keyword="does_no_review_work", tags=("jobs",)),
    Mutation(id="M881", phase=77, description="P3: two reviews of one submittal may be queued",
             path=_R, anchor="        if active is not None:\n            raise ReviewAlreadyActive(active[\"id\"])\n",
             replacement="", target=_T, keyword="second_review", tags=("jobs", "critical")),
    Mutation(id="M882", phase=77, description="P3: a cancellation is never honoured while running",
             path=_R, anchor="        if row and row[\"cancel_requested\"]:\n            raise _Cancelled()\n",
             replacement="", target=_T, keyword="stops_at_the_next_step", tags=("jobs",)),
    Mutation(id="M883", phase=77, description="P3: a cancelled review keeps its half-written findings",
             path=_R, anchor="            conn.execute(\"DELETE FROM review_findings WHERE review_run_id = ?\"\n                         \" AND confirmed_by IS NULL\", (run_id,))\n",
             replacement="", target=_T, keyword="stops_at_the_next_step", tags=("honesty",)),
    Mutation(id="M884", phase=77, description="P3: the worker reviews with every document, not the requester's",
             path=_R, anchor="    scope = _scope_of(job[\"created_by\"])\n",
             replacement="    scope = frozenset(r[0] for r in conn.execute('SELECT id FROM documents'))\n",
             target=_T, keyword="requesters_grants", tags=("privacy", "critical")),
    Mutation(id="M885", phase=77, description="P3: a crashed review is not re-queued",
             path=_R, anchor="            \" AND (claimed_at IS NULL OR claimed_at < ?) RETURNING id, review_run_id\",\n",
             replacement="            \" AND 0 AND (claimed_at IS NULL OR claimed_at < ?) RETURNING id, review_run_id\",\n",
             target=_T, keyword="requeued_not_failed", tags=("jobs",)),
    Mutation(id="M886", phase=77, description="P3: startup fails a run whose job is still active",
             path=APP / "submittal_review.py",
             anchor="            \" AND id NOT IN (SELECT review_run_id FROM jobs WHERE review_run_id IS NOT NULL\"\n            \" AND state IN ('queued', 'running', 'retrying'))\",\n",
             replacement="", target=_T, keyword="requeued_not_failed", tags=("jobs",)),
    Mutation(id="M887", phase=77, description="P3: a poisoned review leaves its run looking queued",
             path=_R, anchor="            if state == job_queue.POISONED:\n",
             replacement="            if False:\n", target=_T, keyword="retried_then_poisoned", tags=("honesty",)),
    Mutation(id="M888", phase=77, runner="vitest", description="P3 UI: the cancel control is never offered",
             path=_V, anchor="  if (!job || !(run.status === \"queued\" || run.status === \"running\") || job.cancel_requested) return null;\n",
             replacement="  return null;\n", target=_VT, keyword="cancels it on request", tags=("ui",)),
    Mutation(id="M889", phase=77, runner="vitest", description="P3 UI: a pending cancellation is not shown",
             path=_V, anchor="          {run.job.cancel_requested ? \" · cancellation requested, stopping at the next step\" : \"\"}\n",
             replacement="", target=_VT, keyword="cancellation is pending", tags=("honesty", "ui")),
)
