"""`chat_model.generate` observed directly: the Claude answer cap, Stop before the model, and an unfinished sentence on Stop.

These three features live in `chat_model.generate` / `_streamed`. Since Claude-first the chat's own routes rarely reach them, so
the older route-level tests passed with the feature removed (mutations M916, M943, M944 were NOT DETECTED). Each test here calls
the function itself with an injected transport; no socket, no model."""
from __future__ import annotations

from app import chat_model, chat_stream
from app.config import settings
from tests.test_chat import temp_storage  # noqa: F401 - autouse fixture
from tests.test_chat_pr1_model_lane import _claude_on
from tests.test_chat_pr3_stream import _claude_stream


def test_the_claude_answer_uses_the_chat_cap_not_the_local_cap(monkeypatch, tmp_path):
    seen: list = []
    _claude_on(monkeypatch, tmp_path, seen, text="A short answer.")
    assert settings.chat_max_output_tokens != settings.max_output_tokens, "the two caps must differ or this proves nothing"
    out = chat_model.generate("system", "prompt", temperature=0.2, preference="claude")
    assert out["provider"] == "claude" and seen
    assert seen[0]["max_tokens"] == settings.chat_max_output_tokens


def _open(convo="c-direct"):
    turn = chat_stream.open_turn(owner=None, conversation_id=convo)
    turn.prepare(passages=[], verify=False, general=True)
    return turn


def test_a_turn_stopped_before_the_model_makes_no_call(monkeypatch, tmp_path):
    calls: list = []
    _claude_stream(monkeypatch, tmp_path, ["never sent."], calls)
    turn = _open()
    turn.cancel.set()
    token = chat_stream.bind(turn)
    try:
        out = chat_model.generate("system", "prompt", temperature=0.2, preference="claude")
    finally:
        chat_stream.unbind(token)
    assert calls == [], "a stopped turn still reached the provider"
    assert out["cancelled"] is True and out["response"] == ""


def test_an_unfinished_sentence_is_never_shown_when_the_turn_is_stopped(monkeypatch, tmp_path):
    turn = _open()
    _claude_stream(monkeypatch, tmp_path, [])  # patches the lane; the transport is replaced below

    def send(url, *, headers, body, timeout, cancel=None):
        yield {"type": "message_start", "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 9}}}
        yield {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "A finished sentence. "}}
        yield {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "An unfinished tail"}}
        turn.cancel.set()
        yield {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " more"}}

    from app import reasoning_provider as rp
    real = rp.ClaudeProvider
    monkeypatch.setattr(rp, "get_provider", lambda role="reasoning", *, step=None: real(
        settings.claude_reasoning_model, step=step, stream_transport=send))
    token = chat_stream.bind(turn)
    try:
        out = chat_model.generate("system", "prompt", temperature=0.2, preference="claude")
    finally:
        chat_stream.unbind(token)
    assert out["cancelled"] is True
    assert turn.shown == ["A finished sentence."]
    assert "unfinished" not in " ".join(turn.shown)
