"""Order 163.3 item F: a timed-out local call is retried once, and an unchanged
local AI answer is reused.

No network and no model: `model_transport.post_json` is replaced by a fake that
times out or answers, and the model's identity (tag + digest) by a fixed value.
Made-up text only.

What is proved:
  * RETRY: one timeout is tried again (1 retry counted) and the sheet is read;
    a second timeout fails as before (2 calls, never more); a refusal or an
    HTTP error is not retried; the pair-choice call retries the same way.
  * CACHE: an unchanged call posts nothing the second time; a changed prompt
    version, model identity, page text or option each skip it; an engine whose
    identity cannot be told is never cached; a reused answer goes through the
    same code gate (a quote not on the page is still rejected).

Mutations: M1221-01..06 (`scripts/mutations/model_transport.py`).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import ai_task_runner, comparison, datasheet_ai, db, model_transport
from app.config import settings

PAGE = "Design pressure 23.5 barg\nDesign temperature 120 C"
GOOD = {
    "field": "Design pressure",
    "value": "23.5",
    "unit": "barg",
    "quote": "Design pressure 23.5 barg",
    "kind": "offered",
}
NOT_ON_PAGE = {
    "field": "Paint system",
    "value": "Three coat zinc",
    "unit": None,
    "quote": "Paint system Three coat zinc",
    "kind": "offered",
}
IDENTITY = "local-0001@sha256:aaaa"
#: The real function, captured before the suite-wide fixture stubs it out.
_REAL_IDENTITY = ai_task_runner.model_identity


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "f163.sqlite")
    monkeypatch.setattr(settings, "datasheet_ai_ollama_model", "local-0001")
    monkeypatch.setattr(settings, "answer_model", "local-0001")
    db.reset_connection()
    db.init_db()
    model_transport.reset_timeout_retries()
    slept: list[float] = []
    monkeypatch.setattr(model_transport.time, "sleep", slept.append)
    yield slept
    db.reset_connection()


def _reply(facts):
    return {
        "response": json.dumps({"facts": facts}),
        "model": "local-0001",
        "done_reason": "stop",
    }


class Engine:
    """A fake `post_json`: replies are consumed in order; an exception is raised."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, path, body, *, timeout):
        self.calls += 1
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _read(page=PAGE):
    return datasheet_ai.read_page_text_with_ai(page, 1, "ollama")


# ------------------------------------------------------------------- RETRY


