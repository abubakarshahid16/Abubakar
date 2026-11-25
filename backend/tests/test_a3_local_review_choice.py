# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""A3 (planner 26 Nov 2026 03:35): the Review model choice on the plan screen. Local only runs the general review on the local
model and the plan shows ONE line with its measured time and score; Claude and Automatic never show it. Its way back,
GENERAL_REVIEW_LOCAL_ENABLED, turned off refuses Local only before the start, says so on the method route, and stops a run queued
before the switch was turned off without loading any model. Invented papers only (the dry-run library); no engine is called."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import aim_review_gate, aim_review_jobs, job_queue, model_transport
from app.config import settings
from app.main import app
from tests.test_aim_dry_run import PAPERS, dry  # noqa: F401 - fixture
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture
from tests.test_u7c_local_general import (  # noqa: F401 - fixtures
    _no_claude,
    _run_row,
    _start_local,
    unloaded,
    world,
)


def _plan(w, paper_id: str, engine: str) -> dict:
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={"submittal_document_id": paper_id, "engine": engine},
        headers=w["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _method(w) -> dict:
    return TestClient(app).get("/api/reviews/method", headers=w["headers"]).json()


def test_local_only_shows_the_measured_line_and_claude_and_automatic_do_not(world):
    paper_id = PAPERS["datasheet"][0]
    local = _plan(world, paper_id, "local")
    assert local["refused"] is None and local["text_leaves"] is False
    assert local["notes"].count(aim_review_gate.LOCAL_TEST_NOTE) == 1
    for engine in ("automatic", "claude"):
        assert (
            aim_review_gate.LOCAL_TEST_NOTE
            not in _plan(world, paper_id, engine)["notes"]
        )
    assert _method(world)["local_available"] is True
    assert _method(world)["local_words"] == aim_review_gate.LOCAL_PLAN_WORDS


def test_the_way_back_refuses_local_only_before_the_start_and_says_so(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "general_review_local_enabled", False)
    paper_id = PAPERS["datasheet"][0]
    plan = _plan(world, paper_id, "local")
    assert plan["refused"] == aim_review_gate.LOCAL_SWITCHED_OFF
    assert aim_review_gate.LOCAL_TEST_NOTE not in plan["notes"]
    r = TestClient(app).post(
        "/api/reviews/start",
        json={
            "submittal_document_id": paper_id,
            "engine": "local",
            "shown_document_ids": [],
        },
        headers=world["headers"],
    )
    assert r.status_code >= 400  # refused, never queued
    method = _method(world)
    assert method["local_available"] is False
    assert method["local_words"] == aim_review_gate.LOCAL_SWITCHED_OFF


def test_a_run_queued_before_the_way_back_stops_without_loading_a_model(
    world, monkeypatch
):
    _no_claude(monkeypatch)

    def no_load(*_a, **_k):
        raise AssertionError("a model was loaded although Local only is switched off")

    monkeypatch.setattr(model_transport, "post_json", no_load)
    run_id = _start_local(world, PAPERS["datasheet"][0])
    monkeypatch.setattr(settings, "general_review_local_enabled", False)
    worker = job_queue.worker_id()
    assert (
        aim_review_jobs.run(aim_review_jobs.claim_next(worker), worker)
        == job_queue.DONE
    )
    run = _run_row(run_id)
    assert run["status"] == "stopped"
    assert (
        run["stop_reason"] == f"local_not_ready: {aim_review_gate.LOCAL_SWITCHED_OFF}"
    )


@pytest.mark.parametrize("on", [True, False])
def test_the_way_back_is_read_in_one_place(monkeypatch, on):
    monkeypatch.setattr(settings, "general_review_local_enabled", on)
    assert aim_review_gate.local_on() is on


def test_automatic_never_picks_the_local_route_for_the_general_review_by_itself():
    """Lead-4, update 9: with GENERAL_REVIEW_LOCAL_ENABLED on, only an explicit Local only runs the general review on the local
    model. Automatic, under every combination of the plan's yes/no facts and kinds, never plans the general review on the local
    model: it runs on Claude or is refused with its reason. Pure plan decision: no model, no call."""
    import dataclasses
    import itertools

    from app import review_engine_general as G
    from app.review_engine import ON_LOCAL, Facts

    flags = [f.name for f in dataclasses.fields(Facts) if f.type in (bool, "bool")]
    assert "local_enabled" in flags and len(flags) >= 10
    seen = 0
    for kind in ("datasheet", "contract", None):
        for values in itertools.product((False, True), repeat=len(flags)):
            f = Facts(kind=kind, **dict(zip(flags, values)))
            plan = G.decide_general(G.AUTOMATIC, G.narrowed(G.AUTOMATIC, f))
            assert all(p.engine != ON_LOCAL for p in plan.parts), (
                kind,
                dict(zip(flags, values)),
            )
            seen += 1
    assert seen == 3 * 2 ** len(flags)
