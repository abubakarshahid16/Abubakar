"""Order 234 (cloud's ask on #1323): every phase of a review run beats the
worker's heartbeat, so a removed beat is a failing test. Invented run, stubbed phases.

The first thing each phase does is logged as (name, beats so far). A phase's own
beat comes before its first call, so the count must RISE at every boundary: read,
standards, compare, checks, CRS numbering+wording. Remove any one phase's beat and
two neighbouring counts are equal.
"""

from __future__ import annotations

import pytest

from app import (
    applicability,
    company_standard_confirm,
    comparison,
    main,
    reread_for_standards,
    review_jobs,
    submittal_fill,
    submittal_review,
)
from tests import test_p3_review_jobs as p3

world, temp_storage = p3.world, p3.temp_storage  # the review-job fixtures

#: The first call of each phase, in run order.
PHASES = ["read", "standards", "compare", "checks", "crs"]


def _run(world, monkeypatch):
    """Run the job with every phase stubbed. Returns {phase: beats at its first call}."""
    _run_id, job_id = p3._enqueue(world)
    beats, seen = [], {}

    def first(phase, result=None):
        def stub(*args, **kwargs):
            seen.setdefault(phase, len(beats))
            return result

        return stub

    selection = {"missing_references": [], "reference_coverage": None}
    monkeypatch.setattr(submittal_review, "ensure_facts_extracted", first("read"))
    monkeypatch.setattr(submittal_fill, "for_review", first("standards"))
    monkeypatch.setattr(applicability, "select", first("standards", selection))
    monkeypatch.setattr(company_standard_confirm, "held_readable", lambda scope: {})
    monkeypatch.setattr(company_standard_confirm, "record_on_run", lambda *a, **k: None)
    monkeypatch.setattr(reread_for_standards, "for_review", lambda *a, **k: None)
    monkeypatch.setattr(comparison, "run_comparison", first("compare"))
    monkeypatch.setattr(review_jobs, "_ai_check", first("checks"))
    monkeypatch.setattr(review_jobs, "_web_check", lambda *a, **k: None)
    monkeypatch.setattr(main, "number_crs_rows", first("crs"))
    monkeypatch.setattr(main, "word_crs_rows", lambda *a, **k: None)
    review_jobs.claim_next(p3.W)

    def heartbeat():
        beats.append(1)

    review_jobs.run(job_id, p3.W, heartbeat=heartbeat)
    return seen


def test_every_phase_of_a_review_run_beats_the_workers_heartbeat(world, monkeypatch):
    seen = _run(world, monkeypatch)
    assert all(phase in seen for phase in PHASES), seen
    counts = [seen[phase] for phase in PHASES]
    assert counts[0] > 0, "the first phase started without a beat"
    assert all(a < b for a, b in zip(counts, counts[1:], strict=False)), (
        f"a phase started without its own beat: {dict(zip(PHASES, counts, strict=True))}"
    )


@pytest.mark.parametrize("phase", ["compare", "checks", "crs"])
def test_taking_one_phases_beat_out_is_noticed(world, monkeypatch, phase):
    """Swallow the beat a phase makes at its start (its `_phase` call is given no
    heartbeat) and the counts stop rising at that boundary."""
    real = review_jobs._phase

    def phase_without(conn, job_id, index, heartbeat, timings, name):
        wanted = {"compare": "compare", "checks": "checks", "crs": None}[phase]
        if name == wanted and (phase != "crs" or index is None):
            heartbeat = None
        return real(conn, job_id, index, heartbeat, timings, name)

    monkeypatch.setattr(review_jobs, "_phase", phase_without)
    seen = _run(world, monkeypatch)
    counts = [seen[p] for p in PHASES]
    assert not all(a < b for a, b in zip(counts, counts[1:], strict=False)), counts
