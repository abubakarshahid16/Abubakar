"""Order 234 (cloud's ask on #1323): every phase of a review run beats the
worker's heartbeat, so a removed beat is a failing test. Invented run, stubbed phases."""

from __future__ import annotations

from app import review_jobs
from tests import test_p3_review_jobs as p3

world, temp_storage = p3.world, p3.temp_storage  # the review-job fixtures


def test_every_phase_of_a_review_run_beats_the_workers_heartbeat(world, monkeypatch):
    """cloud's ask on #1323: a beat at the start of each phase, so a removed
    beat is a failing test. The comparison, the AI checks, the CRS numbering and
    the wording are separate phases of `run()`, stubbed here to log the beats."""
    from app import comparison, main

    _run_id, job_id = p3._enqueue(world)
    beats = []
    seen = {}

    def log(name):
        def stub(*args, **kwargs):
            seen[name] = len(beats)

        return stub

    monkeypatch.setattr(comparison, "run_comparison", log("compare"))
    monkeypatch.setattr(review_jobs, "_ai_check", log("ai_check"))
    monkeypatch.setattr(review_jobs, "_web_check", log("web_check"))
    monkeypatch.setattr(main, "number_crs_rows", log("numbering"))
    monkeypatch.setattr(main, "word_crs_rows", log("wording"))
    review_jobs.claim_next(p3.W)
    review_jobs.run(job_id, p3.W, heartbeat=lambda: beats.append(1))
    order = ["compare", "ai_check", "numbering"]
    assert all(name in seen for name in order), seen
    counts = [seen[name] for name in order]
    assert counts == sorted(set(counts)), (
        f"a phase started without its own beat: {counts}"
    )
