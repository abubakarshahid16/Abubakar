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
REMOTE = "invented-remote:cloud"
STUB = "invented-stub:9b"  # a remote entry with an ordinary name: only its list entry shows it is not a file here
INSTALLED = {
    "models": [
        {"name": SMALL, "size": 9_000_000_000, "digest": "invented-1"},
        {"name": OTHER, "size": 6_000_000_000, "digest": "invented-2"},
        {"name": HUGE, "size": 24_000_000_000, "digest": "invented-3"},
        # a remote stub as the engine lists one: a few hundred bytes and a remote host
        {
            "name": REMOTE,
            "size": 380,
            "digest": "invented-4",
            "remote_host": "https://invented.example",
            "remote_model": "x",
        },
        {
            "name": STUB,
            "size": 412,
            "digest": "invented-5",
            "remote_host": "https://invented.example",
        },
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


def test_the_default_is_marked_and_the_14b_says_it_did_not_finish_a_valve_review(
    monkeypatch, world
):
    monkeypatch.setattr(
        model_transport,
        "get_json",
        lambda *a, **k: {
            "models": [
                {"name": "qwen3.5:9b-q4_K_M", "size": 6_500_000_000, "digest": "d1"},
                {"name": "ministral-3:14b", "size": 9_000_000_000, "digest": "d2"},
            ]
        },
    )
    monkeypatch.setattr(settings, "answer_model", "qwen3.5:9b-q4_K_M")
    rows = {m["name"]: m for m in review_model_setting.options()["local"]}
    assert (
        rows["qwen3.5:9b-q4_K_M"]["is_default"] is True
        and rows["qwen3.5:9b-q4_K_M"]["measured"]
        == aim_review_gate.LOCAL_TEST_NOTE  # its own numbers (M4)
    )
    assert rows["ministral-3:14b"]["is_default"] is False
    assert rows["ministral-3:14b"]["measured"] == aim_review_gate.LOCAL_14B_NOTE
    assert (
        "did not finish a valve review on this Mac"
        in rows["ministral-3:14b"]["measured"]
    )
    assert (
        rows["ministral-3:14b"]["selectable"] is True
    )  # still offered: its contract review finished


# --- review of update 10, M3: a model that is not a file on this computer is never offered, saved or started


def test_a_remote_entry_or_a_cloud_name_is_never_offered_or_saved(engine, world):
    rows = {m["name"]: m for m in review_model_setting.options()["local"]}
    assert rows[REMOTE]["selectable"] is False
    assert rows[REMOTE]["why"] == review_model_setting.NOT_LOCAL_FILE
    assert (
        rows[STUB]["selectable"] is False
        and rows[STUB]["why"] == review_model_setting.NOT_LOCAL_FILE
    )
    for name in (REMOTE, STUB, "invented-other-cloud:1b", "invented:cloud"):
        with pytest.raises(
            review_model_setting.Refused,
            match=re.escape(review_model_setting.NOT_LOCAL_FILE),
        ):
            review_model_setting.save({"steps": {"judge": name}}, "u1")
    assert review_model_setting.stored()["steps"] == {}


@pytest.mark.parametrize(
    "entry",
    [
        {"size": 380, "digest": "d", "remote_host": "https://invented.example"},
        {"size": 380, "digest": "d", "remote_model": "invented"},
        {"size": 0, "digest": "d"},
        {"size": 6_000_000_000},  # no digest: no local file proven
    ],
)
def test_a_run_never_starts_on_a_model_that_is_not_a_local_file(monkeypatch, entry):
    name = "invented-model:9b"
    tags = {"models": [{"name": name, **entry}]}
    monkeypatch.setattr(
        model_transport,
        "get_json",
        lambda path, *, timeout, required=True: (
            tags if path == "/api/tags" else {"models": []}
        ),
    )
    assert local_model.readiness([name]) == local_model.NOT_LOCAL.format(name=name)


def test_a_cloud_name_never_starts_even_when_the_engine_does_not_list_it(monkeypatch):
    monkeypatch.setattr(model_transport, "get_json", lambda *a, **k: {"models": []})
    for name in ("invented:cloud", "invented-model-cloud:1b"):
        assert local_model.readiness([name]) == local_model.NOT_LOCAL.format(name=name)


# --- M4: a model's measured numbers are shown only for that model


@pytest.mark.parametrize(
    "models, note",
    [
        (["qwen3.5:9b-q4_K_M"], aim_review_gate.LOCAL_TEST_NOTE),
        (["ministral-3:14b"], aim_review_gate.LOCAL_14B_NOTE),
        (["invented-other:9b"], "Local model (invented-other:9b): not yet scored."),
        (
            ["qwen3.5:9b-q4_K_M", "ministral-3:14b"],
            "Local model (ministral-3:14b, qwen3.5:9b-q4_K_M): not yet scored.",
        ),
        ([], "Local model (its name was not recorded): not yet scored."),
    ],
)
def test_the_measured_note_is_the_models_own_or_not_yet_scored(models, note):
    assert aim_review_gate.local_measured_note(models) == note


def test_a_plan_on_another_saved_model_shows_no_numbers(engine, world):
    review_model_setting.save({"default": OTHER}, "u1")
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={"submittal_document_id": PAPERS["datasheet"][0], "engine": "local"},
        headers=world["headers"],
    )
    notes = r.json()["notes"]
    assert f"Local model ({OTHER}): {aim_review_gate.NOT_YET_SCORED}." in notes
    assert aim_review_gate.LOCAL_TEST_NOTE not in notes
    assert not any("of 10" in n for n in notes if n.startswith("Local model"))


def test_the_plan_line_names_a_step_set_only_in_env(engine, world, monkeypatch):
    monkeypatch.setattr(settings, "general_review_local_step_models", f"judge={SMALL}")
    line = review_model_setting.plan_line(OTHER, local_model.step_models())
    assert (
        line
        == f"Review model: {OTHER}; judge: {SMALL} ({aim_review_gate.LOCAL_NOT_SCORED})."
    )


# --- review of update 10, N6: the tables are made at app start, and every change is kept


def test_the_app_start_makes_both_tables_and_a_read_still_never_does(world):
    import inspect

    from app import main

    assert "review_model_setting_mod.ensure_schema()" in inspect.getsource(
        main.lifespan
    )
    assert not _table_exists()  # the test library was made without the start-up
    review_model_setting.ensure_schema()
    names = {
        r[0]
        for r in db.connect()
        .execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        .fetchall()
    }
    assert {review_model_setting.TABLE, review_model_setting.HISTORY} <= names


def test_every_change_is_kept_with_who_when_old_and_new_and_nothing_else(engine, world):
    review_model_setting.save({"default": SMALL}, "u1")
    review_model_setting.save({"default": OTHER, "steps": {"judge": SMALL}}, "u2")
    review_model_setting.save(
        {"default": OTHER, "steps": {"judge": SMALL}}, "u3"
    )  # no change: nothing kept
    review_model_setting.save({"default": OTHER}, "u4")  # judge cleared
    got = [
        (h["slot"], h["old_model"], h["new_model"], h["changed_by"])
        for h in review_model_setting.history()
    ]
    assert got == [
        ("judge", SMALL, None, "u4"),
        ("judge", None, SMALL, "u2"),
        ("default", SMALL, OTHER, "u2"),
        ("default", None, SMALL, "u1"),
    ]
    assert all(h["changed_at"] for h in review_model_setting.history())


def test_a_refused_save_keeps_no_change(engine, world):
    review_model_setting.save({"default": SMALL}, "u1")
    with pytest.raises(review_model_setting.Refused):
        review_model_setting.save({"default": HUGE}, "u2")
    assert [h["changed_by"] for h in review_model_setting.history()] == ["u1"]


def test_the_section_is_given_the_latest_changes_newest_first(engine, world):
    for i in range(review_model_setting.HISTORY_SHOWN + 2):
        review_model_setting.save({"default": SMALL if i % 2 else OTHER}, f"u{i}")
    got = (
        TestClient(app)
        .get("/api/admin/review-model", headers=world["headers"])
        .json()["history"]
    )
    assert len(got) == review_model_setting.HISTORY_SHOWN
    assert got[0]["changed_by"] == f"u{review_model_setting.HISTORY_SHOWN + 1}"


# --- lead-4, 26 Nov 2026: the score label and the measured note come from one per-model source


@pytest.mark.parametrize(
    "models",
    [
        ["qwen3.5:9b-q4_K_M"],
        ["ministral-3:14b"],
        ["invented-other:9b"],
        ["qwen3.5:9b-q4_K_M", "ministral-3:14b"],
        [],
    ],
)
def test_the_label_never_says_not_yet_scored_beside_a_measured_score(models):
    label = aim_review_gate.local_score_words(models)
    note = aim_review_gate.local_measured_note(models)
    has_score = "of 10" in note
    assert (label == aim_review_gate.LOCAL_MEASURED_WORDS) is has_score
    assert (aim_review_gate.NOT_YET_SCORED in label) is not has_score


def test_the_local_only_plan_on_the_9b_says_measured_and_never_not_yet_scored(
    engine, world, monkeypatch
):
    nine = "qwen3.5:9b-q4_K_M"
    monkeypatch.setattr(
        model_transport,
        "get_json",
        lambda *a, **k: {
            "models": [{"name": nine, "size": 6_500_000_000, "digest": "d"}]
        },
    )
    review_model_setting.save({"default": nine}, "u1")
    notes = (
        TestClient(app)
        .get(
            "/api/reviews/plan",
            params={"submittal_document_id": PAPERS["datasheet"][0], "engine": "local"},
            headers=world["headers"],
        )
        .json()["notes"]
    )
    assert f"Review model: {nine} ({aim_review_gate.LOCAL_MEASURED_WORDS})." in notes
    assert aim_review_gate.LOCAL_TEST_NOTE in notes
    assert not any(aim_review_gate.NOT_YET_SCORED in n for n in notes)
    row = next(m for m in review_model_setting.options()["local"] if m["name"] == nine)
    assert row["score_words"] == aim_review_gate.LOCAL_MEASURED_WORDS
