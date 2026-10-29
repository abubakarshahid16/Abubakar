"""Order 309.2: a review run records its model, its settings and the cached answers it used (invented data)."""

from __future__ import annotations

import json

from app import (
    ai_task_runner,
    db,
    ingest,
    job_queue,
    model_metrics,
    model_transport,
    review_jobs,
    run_settings,
)
from app.config import settings
from app.reasoning_provider import OllamaProvider, Packet
from tests import test_p3_review_jobs as p3

world, temp_storage = p3.world, p3.temp_storage  # the review-job fixtures
PACKET = Packet(prompt="SECRET PROMPT TEXT", num_ctx=1024, num_predict=16)


def _drain_with(monkeypatch, run_id, job_id, body):
    def run(job, worker, heartbeat=None):
        body()
        raise RuntimeError("the review failed")

    monkeypatch.setattr(review_jobs, "recover_stale", lambda: None)
    monkeypatch.setattr(review_jobs, "claim_next", lambda worker: job_id)
    monkeypatch.setattr(review_jobs, "run", run)
    monkeypatch.setattr(job_queue, "worker_id", lambda: p3.W)
    ingest.IngestionWorker()._drain_review_jobs()
    return p3._run_row(run_id)


def test_the_run_names_the_models_that_answered_with_their_call_counts(
    world, monkeypatch
):
    run_id, job_id = p3._enqueue(world)
    monkeypatch.setattr(
        model_transport, "post_json", lambda path, body, timeout: {"response": "{}"}
    )

    def body():
        OllamaProvider("model-b", timeout=5).reason(PACKET)
        OllamaProvider("model-a", timeout=5).reason(PACKET)
        OllamaProvider("model-a", timeout=5).reason(PACKET)

    row = _drain_with(monkeypatch, run_id, job_id, body)
    assert row["model_name"] == "model-a (2), model-b (1)"


def test_a_run_that_made_no_model_call_keeps_no_model_name_instead_of_a_guess(
    world, monkeypatch
):
    run_id, job_id = p3._enqueue(world)
    assert _drain_with(monkeypatch, run_id, job_id, lambda: None)["model_name"] is None


def test_the_settings_are_stored_with_the_run_and_a_later_change_does_not_alter_them(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "ai_task_model", "model-one")
    first, _ = p3._enqueue(world)
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'failed' WHERE id = ?", (first,))
    monkeypatch.setattr(settings, "ai_task_model", "model-two")
    second, _ = p3._enqueue(world)
    assert run_settings.for_run(first)["ai_task_model"] == "model-one"
    assert run_settings.for_run(second)["ai_task_model"] == "model-two"
    assert run_settings.for_run("no-such-run") == {}


def test_a_text_value_named_like_a_secret_or_an_address_is_never_stored(monkeypatch):
    monkeypatch.setattr(
        run_settings,
        "ANSWER_AFFECTING_SETTINGS",
        ("answer_model", "ollama_url", "data_dir", "db_path"),
    )
    monkeypatch.setattr(run_settings, "REVIEW_SWITCHES", ())
    stored, left_out = run_settings.snapshot()
    assert set(stored) == {"answer_model"} and left_out == 3


def test_a_number_is_stored_even_when_its_name_says_tokens_and_the_list_states_its_boundary(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "max_output_tokens", 1234)
    monkeypatch.setattr(
        run_settings,
        "ANSWER_AFFECTING_SETTINGS",
        ("max_output_tokens", "answer_model", "ollama_url"),
    )
    monkeypatch.setattr(run_settings, "REVIEW_SWITCHES", ())
    run_id, _job = p3._enqueue(world)
    got = run_settings.for_run(run_id)
    assert got["max_output_tokens"] == "1234"
    assert "ollama_url" not in got
    assert got[run_settings.NOT_STORED].startswith("1 of 3")


def _fake_cache(monkeypatch):
    monkeypatch.setattr(
        ai_task_runner, "model_identity", lambda requested: "tag@digest|ollama/1"
    )
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)


def test_the_run_records_which_cached_answers_it_reused_and_which_it_made(
    world, monkeypatch
):
    _fake_cache(monkeypatch)
    run_id, job_id = p3._enqueue(world)
    asked = []

    def body():
        for prompt in ("first question", "second question"):
            ai_task_runner.reuse_or_ask(
                "task-x",
                "v1",
                "model-a",
                None,
                prompt,
                ask=lambda: (asked.append(1), "SECRET ANSWER")[1],
            )

    # the first run answers both fresh and keeps them; a second run of the same prompts reuses them
    _drain_with(monkeypatch, run_id, job_id, body)
    [row] = model_metrics.cache_uses_for_run(run_id)
    assert (row["task"], row["model"], row["answers"]) == (
        "task-x",
        "tag@digest|ollama/1",
        2,
    )
    assert (row["reused"], row["fresh"]) == (
        0,
        2,
    )  # both prompts were new

    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'failed' WHERE id = ?", (run_id,))
        conn.execute("UPDATE jobs SET state = 'failed' WHERE id = ?", (job_id,))
    run2, job2 = p3._enqueue(world)
    _drain_with(monkeypatch, run2, job2, body)
    [again] = model_metrics.cache_uses_for_run(run2)
    assert (again["reused"], again["fresh"]) == (2, 0)
    text = json.dumps(
        [dict(r) for r in db.connect().execute("SELECT * FROM review_run_cache_uses")]
    )
    assert "SECRET" not in text and "question" not in text  # key, task and model only


def test_outside_a_review_nothing_is_recorded_and_the_answer_is_still_cached(
    monkeypatch, world
):
    _fake_cache(monkeypatch)
    got = ai_task_runner.reuse_or_ask(
        "task-x", "v1", "model-a", None, "q", ask=lambda: "A"
    )
    assert got == "A"
    model_metrics.ensure_schema()
    assert (
        db.connect().execute("SELECT COUNT(*) FROM review_run_cache_uses").fetchone()[0]
        == 0
    )


def test_the_switches_that_decide_a_review_are_recorded_though_the_hash_ignores_them(
    world, monkeypatch
):
    from app.config import ANSWER_AFFECTING_SETTINGS, Settings

    assert all(name in Settings.model_fields for name in run_settings.REVIEW_SWITCHES)
    assert not set(run_settings.REVIEW_SWITCHES) & set(ANSWER_AFFECTING_SETTINGS)
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", True)
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    on, _ = p3._enqueue(world)
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'failed' WHERE id = ?", (on,))
    monkeypatch.setattr(settings, "tested_cards_decide_enabled", False)
    off, _ = p3._enqueue(world)
    assert run_settings.for_run(on)["tested_cards_decide_enabled"] == "True"
    assert run_settings.for_run(off)["tested_cards_decide_enabled"] == "False"
