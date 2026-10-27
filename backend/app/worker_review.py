"""The ingestion worker's review-job drain (order 234).

A review job runs on the SAME single thread as document ingestion (the master
plan allows one worker on one 16 GB machine). So while a review runs, the
documents queued behind it wait, and a review step can take a long time (a 35B
model reads a page in about a minute and a half). The health badge read that as
"Queue not moving". A running review is now work: `reviewing` is true for its
whole run, health reports it as `busy`, and every progress update the job makes
(a step, a page, a scope answer) counts as the worker's heartbeat and progress.
"""

from __future__ import annotations

import time

from . import errors


#: A review that has reported nothing for this long (no step, page or scope
#: answer) is no longer "busy" (cloud's ask on #1323): a review stuck forever in
#: a model call must turn the badge red again. Generous: the 35B model takes
#: about 90 s a page and one uncached scope answer can run 15-20 minutes
#: (each answer is a beat).
REVIEW_SILENCE_SECONDS = 30 * 60


class ReviewDrain:
    """Mixin for `ingest.IngestionWorker`: it owns `last_beat`, `last_progress`,
    `last_error`, and calls `_drain_review_jobs` from its loop."""

    reviewing: bool = False

    def review_running(self) -> bool:
        """A review is running AND has reported within `REVIEW_SILENCE_SECONDS`."""
        return self.reviewing and time.time() - self.last_beat <= REVIEW_SILENCE_SECONDS

    def _review_activity(self) -> None:
        """A running review job reported progress: the worker is moving."""
        self.last_beat = self.last_progress = time.time()

    def _drain_review_jobs(self) -> bool:
        """Run one queued review, if any. True when one was run."""
        from . import job_queue, review_jobs

        try:
            review_jobs.recover_stale()
            job_id = review_jobs.claim_next(job_queue.worker_id())
            if job_id is None:
                return False
            self.reviewing = True
            self._review_activity()
            try:
                review_jobs.run(
                    job_id, job_queue.worker_id(), heartbeat=self._review_activity
                )
            finally:
                self.reviewing = False
                self._review_activity()
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = errors.record_failure(exc, stage="review_run")
            return False
