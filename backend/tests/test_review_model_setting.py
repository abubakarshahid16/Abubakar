# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""The Review model setting (planner 25 Nov 2026 22:40; lead-4, 26 Nov 2026): the administrator picks the local model of Local
only runs, a default and one per step, saved in the app's database. Claude stays the main engine and is never changed here;
Automatic never picks a local model; a model is offered only when approved, priced, installed and small enough; the Local only
plan names the models with "local model, not yet scored". The local engine's list is faked: no engine is called and no model is
loaded. Invented model names only."""

from __future__ import annotations

import dataclasses
import itertools
import re

import pytest
from fastapi.testclient import TestClient

from app import aim_review_gate, db, model_transport, review_model_setting
from app.aim_review import local_model
from app.config import settings
from app.main import app
from app.review_engine import ON_LOCAL, Facts
from app.review_engine_general import decide_general
from tests.test_aim_dry_run import PAPERS, dry  # noqa: F401 - fixture
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture

SMALL, OTHER, HUGE = "invented-small:14b", "invented-other:9b", "invented-huge:35b"
INSTALLED = {
    "models": [
        {"name": SMALL, "size": 9_000_000_000},
        {"name": OTHER, "size": 6_000_000_000},
        {"name": HUGE, "size": 24_000_000_000},
    ]
}


@pytest.fixture
def engine(monkeypatch):
    """The local engine's own list of installed models; any other call fails the test."""
    asked: list[str] = []

    def get_json(path, *, timeout, required=True):
        asked.append(path)
        assert path == "/api/tags"
        return INSTALLED

    def no_post(*_a, **_k):
        raise AssertionError("the Review model section loaded or called a model")

    monkeypatch.setattr(model_transport, "get_json", get_json)
    monkeypatch.setattr(model_transport, "post_json", no_post)
    return asked


@pytest.fixture
def world(dry):  # the dry-run library and its signed-in admin
    return dry


def _table_exists() -> bool:
    return bool(
        db.connect()
        .execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (review_model_setting.TABLE,),
        )
        .fetchone()
    )


def test_the_options_list_claude_fixed_and_each_installed_local_model_with_why_not(
    engine, world
):
    got = review_model_setting.options()
    assert [m["name"] for m in got["claude"]] == [
        settings.general_review_lead_model,
        settings.general_review_strong_model,
    ]
    assert all(
        not m["selectable"] and m["why"] == review_model_setting.CLAUDE_FIXED
        for m in got["claude"]
    )
    local = {m["name"]: m for m in got["local"]}
    assert local[SMALL]["selectable"] and local[OTHER]["selectable"]
    assert (
        not local[HUGE]["selectable"]
        and local[HUGE]["why"] == review_model_setting.TOO_LARGE
    )
    assert all(
        m["score_words"] == aim_review_gate.LOCAL_NOT_SCORED for m in got["local"]
    )
    assert got["steps"] == list(local_model.STEP_GROUPS)
    assert engine == ["/api/tags"]  # only the list was read


def test_a_local_engine_that_does_not_answer_offers_nothing_and_says_so(
    monkeypatch, world
):
    monkeypatch.setattr(model_transport, "get_json", lambda *a, **k: None)
    got = review_model_setting.options()
    assert got["local"] == [] and got["engine_down"] is True
    with pytest.raises(
        review_model_setting.Refused, match=review_model_setting.ENGINE_DOWN
    ):
        review_model_setting.save({"default": SMALL}, "u1")


def test_a_read_never_creates_the_table_and_nothing_saved_keeps_the_answer_model(
    engine, world
):
    assert review_model_setting.stored()["default"] is None
    assert not _table_exists()
    assert local_model.model_name() == str(settings.answer_model)


