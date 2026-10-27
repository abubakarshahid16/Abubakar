"""#555: when Claude was asked for and the local model answered, the recorded
engine says so. Invented prompts; a fake local transport, no model.
"""

from __future__ import annotations

import pytest

from app import chat_model, crs_wording, fallback_note
from app import reasoning_provider as rp
from app.config import settings
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import world  # noqa: F401 - fixture


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


def _local_reply(self, packet):
    return _response(tag="m")


@pytest.fixture
def closed_lane(monkeypatch):
    """Claude asked for in the way `how` says and the lane closed (no key)."""

    def set_up(how="claude"):
        monkeypatch.setattr(settings, "reasoning_provider", how)
        monkeypatch.setattr(settings, "crs_ai_wording_engine", "claude")
        monkeypatch.setattr(settings, "review_ai_check_engine", "claude")
        monkeypatch.setattr(rp.OllamaProvider, "reason", _local_reply)
        monkeypatch.setattr(
            rp,
            "claude_unavailable",
            lambda: (
                ("KEY_MISSING", "no key") if how == "claude" else ("PROVIDER_OFF", "x")
            ),
        )
        monkeypatch.setattr(
            rp, "claude_unavailable_for_task", lambda engine: ("KEY_MISSING", "no key")
        )
        monkeypatch.setattr(rp, "claude_for_task", lambda *a, **k: None)

    return set_up


@pytest.mark.parametrize("how", ["claude", "per_task"])
def test_the_wording_step_keeps_the_note_on_the_provider_it_really_uses(
    closed_lane, how
):
    closed_lane(how)
    provider, local_instead = crs_wording._provider_for_this_review()
    assert isinstance(provider, rp.OllamaProvider) and local_instead is None
    assert provider.fell_back == fallback_note.WORDS["KEY_MISSING"]
    label = crs_wording._ask(provider, ROW)[2]
    assert label == f"ollama:m (Claude not used: {fallback_note.WORDS['KEY_MISSING']})"


def test_a_step_that_never_asked_for_claude_says_nothing(closed_lane, monkeypatch):
    closed_lane("per_task")
    monkeypatch.setattr(settings, "crs_ai_wording_engine", "ollama")
    provider, _ = crs_wording._provider_for_this_review()
    assert provider.fell_back is None
    assert crs_wording._ask(provider, ROW)[2] == "ollama:m"


def test_a_document_not_approved_for_the_cloud_model_is_named_for_a_step_that_asked(
    monkeypatch,
):
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(rp, "claude_unavailable_for_task", lambda engine: (None, ""))
    local = rp.OllamaProvider()
    monkeypatch.setattr(rp, "claude_for_task", lambda *a, **k: None)
    marked = fallback_note.or_local(local, "claude")
    assert marked.fell_back == fallback_note.NOT_APPROVED


def test_the_ai_check_hands_its_local_provider_the_note(
    request, closed_lane, monkeypatch
):
    from app import ai_engineering_check as aic

    closed_lane("claude")
    _sub, run, scope = request.getfixturevalue("world")
    seen = []

    def spy(provider, *a, **k):
        seen.append(provider)
        return {
            "pages": 0,
            "done": [],
            "timed_out": [],
            "failed": [],
            "not_tried": [],
            "no_value_read": [],
            "no_blank_field": [],
            "calls_made": 0,
            "proposed": 0,
            "engine": None,
        }

    monkeypatch.setattr(aic, "_local_page_calls", spy)
    aic.run_check(run, allowed_document_ids=scope, cited=[])
    assert seen and isinstance(seen[0], rp.OllamaProvider)
    assert seen[0].fell_back == fallback_note.WORDS["KEY_MISSING"]


def test_carry_copies_the_note_to_a_replacement_provider():
    old = rp.OllamaProvider()
    old.fell_back = "x"
    assert fallback_note.carry(old, timeout=5.0).fell_back == "x"
    assert fallback_note.carry(rp.OllamaProvider(), timeout=5.0).fell_back is None


def test_a_global_claude_request_survives_a_step_that_did_not_ask_itself(
    closed_lane, monkeypatch
):
    """REASONING_PROVIDER=claude and the wording step's own engine says ollama: only the provider
    switch asked for Claude, and the fresh local provider must still carry that."""
    closed_lane("claude")
    monkeypatch.setattr(settings, "crs_ai_wording_engine", "ollama")
    provider, _ = crs_wording._provider_for_this_review()
    assert provider.fell_back == fallback_note.WORDS["KEY_MISSING"]
