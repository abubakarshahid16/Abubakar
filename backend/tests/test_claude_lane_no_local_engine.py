"""A review on the Claude lane never loads the local engine, and says what it skipped.

The pilot of 2 Nov 2026 stopped at 91% memory: Claude had read and matched, then
"finishing: AI comments and wording" loaded the local 35B. The transport here raises and
records if anything reaches `model_transport`. Fake Claude transport; no socket.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import (
    ai_applicability,
    ai_engineering_check,
    ai_task_runner,
    clause_review,
    comparison,
    crs_wording,
    datasheet_ai,
    db,
    field_naming,
    local_engine_bar,
    model_transport,
    reader_transport,
    review_audit,
    review_audit_rows,
    review_jobs,
    rule_equipment_scope,
)
from app import reasoning_provider as rp
from app.config import settings
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _enqueue,
    temp_storage,
    world,
)

W = "worker-lane"
NOTE = local_engine_bar.NOTE


class _Loaded(AssertionError):
    pass


@pytest.fixture
def engine_calls(monkeypatch):
    """Every public way into the local engine raises and is recorded."""
    calls = []

    def raising(name):
        def fake(path, *a, **k):
            calls.append((name, path))
            raise _Loaded(f"{name} {path}")

        return fake

    for name in ("post_json", "post_json_retrying", "stream_json", "get_json"):
        monkeypatch.setattr(model_transport, name, raising(name))
    monkeypatch.setattr(ai_task_runner, "_IDENTITY_MEMO", {})
    monkeypatch.setattr(ai_task_runner, "_tags_cache", {})
    return calls


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """The lane open: flags, a key, and the ledger and cache in this test's folder."""
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", True)
    monkeypatch.setattr(settings, "clause_review_enabled", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _outcome(run_id):
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    return json.loads(row["outcome_json"])


def _review(world):  # noqa: F811
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    state = review_jobs.run(job_id, W)
    return run_id, state


# ------------------------------------------------------------- the whole review


@pytest.mark.parametrize("provider", ["per_task", "claude"])
def test_a_claude_lane_review_never_reaches_the_local_engine(
    world,  # noqa: F811
    lane,
    engine_calls,
    provider,
):
    lane.setattr(settings, "reasoning_provider", provider)
    fake_claude = _claude_answers()
    lane.setattr(reader_transport, "transport", lambda: fake_claude)
    _run_id, state = _review(world)
    assert state == "done"
    assert engine_calls == [], (
        "the local engine was reached during a Claude-lane review"
    )


def test_a_per_task_review_states_every_step_it_skipped(world, lane, engine_calls):  # noqa: F811
    run_id, state = _review(world)
    assert state == "done" and engine_calls == []
    skipped = {r["step"]: r for r in _outcome(run_id)[local_engine_bar.OUTCOME_KEY]}
    assert "review_ai_check" in skipped and "crs_wording" in skipped
    assert all(r["note"] == NOTE for r in skipped.values())


def test_the_audit_lists_the_skipped_steps(world, lane, engine_calls):  # noqa: F811
    run_id, _state = _review(world)
    run = dict(
        db.connect()
        .execute("SELECT * FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    steps = review_audit_rows.skipped_steps(json.loads(run["outcome_json"]))
    assert {
        "name": "crs_wording",
        "state": NOTE,
        "model": None,
        "calls": 0,
        "fresh": 0,
        "failed": 0,
        "reused": 0,
    } in steps
    audit = {
        "ai_use": {
            "steps": steps,
            "totals": {"fresh": 0, "failed": 0, "reused": 0, "boundary": "b"},
        }
    }
    assert any(f"crs_wording: {NOTE}" in line for line in review_audit._md_ai(audit))


def test_wording_runs_on_claude_when_its_own_engine_says_so_and_cost_is_on_the_ledger(
    world,  # noqa: F811
    lane,
    engine_calls,
):
    lane.setattr(settings, "crs_ai_wording_engine", "claude")
    fake_claude = _claude_answers()
    lane.setattr(reader_transport, "transport", lambda: fake_claude)
    run_id, state = _review(world)
    assert state == "done" and engine_calls == []
    assert fake_claude.models == {settings.claude_labelling_model}, (
        "the wording did not ask Haiku"
    )
    skipped = {
        r["step"] for r in _outcome(run_id).get(local_engine_bar.OUTCOME_KEY, [])
    }
    assert "crs_wording" not in skipped


def _claude_answers():
    def send(url, *, headers, body, timeout):
        send.models.add(body["model"])
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": '{"comment": "Noise level exceeds the limit."}',
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    send.models = set()
    send.usage = {}
    return send


# ------------------------------------------------------------ ollama is untouched


def test_with_the_provider_on_ollama_the_bar_never_rises(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    assert not local_engine_bar.is_claude_lane_run()
    seen = []
    monkeypatch.setattr(
        local_engine_bar, "stated", lambda: seen.append(local_engine_bar.active()) or []
    )
    run_id, state = _review(world)
    assert state == "done" and seen == [False]
    assert local_engine_bar.OUTCOME_KEY not in _outcome(run_id)


def test_a_closed_lane_is_not_a_claude_lane_run(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "standards_reader_enabled", False)
    monkeypatch.delenv("STANDARDS_READER_ENABLED", raising=False)
    assert not local_engine_bar.is_claude_lane_run()


def test_outside_a_review_the_local_engine_stays_open(lane):
    """A chat answer on the Local model, on another thread, is not a review."""
    assert not local_engine_bar.active()
    assert model_transport.endpoint("/api/generate").endswith("/api/generate")


# ------------------------------------------------------------- each step, by itself


def test_the_gate_holds_where_a_step_forgot_and_looks_like_a_stopped_engine():
    with local_engine_bar.bar():
        with pytest.raises(httpx.ConnectError) as caught:
            model_transport.endpoint("/api/generate")
        assert isinstance(caught.value, model_transport.LocalEngineNotLoaded)
        assert local_engine_bar.stated()[0]["step"] == "local engine /api/generate"


def test_the_local_provider_refuses_and_names_the_step(engine_calls):
    packet = rp.Packet(prompt="p", num_ctx=1, num_predict=1, step="b4-naming2")
    with local_engine_bar.bar():
        with pytest.raises(rp.ProviderRefused, match=NOTE):
            rp.OllamaProvider().reason(packet)
        with pytest.raises(rp.ProviderRefused, match=NOTE):
            rp.OllamaProvider().stream(packet, lambda piece: None)
        assert local_engine_bar.stated() == [
            {"step": "b4-naming2", "calls_not_made": 2, "note": NOTE}
        ]
    assert engine_calls == []


def test_the_matcher_on_the_local_engine_is_skipped(engine_calls, monkeypatch):
    monkeypatch.setattr(settings, "match_engine", "ollama")
    with local_engine_bar.bar():
        got = comparison._ask_model_once(
            {"requirement_text": "x"}, [{"field_name": "y"}]
        )
        assert got == (None, comparison.MODEL_UNAVAILABLE)
        assert local_engine_bar.stated()[0]["step"] == comparison.MATCH_STEP
    assert engine_calls == []


def test_rule_equipment_scope_is_skipped(engine_calls):
    with local_engine_bar.bar():
        assert rule_equipment_scope.ask_local_model({"requirement_text": "x"}) is None
        assert local_engine_bar.stated()[0]["step"] == "rule_equipment_scope"
    assert engine_calls == []


def test_a_task_is_skipped_with_the_note_as_its_reason(engine_calls):
    spec = ai_applicability.TASK
    with local_engine_bar.bar():
        result = ai_task_runner.run_task(spec, "some text")
        assert (
            result.state == ai_task_runner.STATE_COULD_NOT_READ
            and result.reason == NOTE
        )
        assert ai_task_runner.model_identity("any-model") is None
        assert ai_task_runner._installed_tags() is None
    assert engine_calls == []


def test_a_barred_probe_is_not_remembered_as_the_engines_answer(engine_calls):
    with local_engine_bar.bar():
        ai_task_runner.model_identity("any-model")
    assert "any-model" not in ai_task_runner._IDENTITY_MEMO


def test_the_datasheet_reader_on_the_local_engine_is_skipped(engine_calls):
    with local_engine_bar.bar():
        call, why = datasheet_ai.model_call_for("ollama")
        assert call is None and "LocalEngineNotLoaded" in why
        assert local_engine_bar.stated()[0]["note"] == NOTE
    assert engine_calls == []


def test_field_naming_on_the_local_engine_is_stated(engine_calls, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    with local_engine_bar.bar():
        provider = rp.get_provider("labelling", step=field_naming.NAMING_STEP)
        with pytest.raises(rp.ProviderRefused, match=NOTE):
            provider.reason(
                rp.Packet(
                    prompt="p", num_ctx=1, num_predict=1, step=field_naming.NAMING_STEP
                )
            )
    assert engine_calls == []


def test_a_failed_cloud_wording_call_does_not_fall_back_to_the_local_engine(lane):
    provider = rp.ClaudeProvider("claude-haiku-5-5", transport=lambda *a, **k: {})
    assert (
        crs_wording._local_after_a_failed_cloud_call(provider, RuntimeError("x"))
        is not None
    )
    with local_engine_bar.bar():
        assert (
            crs_wording._local_after_a_failed_cloud_call(provider, RuntimeError("x"))
            is None
        )


def test_the_engineering_check_never_falls_back_to_the_local_engine(
    world,  # noqa: F811
    lane,
    engine_calls,
):
    """#870's fallback, under the bar: the cloud call failed, and the run says so."""
    lane.setattr(settings, "review_ai_check_engine", "claude")

    def fails(url, *, headers, body, timeout):
        raise httpx.ReadTimeout("late")

    lane.setattr(reader_transport, "transport", lambda: fails)
    run_id, _job = _enqueue(world)
    with local_engine_bar.bar():
        result = ai_engineering_check.run_check(
            run_id, allowed_document_ids=world["scope"], cited=[]
        )
        assert result.get("reason") != NOTE
    assert engine_calls == []


def test_the_clause_review_is_local_only_so_it_is_skipped_and_says_so(
    world,  # noqa: F811
    lane,
    engine_calls,
):
    run_id, _job = _enqueue(world)
    with local_engine_bar.bar():
        clause_review.for_review(run_id, world["scope"])
        assert local_engine_bar.stated()[0]["step"] == clause_review.STEP
    row = (
        db.connect()
        .execute("SELECT ai_check_status FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert NOTE in json.loads(row["ai_check_status"])[clause_review.STATUS_KEY]["plain"]
    assert engine_calls == []


def test_deleting_a_document_removes_the_stored_answers_that_quote_it(world, lane):  # noqa: F811
    from app import claude_answer_cache, claude_approved, claude_spend, document_refs

    def send(url, *, headers, body, timeout):
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "usage": {},
            "content": [{"type": "text", "text": '{"a": 1}'}],
        }

    body = {"model": "m", "messages": []}
    with claude_approved.carrying([world["sub"]]):
        claude_spend.metered(send, "s")("https://x", headers={}, body=body, timeout=1)
    assert list(claude_answer_cache._root().rglob("*.json"))
    with db.connect() as conn:
        document_refs.forget_quotes(conn, world["sub"])
    assert not list(claude_answer_cache._root().rglob("*.json"))
