# ruff: noqa: F811
"""Order 14, piece E: `GET /api/reviews/method`, the one home of each sentence, the way back (`REVIEW_OLD_ENGINE_ENABLED`) on the routes,
and the classification of the four new settings. Invented values only."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import access, aim_review_gate, aim_review_store, db, review_engine
from app.config import settings
from app.main import app
from tests import env_isolation
from tests.test_b1_review_engine import (  # noqa: F401 - fixtures
    _rows,
    lane,
    temp_storage,
    world,
)

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
FRONTEND_SRC = BACKEND.parent / "frontend" / "src"

SENTENCES = {
    "AI_MARK": aim_review_gate.AI_MARK,
    "LOCAL_NOT_AVAILABLE": aim_review_gate.LOCAL_NOT_AVAILABLE,
    "LOCAL_PLAN_WORDS": aim_review_gate.LOCAL_PLAN_WORDS,
    "LOCAL_RUN_WHY": aim_review_gate.LOCAL_RUN_WHY,
    "LOCAL_NOT_SCORED": aim_review_gate.LOCAL_NOT_SCORED,
    "NO_CONTRACTOR_COPY_WORDS": aim_review_gate.NO_CONTRACTOR_COPY_WORDS,
    "OLD_ENGINE_OFF_WORDS": aim_review_gate.OLD_ENGINE_OFF_WORDS,
    "EARLIER_VERSION": aim_review_gate.EARLIER_VERSION,
}
FOUR_SETTINGS = (
    "review_old_engine_enabled",
    "general_review_max_usd_per_run",
    "general_review_lead_model",
    "general_review_strong_model",
)


def _get_method(world) -> dict:
    r = TestClient(app).get("/api/reviews/method", headers=world["admin"])
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(autouse=True)
def _clean_override(temp_storage):
    aim_review_store.ensure_schema()
    yield
    app.dependency_overrides.pop(access.current_scope, None)


# --- the route ---------------------------------------------------------------------------------------------------------


def test_the_method_route_says_general_when_the_old_engine_is_off(world, monkeypatch):
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    assert _get_method(world) == {
        "method": "general",
        "old_engine": False,
        # Local only runs the general review on the local model (planner 25 Nov 2026 22:35): available, with its own words
        "local_available": True,
        "local_words": aim_review_gate.LOCAL_PLAN_WORDS,
        "mark": aim_review_gate.AI_MARK,
    }


def test_the_method_route_says_earlier_when_the_way_back_is_on(world, monkeypatch):
    monkeypatch.setattr(settings, "review_old_engine_enabled", True)
    body = _get_method(world)
    assert body["method"] == "earlier" and body["old_engine"] is True
    assert (
        body["local_available"] is True
    )  # a constant since the local route; the screen reads it for the general method only


def test_the_method_route_needs_a_signed_in_caller():
    r = TestClient(app).get("/api/reviews/method")
    assert r.status_code == 401


def test_the_method_route_writes_nothing(world, monkeypatch):
    before = {t: _rows(t) for t in ("jobs", "review_runs", "audit_events")}
    _get_method(world)
    assert {t: _rows(t) for t in before} == before


# --- one home for each sentence -----------------------------------------------------------------------------------------


def _files(root: Path, suffixes: tuple[str, ...]):
    for p in sorted(root.rglob("*")):
        if (
            p.is_file()
            and p.suffix in suffixes
            and "node_modules" not in p.parts
            and "__pycache__" not in p.parts
        ):
            yield p


def test_each_sentence_has_one_home_in_the_backend():
    gate = (APP / "aim_review_gate.py").resolve()
    for name, text in SENTENCES.items():
        # the longer sentences are written as adjacent string literals: look for the first literal's words
        probe = text[:40]
        assert len(probe) >= 15 or name in {"EARLIER_VERSION"}
        homes = [
            p
            for p in _files(APP, (".py",))
            if probe in p.read_text(encoding="utf-8") and p.resolve() != gate
        ]
        if name in {"AI_MARK", "EARLIER_VERSION"}:
            # a short word the sentences of other files may carry inside a longer one: they must read the constant instead
            homes = [
                p
                for p in homes
                if re.search(
                    rf"""["']{re.escape(text)}["']""", p.read_text(encoding="utf-8")
                )
            ]
        assert homes == [], f"{name} is written again in {[h.name for h in homes]}"


def test_each_sentence_is_defined_once_in_the_gate():
    src = (APP / "aim_review_gate.py").read_text(encoding="utf-8")
    for name in SENTENCES:
        assert len(re.findall(rf"^{name}\s*=", src, flags=re.M)) == 1, name
    assert SENTENCES["AI_MARK"] in SENTENCES["NO_CONTRACTOR_COPY_WORDS"]


