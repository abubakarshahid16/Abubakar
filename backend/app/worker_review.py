"""The worker's REVIEW LANE (order 234; its own thread since update 7, planner 19 Nov 2026 01:02, GitHub #1913).

A review runs on the worker's review thread, beside the upload lane (`ingest.IngestionWorker._run`), so page reading and rule
extraction of an upload never wait behind a running review. The two lanes never run two large local models: every local model
call passes `local_model_gate` (a call of the other lane waits only while one is in flight). `reviewing` is true for a review's
whole run, health reports it as `busy`, and every progress update the job makes (a step, a page, a scope answer, a model call)
is the REVIEW lane's heartbeat (`last_review_beat`), never the upload lane's.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar

from . import errors, model_metrics

#: A review that has reported nothing for this long (no step, page or scope
#: answer) is no longer "busy" (cloud's ask on #1323): a review stuck forever in
#: a model call must turn the badge red again. Generous: the 35B model takes
#: about 90 s a page and one uncached scope answer can run 15-20 minutes
#: (each answer is a beat).
REVIEW_SILENCE_SECONDS = 30 * 60


#: The running review's heartbeat for THIS thread (set by `_drain_review_jobs`).
_ACTIVITY: ContextVar[Callable[[], None] | None] = ContextVar(
    "review_activity", default=None
)


def beat_now() -> float:
    """`time.time()`, and a beat of the running review's heartbeat when a review
    is running on this thread: every local model call starts and ends with one
    (`reasoning_provider.OllamaProvider.reason`), so the comparison, the AI
    checks and the wording are activity too, not only the phase boundaries."""
    beat = _ACTIVITY.get()
    if beat is not None:
        beat()
    return time.time()


@contextmanager
def keep_beating(every: float = 30.0):
    """Beat the running review's heartbeat every `every` seconds while a call that cannot beat itself is waiting (a Claude request can
    take minutes). Bounded by the call: it ends when the `with` block does, so a request that never returns still ends at its own
    timeout. Nothing is done when no review is running on this thread."""
    beat = _ACTIVITY.get()
    if beat is None:
        yield
        return
    done = threading.Event()

    def loop() -> None:
        while not done.wait(every):
            beat()

    thread = threading.Thread(target=loop, name="review-beat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=1.0)


class ReviewDrain:
    """Mixin for `ingest.IngestionWorker`: it owns `last_error` and the review thread (`_review_thread`), which calls
    `_drain_review_jobs` from `_review_run`."""

    reviewing: bool = False
    last_review_beat: float = 0.0
    _review_thread: threading.Thread | None = None

    @property
    def review_alive(self) -> bool:
        thread = self._review_thread
        return bool(thread and thread.is_alive())

    def in_review(self) -> bool:
        """A review is running, the review thread is alive, and it has reported within `REVIEW_SILENCE_SECONDS`."""
        fresh = time.time() - self.last_review_beat <= REVIEW_SILENCE_SECONDS
        return self.reviewing and self.review_alive and fresh

    def review_silent_for(self) -> float | None:
        """Seconds a running review has reported nothing, past `REVIEW_SILENCE_SECONDS`; None otherwise."""
        if not (self.reviewing and self.review_alive):
            return None
        age = time.time() - self.last_review_beat
        return age if age > REVIEW_SILENCE_SECONDS else None

    def beat_age_of_claim(self, claimed_by: str | None) -> int | None:
        """Seconds since this worker's last beat, when it is in review and its
        own thread holds `claimed_by`; else None. Model calls beat the worker and
        never the jobs row, so only this tells a long call from a dead job."""
        from . import job_queue

        thread = self._review_thread
        if thread is None or not self.in_review():
            return None
        if claimed_by != f"w-{job_queue._PROCESS_TOKEN}-{thread.ident}":
            return None
        return max(0, int(time.time() - self.last_review_beat))

    def _review_activity(self) -> None:
        """A running review job reported progress: the review lane is moving."""
        self.last_review_beat = time.time()

    def _review_run(self) -> None:
        """The review lane's loop (its own thread): one queued review after another; an idle poll otherwise."""
        from . import local_model_gate

        with local_model_gate.lane(local_model_gate.REVIEW):
            while not self._stop.is_set():
                self._review_activity()
                try:
                    if not self._drain_review_jobs():
                        self._idle_wait()
                except Exception as exc:  # noqa: BLE001 - the lane never dies of one failure: recorded, then the next poll
                    self.last_error = errors.record_failure(exc, stage="review_lane")
                    self._stop.wait(self.poll_seconds)

    def _idle_wait(self) -> None:
        """Nothing to do: a clause review waiting on a Claude batch gets one short poll when
        due, never a wait for the batch, then the worker sleeps as before."""
        from . import clause_review_claude

        clause_review_claude.poll_due()
        self._stop.wait(self.poll_seconds)

    def _drain_review_jobs(self) -> bool:
        """Run one queued review, if any. True when one was run."""
        from . import agent_review_jobs, aim_review_jobs, job_queue, review_jobs

        try:
            review_jobs.recover_stale()
            agent_review_jobs.recover_stale()  # the AI reviewer's own stage; nothing at all with its switch off
            aim_review_jobs.recover_stale()  # the general review's stage (order 14); nothing with the old engine on
            job_id = review_jobs.claim_next(job_queue.worker_id())
            job_run = review_jobs.run
            if job_id is None:
                # None with the switch off
                job_id = agent_review_jobs.claim_next(job_queue.worker_id())
                job_run = agent_review_jobs.run
            if job_id is None:
                # after the two old stages (a review queued before the switch still finishes); None with the old engine on
                job_id = aim_review_jobs.claim_next(job_queue.worker_id())
                job_run = aim_review_jobs.run
            if job_id is None:
                return False
            self.reviewing = True
            self._review_activity()
            token = _ACTIVITY.set(self._review_activity)
            try:
                with model_metrics.collect() as bucket:
                    try:
                        job_run(
                            job_id,
                            job_queue.worker_id(),
                            heartbeat=self._review_activity,
                        )
                    finally:  # a failed review's calls are worth knowing too
                        model_metrics.store_for_job(job_id, bucket)
            finally:
                _ACTIVITY.reset(token)
                self.reviewing = False
                self._review_activity()
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = errors.record_failure(exc, stage="review_run")
            return False