def test_a_forced_timeout_retries_once_and_passes(monkeypatch, temp_storage):
    engine = Engine(httpx.ReadTimeout("slow"), _reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    got = model_transport.post_json_retrying(
        "/api/generate", {"model": "m"}, timeout=1.0
    )
    assert got["model"] == "local-0001"
    assert engine.calls == 2 and model_transport.timeout_retries() == 1
    assert temp_storage == [model_transport.TIMEOUT_RETRY_BACKOFF_S]


def test_a_timed_out_page_read_is_retried_and_the_sheet_is_read(monkeypatch):
    # the first call of the page times out; every later call answers
    engine = Engine(httpx.ReadTimeout("slow"), _reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    out = _read()
    assert len(out["accepted"]) == 1 and not out.get("error")
    assert model_transport.timeout_retries() == 1


def test_a_second_timeout_still_fails_as_today_with_no_endless_retry(monkeypatch):
    engine = Engine(httpx.ReadTimeout("slow"))
    monkeypatch.setattr(model_transport, "post_json", engine)
    with pytest.raises(httpx.ReadTimeout):
        model_transport.post_json_retrying("/api/generate", {"model": "m"}, timeout=1.0)
    assert engine.calls == 2 and model_transport.timeout_retries() == 1


def test_a_page_whose_every_call_times_out_is_not_read_and_says_timed_out(monkeypatch):
    engine = Engine(httpx.ReadTimeout("slow"))
    monkeypatch.setattr(model_transport, "post_json", engine)
    out = _read()
    assert out["accepted"] == [] and out.get("error")
    assert datasheet_ai.TIMED_OUT.split("{")[0] in out["error"]
    assert engine.calls == 2


def test_a_provider_that_did_not_ask_for_a_retry_is_not_given_one(monkeypatch):
    """The review AI check decided a timed-out page is not asked again; the
    provider's default keeps that."""
    from app.reasoning_provider import OllamaProvider, Packet, ProviderRefused

    engine = Engine(httpx.ReadTimeout("slow"), _reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    with pytest.raises(ProviderRefused):
        OllamaProvider("local-0001").reason(
            Packet(prompt="q", num_ctx=2048, num_predict=10)
        )
    assert engine.calls == 1 and model_transport.timeout_retries() == 0


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        ValueError("bad body"),
        httpx.HTTPStatusError(
            "500",
            request=httpx.Request("POST", "http://x"),
            response=httpx.Response(500),
        ),
    ],
)
def test_only_a_timeout_is_retried(monkeypatch, failure):
    engine = Engine(failure, _reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    with pytest.raises(type(failure)):
        model_transport.post_json_retrying("/api/generate", {"model": "m"}, timeout=1.0)
    assert engine.calls == 1 and model_transport.timeout_retries() == 0


def test_the_pair_choice_call_retries_a_timeout_once(monkeypatch):
    answer = {
        "response": json.dumps({"choice": 0, "reason": "same quantity"}),
        "model": "local-0001",
    }
    engine = Engine(httpx.ReadTimeout("slow"), answer)
    monkeypatch.setattr(model_transport, "post_json", engine)
    got, why = comparison._ask_model_once(
        {"requirement_text": "pressure shall be 23 barg", "id": "r"},
        [{"field_name": "Design pressure", "id": "f"}],
    )
    assert why is None and got.choice == 0
    assert engine.calls == 2 and model_transport.timeout_retries() == 1


# ------------------------------------------------------------------- CACHE


@pytest.fixture
def known_model(monkeypatch):
    """The engine reports a fixed identity, so the cache is on."""
    identity = {"now": IDENTITY}
    monkeypatch.setattr(
        ai_task_runner, "model_identity", lambda requested: identity["now"]
    )
    return identity


def test_an_unchanged_page_read_uses_the_stored_answer(monkeypatch, known_model):
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    first = _read()
    assert engine.calls == 2  # the reader's two runs
    second = _read()
    assert engine.calls == 2  # nothing new was asked
    assert second["accepted"] == first["accepted"] and len(second["accepted"]) == 1


def test_a_changed_prompt_version_skips_the_cache(monkeypatch, known_model):
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    _read()
    monkeypatch.setattr(
        datasheet_ai, "PROMPT_VERSION", datasheet_ai.PROMPT_VERSION + "-next"
    )
    _read()
    assert engine.calls == 4


def test_a_changed_model_identity_skips_the_cache(monkeypatch, known_model):
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    _read()
    known_model["now"] = "local-0001@sha256:bbbb"  # same tag, re-pulled
    _read()
    assert engine.calls == 4


def test_a_changed_page_skips_the_cache(monkeypatch, known_model):
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    _read()
    _read(PAGE + "\nPaint system Two coat epoxy")
    assert engine.calls == 4


def test_an_engine_whose_identity_is_unknown_is_never_cached(monkeypatch, known_model):
    known_model["now"] = None
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    _read()
    _read()
    assert engine.calls == 4


def test_a_reused_answer_still_meets_the_quote_gate(monkeypatch, known_model):
    engine = Engine(_reply([NOT_ON_PAGE]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    first = _read()
    second = _read()
    assert engine.calls == 2
    assert first["accepted"] == [] and second["accepted"] == []
    assert second["rejected"] == first["rejected"] and second["rejected"]


def test_the_second_run_of_a_stability_check_is_its_own_stored_answer(
    monkeypatch, known_model
):
    """Two runs of one prompt that DISAGREE stay disagreeing when reused: the
    second run is stored apart from the first, not replaced by a copy of it."""
    engine = Engine(_reply([GOOD]), _reply([]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    first = _read()
    second = _read()
    assert engine.calls == 2
    assert second["accepted"] == first["accepted"]
    assert second["counts"] == first["counts"]


def test_an_unchanged_pair_choice_uses_the_stored_answer(monkeypatch, known_model):
    answer = {
        "response": json.dumps({"choice": 0, "reason": "same quantity"}),
        "model": "local-0001",
    }
    engine = Engine(answer)
    monkeypatch.setattr(model_transport, "post_json", engine)
    requirement = {"requirement_text": "pressure shall be 23 barg", "id": "r"}
    candidates = [{"field_name": "Design pressure", "id": "f"}]
    first = comparison._ask_model_once(requirement, candidates)
    second = comparison._ask_model_once(requirement, candidates)
    assert engine.calls == 1
    assert first[0].choice == second[0].choice == 0


def test_a_changed_match_prompt_version_or_option_skips_the_cache(
    monkeypatch, known_model
):
    answer = {
        "response": json.dumps({"choice": 0, "reason": "same quantity"}),
        "model": "local-0001",
    }
    engine = Engine(answer)
    monkeypatch.setattr(model_transport, "post_json", engine)
    requirement = {"requirement_text": "pressure shall be 23 barg", "id": "r"}
    candidates = [{"field_name": "Design pressure", "id": "f"}]
    comparison._ask_model_once(requirement, candidates)
    monkeypatch.setattr(comparison, "MATCH_PROMPT_VERSION", "match-pair-choice-next")
    comparison._ask_model_once(requirement, candidates)
    assert engine.calls == 2
    monkeypatch.setattr(settings, "match_seed", settings.match_seed + 1)
    comparison._ask_model_once(requirement, candidates)
    assert engine.calls == 3
    known_model["now"] = "local-0001@sha256:bbbb"
    comparison._ask_model_once(requirement, candidates)
    assert engine.calls == 4


def test_a_pair_choice_that_fails_the_code_check_is_not_stored(
    monkeypatch, known_model
):
    bad = {"response": json.dumps({"choice": 7, "reason": "x"}), "model": "local-0001"}
    engine = Engine(bad)
    monkeypatch.setattr(model_transport, "post_json", engine)
    requirement = {"requirement_text": "pressure shall be 23 barg", "id": "r"}
    candidates = [{"field_name": "Design pressure", "id": "f"}]
    assert (
        comparison._ask_model_once(requirement, candidates)[1]
        == comparison.MODEL_OUT_OF_RANGE
    )
    assert (
        comparison._ask_model_once(requirement, candidates)[1]
        == comparison.MODEL_OUT_OF_RANGE
    )
    assert engine.calls == 2


def _engine_probe(monkeypatch, *, version="0.40.6", digest="abc", tags_ok=True):
    """The engine's two read-only probes: `/api/tags` (model + digest) and
    `/api/version`. `seen` counts the probes; `state` changes between reads."""
    state = {"version": version, "digest": digest, "n": 0}

    def get_json(path, *, timeout, required=True):
        state["n"] += 1
        if path == "/api/version":
            return {"version": state["version"]} if state["version"] else None
        return {
            "models": [
                {"name": "local-0001:latest", "digest": state["digest"]},
                {"name": "other", "digest": "zzz"},
            ]
        }

    monkeypatch.setattr(model_transport, "get_json", get_json)
    ai_task_runner._IDENTITY_MEMO.clear()
    return state


def test_a_model_identity_is_the_tag_digest_and_engine_version_the_engine_reports(
    monkeypatch,
):
    state = _engine_probe(monkeypatch)
    want = "local-0001:latest@abc|ollama/0.40.6"
    assert _REAL_IDENTITY("local-0001") == want
    probes = state["n"]
    assert _REAL_IDENTITY("local-0001") == want and state["n"] == probes  # memoised
    assert _REAL_IDENTITY("not-pulled") is None


def test_an_engine_that_will_not_say_its_version_has_no_identity(monkeypatch):
    _engine_probe(monkeypatch, version="")
    assert _REAL_IDENTITY("local-0001") is None


def test_a_new_engine_version_never_reuses_an_old_answer(monkeypatch):
    """Order 205: the engine's version is part of the key. Same page, same model
    digest, a different Ollama: asked again."""
    state = _engine_probe(monkeypatch, version="0.40.6")
    monkeypatch.setattr(ai_task_runner, "model_identity", _REAL_IDENTITY)
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    _read()
    assert engine.calls == 2
    _read()
    assert engine.calls == 2  # same engine: reused
    state["version"] = "0.41.0"
    ai_task_runner._IDENTITY_MEMO.clear()
    _read()
    assert engine.calls == 4  # new engine: asked again


def test_an_unreachable_engine_has_no_identity(monkeypatch):
    def down(path, *, timeout, required=True):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(model_transport, "get_json", down)
    ai_task_runner._IDENTITY_MEMO.clear()
    assert _REAL_IDENTITY("local-0001") is None


# ------------------------------------------------ the switch (order 205)


def test_with_reuse_off_every_page_is_read_fresh_and_nothing_is_kept(
    monkeypatch, known_model
):
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    _read()
    _read()
    assert engine.calls == 4  # nothing reused, however identical
    conn = db.connect()
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_task_cache'"
    ).fetchone()
    # and nothing written either: no table at all, or no row in it
    assert (
        table is None or conn.execute("SELECT 1 FROM ai_task_cache").fetchone() is None
    )


def test_reuse_on_and_off_give_the_same_reading(monkeypatch, known_model):
    """The cache decides nothing: the same engine answers, the same gates run."""
    engine = Engine(_reply([GOOD]))
    monkeypatch.setattr(model_transport, "post_json", engine)
    off = (monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False), _read())[1]
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    first_on = _read()
    second_on = _read()  # reused
    assert first_on["accepted"] == off["accepted"] == second_on["accepted"]
    assert len(off["accepted"]) == 1


def test_the_switch_covers_the_matcher_too(monkeypatch, known_model):
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
    calls = {"n": 0}

    def ask():
        calls["n"] += 1
        return "answer"

    for _ in range(2):
        assert (
            ai_task_runner.reuse_or_ask("t", "v", "local-0001", None, "p", ask)
            == "answer"
        )
    assert calls["n"] == 2
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    for _ in range(2):
        ai_task_runner.reuse_or_ask("t", "v", "local-0001", None, "p", ask)
    assert calls["n"] == 3  # on: the second is reused


# ------------------------------------------------ only a well-shaped answer is kept


@pytest.mark.parametrize(
    "bad", ["not json at all", "", '{"other": []}', '{"facts": "none"}', "[1, 2]"]
)
def test_a_malformed_answer_is_not_stored_and_the_next_read_asks_again(
    monkeypatch, known_model, bad
):
    engine = Engine({"response": bad, "model": "local-0001", "done_reason": "stop"})
    monkeypatch.setattr(model_transport, "post_json", engine)
    first = _read()
    asked_first = engine.calls
    assert first["accepted"] == [] and asked_first >= 1
    # the model now answers properly: a second read of the SAME page must ask it
    engine.replies = [_reply([GOOD])]
    second = _read()
    assert engine.calls > asked_first
    assert len(second["accepted"]) == 1
    # and the good answer, being well shaped, is reused from then on
    seen = engine.calls
    third = _read()
    assert engine.calls == seen and len(third["accepted"]) == 1


def test_the_form_readers_shape_is_checked_too(monkeypatch, known_model):
    shape = {
        "json_schema": {
            "type": "object",
            "required": ["fields"],
            "properties": {"fields": {"type": "array"}},
        },
        "prompt_version": "form-test-1",
        "num_predict": 64,
    }
    engine = Engine(
        {"response": "{broken", "model": "local-0001", "done_reason": "stop"}
    )
    monkeypatch.setattr(model_transport, "post_json", engine)
    call, why = datasheet_ai.model_call_for("ollama", packet_shape=shape)
    assert why is None
    assert call("same prompt") == "{broken"
    engine.replies = [
        {"response": '{"fields": []}', "model": "local-0001", "done_reason": "stop"}
    ]
    engine.calls = 0
    assert call("same prompt") == '{"fields": []}'  # asked again, not replayed
    assert engine.calls == 1
    fresh, _ = datasheet_ai.model_call_for("ollama", packet_shape=shape)
    assert fresh("same prompt") == '{"fields": []}' and engine.calls == 1  # now reused
