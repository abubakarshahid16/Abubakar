"""#555: when Claude was asked for and the local model answered, the recorded
engine says so. Invented prompts; a fake local transport, no model.
"""

from __future__ import annotations

import pytest

from app import chat_model, crs_wording, fallback_note
from app import reasoning_provider as rp
from app.config import settings


@pytest.fixture
def claude_asked_for(monkeypatch):
    """REASONING_PROVIDER=claude with the lane closed, as `code` says."""

    def asked(code="KEY_MISSING", setting="claude"):
        monkeypatch.setattr(settings, "reasoning_provider", setting)
        monkeypatch.setattr(rp, "claude_unavailable", lambda: (code, "x"))

    return asked


def _response(provider=rp.OLLAMA, tag="qwen:test"):
    return rp.Response(
        text="{}",
        provider=provider,
        model_tag=tag,
        digest="d",
        finish_reason="stop",
        prompt_sha256="p",
    )


def test_the_words_cover_every_reason_the_lane_can_give():
    assert set(fallback_note.WORDS) == {
        rp.UNAVAILABLE_PROVIDER_OFF,
        rp.UNAVAILABLE_EGRESS_OFF,
        rp.UNAVAILABLE_KEY_MISSING,
    }
    assert (
        chat_model.unavailable_words() is None
        or chat_model.unavailable_words() in fallback_note.WORDS.values()
    )


@pytest.mark.parametrize("code", ["KEY_MISSING", "EGRESS_OFF"])
def test_claude_asked_for_and_unavailable_gives_a_local_engine_that_says_so(
    claude_asked_for, code
):
    claude_asked_for(code)
    engine = rp.get_provider("reasoning")
    assert isinstance(engine, rp.OllamaProvider)
    assert engine.fell_back == fallback_note.WORDS[code]
    label = fallback_note.engine_label(engine, _response())
    assert label == f"ollama:qwen:test (Claude not used: {fallback_note.WORDS[code]})"


def test_a_local_engine_that_was_chosen_says_nothing_extra(claude_asked_for):
    claude_asked_for("PROVIDER_OFF", setting="ollama")
    engine = rp.get_provider("reasoning")
    assert engine.fell_back is None
    assert fallback_note.engine_label(engine, _response()) == "ollama:qwen:test"
    assert fallback_note.engine_label(object(), _response()) == "ollama:qwen:test"


def test_a_directly_built_local_provider_is_not_a_fallback():
    assert rp.OllamaProvider().fell_back is None


def test_the_note_never_carries_a_setting_value_or_a_key(claude_asked_for):
    claude_asked_for("KEY_MISSING")
    settings_value = "sk-secret-not-a-real-key"
    engine = rp.get_provider("reasoning")
    assert settings_value not in fallback_note.engine_label(engine, _response())


def _fake(fell_back):
    class Fake:
        def reason(self, packet):
            return _response(tag="m")

    engine = Fake()
    engine.fell_back = fell_back
    return engine


ROW = {
    "standard_reference": "Std 1",
    "page_section": "p. 2",
    "comment": "Provide the rated flow.",
}


def test_the_wording_step_records_the_fallback_in_the_engine_it_stores():
    words = fallback_note.WORDS["EGRESS_OFF"]
    model = crs_wording._ask(_fake(words), ROW)[2]
    assert model == f"ollama:m (Claude not used: {words})"
    assert crs_wording._ask(_fake(None), ROW)[2] == "ollama:m"


def test_the_ai_check_records_the_fallback_in_its_engine():
    from app import ai_engineering_check as aic

    words = fallback_note.WORDS["KEY_MISSING"]
    out = aic._call(_fake(words), None)[0]
    assert fallback_note.engine_label(_fake(words), out).endswith(
        f"(Claude not used: {words})"
    )
    import inspect

    src = inspect.getsource(aic)
    assert src.count("fallback_note.engine_label(provider, response)") == 3
    assert 'f"{response.provider}:{response.model_tag}"' not in src