@pytest.mark.parametrize(
    "choice, words",
    [
        ({"default": HUGE}, review_model_setting.TOO_LARGE),
        ({"default": "invented-missing:1b"}, review_model_setting.NOT_INSTALLED),
        ({"steps": {"judge": HUGE}}, review_model_setting.TOO_LARGE),
        ({"steps": {"no such step": SMALL}}, review_model_setting.UNKNOWN_STEP),
    ],
)
def test_a_refused_choice_saves_nothing(engine, world, choice, words):
    review_model_setting.save({"default": SMALL}, "u1")
    with pytest.raises(review_model_setting.Refused, match=re.escape(words)):
        review_model_setting.save({"default": OTHER, **choice}, "u1")
    assert (
        review_model_setting.stored()["default"] == SMALL
    )  # the earlier choice stands whole


def test_the_saved_choice_is_what_a_local_run_uses_and_wins_over_the_env_setting(
    engine, world, monkeypatch
):
    monkeypatch.setattr(
        settings,
        "general_review_local_step_models",
        "judge=invented-env:1b, editor=invented-env:1b",
    )
    review_model_setting.save({"default": OTHER, "steps": {"judge": SMALL}}, "u1")
    model = local_model.LocalModel()
    assert model.name == OTHER
    assert model.model_for("aim_judge") == SMALL  # saved wins
    assert (
        model.model_for("aim_edit") == "invented-env:1b"
    )  # a step not saved keeps the env setting
    assert model.model_for("aim_identify") == OTHER
    review_model_setting.save({}, "u1")  # an empty choice clears it
    assert local_model.LocalModel().name == str(settings.answer_model)


def test_the_local_only_plan_names_the_models_with_not_yet_scored_and_claude_plans_do_not(
    engine, world
):
    review_model_setting.save({"default": OTHER, "steps": {"judge": SMALL}}, "u1")
    client = TestClient(app)
    paper = PAPERS["datasheet"][0]

    def notes(choice):
        r = client.get(
            "/api/reviews/plan",
            params={"submittal_document_id": paper, "engine": choice},
            headers=world["headers"],
        )
        assert r.status_code == 200, r.text
        return r.json()["notes"]

    line = (
        f"Review model: {OTHER}; judge: {SMALL} ({aim_review_gate.LOCAL_NOT_SCORED})."
    )
    assert line in notes("local")
    assert all(
        not n.startswith("Review model:")
        for c in ("automatic", "claude")
        for n in notes(c)
    )


def test_automatic_and_claude_never_pick_the_local_model_whatever_the_facts():
    flags = [f.name for f in dataclasses.fields(Facts) if f.type in (bool, "bool")]
    for kind, provider in itertools.product(
        ("datasheet", None), ("claude", "per_task")
    ):
        for values in itertools.product((False, True), repeat=len(flags)):
            facts = Facts(
                kind=kind, provider=provider, **dict(zip(flags, values, strict=True))
            )
            for choice in ("automatic", "claude"):
                parts = decide_general(choice, facts).parts
                assert all(p.engine != ON_LOCAL for p in parts), (choice, facts)


def test_the_routes_admin_reads_and_only_a_signed_in_admin_saves(engine, world):
    client = TestClient(app)
    got = client.get("/api/admin/review-model", headers=world["headers"])
    assert got.status_code == 200 and got.json()["steps"] == list(
        local_model.STEP_GROUPS
    )
    saved = client.put(
        "/api/admin/review-model",
        json={"default": SMALL, "steps": {"judge": OTHER}},
        headers=world["headers"],
    )
    assert saved.status_code == 200, saved.text
    assert (
        saved.json()["stored"]["default"] == SMALL and saved.json()["stored"]["set_by"]
    )
    refused = client.put(
        "/api/admin/review-model", json={"default": HUGE}, headers=world["headers"]
    )
    assert refused.status_code == 422 and review_model_setting.TOO_LARGE in refused.text
    anonymous = client.put("/api/admin/review-model", json={"default": OTHER})
    assert anonymous.status_code in (403, 404)  # no identity never saves
    assert review_model_setting.stored()["default"] == SMALL
