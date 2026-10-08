"""Mutations of the B11 job rules: one job per request, cancellation,
concurrency bound, provenance, audit, scoped job API."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_b11_jobs.py"
_Q = APP / "job_queue.py"
_S = APP / "standards.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M853", phase=74, description="B11: enqueue checks and inserts without the write lock",
             path=_S, anchor="    with job_queue.immediate(conn):\n        existing = conn.execute(\n",
             replacement="    with conn:\n        existing = conn.execute(\n",
             target=_T, keyword="queue_one_job", tags=("jobs", "critical")),
    Mutation(id="M854", phase=74, description="B11: two reviews of one submittal may run at once",
             path=APP / "submittal_review.py",
             anchor="        if running is not None:\n            raise ReviewAlreadyRunning(running[\"id\"])\n",
             replacement="", target=_T, keyword="second_review", tags=("jobs",)),
    Mutation(id="M855", phase=74, description="B11: a job no longer records which code produced it",
             path=_S, anchor='             provenance.code_version("standards", "tables", "requirements_3b"),\n             config_version()))\n',
             replacement="             None,\n             config_version()))\n",
             target=_T, keyword="which_code_and_settings", tags=("provenance",)),
    Mutation(id="M856", phase=74, description="B11: a cancelled job is claimed and run anyway",
             path=APP / "standards.py",
             anchor="_CLAIMABLE = (\"(state = 'queued' OR (state = 'retrying'\"\n",
             replacement="_CLAIMABLE = (\"(state IN ('queued', 'cancelled') OR (state = 'retrying'\"\n",
             target=_T, keyword="never_claimed", tags=("jobs", "critical")),
    Mutation(id="M857", phase=74, description="B11: a running job is reported cancelled",
             path=_Q, anchor="CANCELLABLE = (QUEUED, RETRYING)\n",
             replacement="CANCELLABLE = (QUEUED, RETRYING, RUNNING)\n",
             target=_T, keyword="not_reported_cancelled", tags=("honesty",)),
    Mutation(id="M858", phase=74, description="B11: the concurrency limit is not applied",
             path=_Q, anchor="            \" AND state = 'running' AND claimed_at >= :stale) < :limit\")\n",
             replacement="            \" AND state = 'running' AND claimed_at >= :stale) < :limit + 100\")\n",
             target=_T, keyword="than_the_limit", tags=("jobs",)),
    Mutation(id="M859", phase=74, description="B11: a dead worker's claim holds the limit forever",
             path=_Q, anchor="            \" AND state = 'running' AND claimed_at >= :stale) < :limit\")\n",
             replacement="            \" AND state = 'running' AND :stale IS NOT NULL) < :limit\")\n",
             target=_T, keyword="dead_workers_claim", tags=("jobs",)),
    Mutation(id="M860", phase=74, description="B11: poisoning a job is not audited",
             path=_Q, anchor='    audit(conn, "job.poisoned", job_id, detail=f"error={code}")\n',
             replacement="", target=_T, keyword="poison_and_completion", tags=("audit",)),
    Mutation(id="M861", phase=74, description="B11: the job list ignores the caller's grants",
             path=_Q, anchor="    ids = sorted(allowed_document_ids if document_id is None\n                 else allowed_document_ids & {document_id})\n",
             replacement="    ids = sorted(r[0] for r in __import__('app.db', fromlist=['connect']).connect().execute('SELECT id FROM documents'))\n",
             target=_T, keyword="readable_documents", tags=("privacy", "critical")),
    Mutation(id="M862", phase=74, description="B11: one job is readable on a document the caller cannot read",
             path=_Q, anchor='    if row is None or row["document_id"] not in allowed_document_ids:\n',
             replacement="    if row is None:\n", target=_T, keyword="readable_documents", tags=("privacy", "critical")),
    Mutation(id="M863", phase=74, description="B11: a non-admin may cancel",
             path=APP / "main.py",
             anchor="    scope: access.AccessScope = Depends(access.current_scope),\n    actor: dict | None = Depends(admin_mod.current_admin),\n):\n    \"\"\"B11: withdraw a job",
             replacement="    scope: access.AccessScope = Depends(access.current_scope),\n    actor: dict | None = None,\n):\n    \"\"\"B11: withdraw a job",
             target=_T, keyword="needs_an_admin", tags=("privacy",)),
    Mutation(id="M864", phase=74, description="B11: cancelling twice is reported as a cancellation",
             path=APP / "main.py", anchor="    if not cancelled:\n",
             replacement="    if state != job_queue_mod.CANCELLED:\n",
             target=_T, keyword="needs_an_admin", tags=("honesty",)),
)
