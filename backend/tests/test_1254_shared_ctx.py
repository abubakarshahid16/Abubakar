"""One shared context window for every local Ollama call (PR 1254).

Ollama reloads the model whenever a call's `num_ctx` differs from the loaded
one. Steps asked for 2048, 4096 and 8192, so two reviews in different phases
took turns evicting each other's runner. `model_transport.runner_options` is
the one place every local generate/chat call passes through; it now raises
`num_ctx` to `settings.local_num_ctx`. Invented text, no network."""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from app import answerability, applicability_reasoning, model_transport
from app import reasoning_provider as rp
from app.config import Settings, settings
from tests.test_chat import temp_storage  # noqa: F401 - the fixture is autouse

pytestmark = pytest.mark.usefixtures("temp_storage")

SHARED = 8192


def _capture(monkeypatch) -> list[dict]:
    seen: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}", "done_reason": "stop", "model": "m"}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None):
            seen.append(json)
            return FakeResponse()

    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:11434")
    monkeypatch.setattr(settings, "num_ctx", 4096)
    monkeypatch.setattr(settings, "local_num_ctx", SHARED)
    monkeypatch.setattr(httpx, "Client", FakeClient)
    return seen


def _packet(num_ctx: int, step: str) -> rp.Packet:
    return rp.Packet(prompt="invented", num_ctx=num_ctx, num_predict=20, step=step)


def _step_packets() -> list[rp.Packet]:
    """One packet per step, each with the num_ctx that step really asks for."""
    judge = answerability._judge_packet("Is it rated?", [{"text": "It is rated."}])
    applic = applicability_reasoning.packet(
        {"requirement_text": "shall be rated"}, "pump", step="applicability"
    )
    return [
        _packet(2048, "ai_task_runner"),  # ai_task_runner.py
        judge,  # answerability.py: 4096
        applic,  # applicability_reasoning.py: 4096
        _packet(4096, "crs_wording"),  # crs_wording.py: 4096
        _packet(settings.num_ctx, "chat"),  # chat_model / analysis / comparison
        _packet(8192, "datasheet_ai"),  # datasheet_ai.OLLAMA_NUM_CTX
    ]


def test_the_real_step_packets_ask_for_the_sizes_this_fix_unifies():
    asked = sorted({p.num_ctx for p in _step_packets()})
    assert asked == [2048, 4096, 8192], "the call sites changed; update this test"


def test_every_local_step_sends_the_same_num_ctx(monkeypatch):
    seen = _capture(monkeypatch)
    for packet in _step_packets():
        rp.OllamaProvider().reason(packet)
    assert [b["options"]["num_ctx"] for b in seen] == [SHARED] * 6


def test_the_shared_normaliser_every_path_uses_raises_a_small_request():
    body = model_transport.with_runner_options(
        {"model": "m", "options": {"num_ctx": 2048}}
    )
    assert body["options"]["num_ctx"] == max(settings.num_ctx, settings.local_num_ctx)


def test_a_request_larger_than_the_shared_size_keeps_its_own(monkeypatch):
    seen = _capture(monkeypatch)
    rp.OllamaProvider().reason(_packet(16384, "field_naming"))
    rp.OllamaProvider().reason(_packet(32768, "vision"))
    assert [b["options"]["num_ctx"] for b in seen] == [16384, 32768]


def test_a_lowered_shared_size_never_goes_below_the_prompt_default(monkeypatch):
    _capture(monkeypatch)
    monkeypatch.setattr(settings, "local_num_ctx", 2048)
    assert model_transport.runner_options(1024)["num_ctx"] == settings.num_ctx


def test_only_runner_paths_are_changed(monkeypatch):
    seen = _capture(monkeypatch)
    model_transport.post_json(
        "/api/embed",
        {"model": "e", "input": "x", "options": {"num_ctx": 512}},
        timeout=5,
    )
    model_transport.post_json(
        "/api/generate",
        {"model": "m", "prompt": "x", "options": {"num_ctx": 512}},
        timeout=5,
    )
    assert [b["options"]["num_ctx"] for b in seen] == [512, SHARED]


def test_the_claude_lane_num_ctx_is_untouched(monkeypatch):
    """A Claude packet (num_ctx 200_000 in the chat loop) never reaches the
    local normaliser, and the shared size is not written into its request."""
    seen = _capture(monkeypatch)
    sent: list[dict] = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        return {
            "model": "claude-x",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    for name, value in (
        ("reasoning_provider", "claude"),
        ("anthropic_api_key", "sk-ant-test-0000000000"),
        ("standards_reader_enabled", True),
        ("standards_reader_allow_public_egress", True),
    ):
        monkeypatch.setattr(settings, name, value)
    packet = _packet(200_000, "chat_claude")
    try:
        rp.ClaudeProvider("claude-x", transport=send).reason(packet)
    except Exception:  # noqa: BLE001 - a ledger refusal is fine; only the lane matters
        pass
    assert seen == [], "a Claude packet went through the local Ollama transport"
    assert all(b.get("options", {}).get("num_ctx") != SHARED for b in sent)
    assert packet.num_ctx == 200_000
    # And the local normaliser leaves a non-runner body exactly as it was.
    assert model_transport._normalised(
        "/api/tags", {"options": {"num_ctx": 200_000}}
    ) == {"options": {"num_ctx": 200_000}}


def test_out_of_range_local_num_ctx_is_refused_with_a_plain_message(monkeypatch):
    for bad in ("1024", "999999", "abc"):
        monkeypatch.setenv("LOCAL_NUM_CTX", bad)
        with pytest.raises(ValidationError) as err:
            Settings()
        assert "local_num_ctx" in str(err.value)
    monkeypatch.setenv("LOCAL_NUM_CTX", "16384")
    assert Settings().local_num_ctx == 16384
    monkeypatch.delenv("LOCAL_NUM_CTX")
    assert Settings().local_num_ctx == 8192


def test_a_mixed_sequence_of_calls_uses_exactly_one_distinct_num_ctx(monkeypatch):
    """The reload-thrash proxy: distinct num_ctx values seen by Ollama."""
    seen = _capture(monkeypatch)
    for _ in range(3):
        for packet in _step_packets():
            rp.OllamaProvider().reason(packet)
    assert len(seen) == 18
    assert {b["options"]["num_ctx"] for b in seen} == {SHARED}


def test_changing_the_shared_window_changes_the_run_stamp_and_the_reader_key(monkeypatch):
    """s2's blocker 1: two runs at different LOCAL_NUM_CTX must not look alike,
    and the reader must not reuse answers read at another window."""
    from app import config, datasheet_ai

    assert "local_num_ctx" in config.ANSWER_AFFECTING_SETTINGS
    monkeypatch.setattr(settings, "local_num_ctx", 8192)
    stamp, key = config.config_version(), datasheet_ai._effective_window()
    monkeypatch.setattr(settings, "local_num_ctx", 16384)
    assert config.config_version() != stamp
    assert datasheet_ai._effective_window() != key
    assert datasheet_ai._effective_window() == 16384