def test_the_frontend_does_not_write_the_sentences_it_reads_from_the_route():
    if not FRONTEND_SRC.exists():
        pytest.skip("no frontend checkout")
    for name in (
        "LOCAL_NOT_AVAILABLE",
        "NO_CONTRACTOR_COPY_WORDS",
        "OLD_ENGINE_OFF_WORDS",
    ):
        probe = SENTENCES[name][:40]
        written = [
            str(p.relative_to(FRONTEND_SRC))
            for p in _files(FRONTEND_SRC, (".ts", ".tsx"))
            if probe in p.read_text(encoding="utf-8") and ".test." not in p.name
        ]
        assert written == [], f"{name} is hard-coded in {written}"


def test_only_the_gate_reads_the_way_back_setting():
    """Every piece reads `review_old_engine_enabled` ONLY through `aim_review_gate` (settings, env isolation and tests excepted)."""
    allowed = {"aim_review_gate.py", "settings_ext.py"}
    readers = [
        str(p.relative_to(APP))
        for p in _files(APP, (".py",))
        if p.name not in allowed
        and "review_old_engine_enabled" in p.read_text(encoding="utf-8")
    ]
    assert readers == [], f"read the way-back setting directly: {readers}"


# --- the way back on the routes ------------------------------------------------------------------------------------------


def _job_stages() -> set[str]:
    return {r[0] for r in db.connect().execute("SELECT DISTINCT stage FROM jobs")}


def test_with_the_old_engine_on_the_plan_and_the_start_are_the_old_ones(
    world,
    lane,
    monkeypatch,
):
    monkeypatch.setattr(settings, "review_old_engine_enabled", True)
    client = TestClient(app)
    plan = client.get(
        "/api/reviews/plan",
        params={"submittal_document_id": world["sub"], "engine": "local"},
        headers=world["admin"],
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body.get("method", "earlier") == "earlier"
    # the recorded old answer: the pure resolver's own plan for the same paper
    old = review_engine.plan_for(db.connect(), world["sub"], world["scope"], "local")
    assert body["parts"] == old["parts"] and body["text_leaves"] == old["text_leaves"]
    assert "GENERAL_NOT_ON_LOCAL" not in plan.text
    assert aim_review_gate.LOCAL_NOT_AVAILABLE not in plan.text
    before = _rows("jobs")
    start = client.post(
        "/api/reviews/start",
        json={"submittal_document_id": world["sub"], "engine": "local"},
        headers=world["admin"],
    )
    assert start.status_code == 200, (
        start.text
    )  # Local only still runs the old rule check
    assert _rows("jobs") == before + 1
    assert "aim_review" not in _job_stages()
    assert aim_review_gate.LOCAL_NOT_AVAILABLE not in start.text


def test_with_the_old_engine_on_no_start_route_reaches_the_general_review(
    world,
    lane,
    monkeypatch,
):
    monkeypatch.setattr(settings, "review_old_engine_enabled", True)
    client = TestClient(app)
    for path, payload in (
        (
            "/api/reviews/start",
            {"submittal_document_id": world["sub"], "engine": "claude"},
        ),
        ("/api/reviews/run", {"submittal_document_id": world["sub"]}),
        ("/api/reviews/agent-run", {"submittal_document_id": world["sub"]}),
    ):
        client.post(path, json=payload, headers=world["admin"])
    assert "aim_review" not in _job_stages()
    assert _rows("aim_runs") == 0


def test_the_way_back_changes_only_the_method_the_routes_report(world, monkeypatch):
    seen = {}
    for flag in (False, True):
        monkeypatch.setattr(settings, "review_old_engine_enabled", flag)
        seen[flag] = _get_method(world)
    assert seen[False]["method"] == "general" and seen[True]["method"] == "earlier"
    same = {k for k in seen[False] if seen[False][k] == seen[True][k]}
    assert same == {"local_available", "local_words", "mark"}
    assert seen[False]["old_engine"] is not seen[True]["old_engine"]


# --- the four settings are classified -------------------------------------------------------------------------------------


def test_the_four_settings_are_classified_in_the_env_isolation_list():
    for name in FOUR_SETTINGS:
        assert name in env_isolation.EGRESS_SAFE, name
    assert env_isolation.TEST_PINS["review_old_engine_enabled"] is True
    # the three knobs are inert in tests whatever the machine says: they equal the production defaults
    from app.config import Settings

    clean = Settings()
    for name in FOUR_SETTINGS[1:]:
        assert env_isolation.EGRESS_SAFE[name] == getattr(clean, name), name
