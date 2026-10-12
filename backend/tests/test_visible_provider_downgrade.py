"""A Claude request answered by the LOCAL model says so (audit 101).

Found 2026-10-01: with Model = Claude selected, `reasoning_provider.get_provider`
hands back the local engine whenever Claude cannot be used (provider switch,
egress flags, key, a first call that failed), and the answer looked exactly
like a Claude answer. The answer now records `requested_provider="claude"` and
a code-written `provider_note` naming the real cause, is stored and lifted like
`provider`, and a turn stored before the keys existed is unchanged.

Downgrade paths covered, each against the real `chat.ask`:
  * `get_provider` / `chat_model.provider`: REASONING_PROVIDER not claude;
  * the same, egress flags off; the same, no key;
  * `chat_claude_first.answer` falling back after a failed first call;
  * the general-knowledge lane (`chat_answers.general`) and the document lane
    (`answer.answer`) both reach the same fields, because `chat.ask` adds them
    once, after whichever lane built the result;
  * the local engine being down too (a failed answer still says Claude was
    asked for).

No network, no key, no spend; synthetic text only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat, chat_claude_first, chat_model, claude_spend, schemas
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - autouse fixture
from tests.test_chat_claude_first import _ask, _on, _scripted, _text
from tests.test_chat_pr1_model_lane import KEY, _ollama

pytestmark = pytest.mark.usefixtures("temp_storage")

GENERAL_Q = "what is entropy"


def _convo(client):
    return client.post("/api/conversations").json()["id"]


def _ask_general(client, **extra):
    return _ask(client, _convo(client), GENERAL_Q, **extra)


def _clear_env(monkeypatch):
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
                 "ANTHROPIC_API_KEY", "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)


# ----------------------------------------------------- each downgrade path

def test_provider_switch_off_is_named(monkeypatch):
    _clear_env(monkeypatch)
    _ollama(monkeypatch, [], text="Entropy measures disorder.")
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    body = _ask_general(TestClient(app), model="claude")
    assert body["provider"] == rp.OLLAMA
    assert body["requested_provider"] == "claude"
    assert body["provider_note"] == (
        "Claude was not available (the system is not set up to use Claude); "
        "this answer was written by the local model.")


def test_egress_flags_off_are_named(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "standards_reader_enabled", False)
    _ollama(monkeypatch, [], text="Entropy measures disorder.")
    body = _ask_general(TestClient(app), model="claude")
    assert body["provider"] == rp.OLLAMA
    assert body["requested_provider"] == "claude"
    assert "Claude access is switched off in the settings" in body["provider_note"]


def test_a_missing_key_is_named_and_the_key_text_never_appears(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    _ollama(monkeypatch, [], text="Entropy measures disorder.")
    body = _ask_general(TestClient(app), model="claude")
    assert body["requested_provider"] == "claude"
    assert "no Claude key is set" in body["provider_note"]
    assert KEY not in str(body)


def test_a_document_question_answered_locally_is_named_too(monkeypatch):
    _clear_env(monkeypatch)
    _ollama(monkeypatch, [], text="The thickness is 280 um [S1].")
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    client = TestClient(app)
    upload(client)
    body = _ask(client, _convo(client), "what is the NDFT for coating system no. 1",
                tier="generated", model="claude")
    assert body["provider"] == rp.OLLAMA
    assert body["requested_provider"] == "claude"
    assert body["provider_note"].startswith("Claude was not available (")


def test_the_local_engine_being_down_still_says_claude_was_asked_for(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")

    def down(*_a, **_k):
        raise ConnectionError("unreachable")
    monkeypatch.setattr(chat_model.model_transport, "post_json", down)
    client = TestClient(app)
    upload(client)
    body = _ask(client, _convo(client), "what is the NDFT for coating system no. 1",
                tier="generated", model="claude")
    assert body["answer_type"] == "model_unavailable"
    assert body["provider"] == rp.OLLAMA
    assert body["requested_provider"] == "claude"
    assert body["provider_note"].endswith("the local model was used instead.")


def test_a_failed_first_claude_call_gives_its_own_cause(monkeypatch, tmp_path):
    """`chat_claude_first` returns None after a failed first call. The cause it
    reports is the call's, not whatever the settings say afterwards."""
    _on(monkeypatch, tmp_path)
    _ollama(monkeypatch, [], text="Entropy measures disorder.")

    def refused_first_call(question, **kwargs):
        kwargs["on_fallback_reason"](chat_model.fallback_words(
            claude_spend.BudgetExceeded("a cap, USD 5.0000")))
        monkeypatch.setattr(settings, "reasoning_provider", "ollama")  # the lane then runs local
        return None
    monkeypatch.setattr(chat_claude_first, "answer", refused_first_call)
    body = _ask_general(TestClient(app), model="claude")
    assert body["provider"] == rp.OLLAMA
    assert body["provider_note"] == (
        "Claude was not available (the Claude spending cap would be exceeded); "
        "this answer was written by the local model.")
    assert "USD" not in body["provider_note"]


def test_the_claude_first_loop_reports_why_it_fell_back(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    reasons: list[str] = []

    class Refusing(rp.ClaudeProvider):
        def stream(self, *_a, **_k):
            raise rp.ProviderRefused("claude: HTTPStatusError: 500 with some provider text")

    monkeypatch.setattr(chat_model, "provider",
                        lambda preference=None: Refusing(settings.claude_reasoning_model, step="chat"))
    out = chat_claude_first.answer(GENERAL_Q, history="", allowed_document_ids=frozenset(),
                                   web_enabled=False, preference="claude",
                                   on_fallback_reason=reasons.append)
    assert out is None
    assert reasons == ["the Claude call failed"]


def test_a_spending_cap_refusal_is_classified_as_the_cap(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    reasons: list[str] = []

    class Capped(rp.ClaudeProvider):
        def stream(self, *_a, **_k):
            raise claude_spend.BudgetExceeded("cap")

    monkeypatch.setattr(chat_model, "provider",
                        lambda preference=None: Capped(settings.claude_reasoning_model, step="chat"))
    chat_claude_first.answer(GENERAL_Q, history="", allowed_document_ids=frozenset(),
                             web_enabled=False, preference="claude",
                             on_fallback_reason=reasons.append)
    assert reasons == ["the Claude spending cap would be exceeded"]


# --------------------------------------------------- no notice when none is due

def test_a_normal_claude_answer_has_no_notice(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    _scripted(monkeypatch, [_text("Entropy measures disorder.")])
    body = _ask_general(TestClient(app), model="claude")
    assert body["provider"] == rp.CLAUDE
    assert body["requested_provider"] is None and body["provider_note"] is None


def test_a_local_selected_answer_has_no_notice(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    _ollama(monkeypatch, [], text="Entropy measures disorder.")
    body = _ask_general(TestClient(app), model="local")
    assert body["provider"] == rp.OLLAMA
    assert body["requested_provider"] is None and body["provider_note"] is None


def test_the_automatic_choice_has_no_notice_when_claude_is_off(monkeypatch):
    """"auto" never promised Claude, so the local engine answering is no downgrade."""
    _clear_env(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    _ollama(monkeypatch, [], text="Entropy measures disorder.")
    body = _ask_general(TestClient(app))
    assert body["provider"] == rp.OLLAMA
    assert body["requested_provider"] is None and body["provider_note"] is None


# ------------------------------------------------------------ the unit rules

def test_an_unknown_cause_says_only_that_claude_was_not_used(monkeypatch):
    monkeypatch.setattr(chat_model, "unavailable_words", lambda: None)
    out = chat_model.downgrade_fields("claude", {"provider": "ollama", "answer": "x"})
    assert out["provider_note"] == "Claude was not used; this answer was written by the local model."


def test_only_a_local_answer_to_a_claude_request_is_flagged():
    local = {"provider": "ollama", "answer": "x"}
    assert chat_model.downgrade_fields("claude", {"provider": "claude", "answer": "x"}) == {}
    assert chat_model.downgrade_fields("claude", {"answer": "a count", "provider": None}) == {}
    assert chat_model.downgrade_fields("local", local) == {}
    assert chat_model.downgrade_fields(None, local) == {}
    assert chat_model.downgrade_fields("claude", local, "the Claude call failed")["requested_provider"] == "claude"


def test_an_unreadable_cause_never_crashes_the_answer(monkeypatch):
    def broken():
        raise RuntimeError("settings unreadable")
    monkeypatch.setattr(rp, "claude_unavailable", broken)
    assert chat_model.unavailable_words() is None


# ------------------------------------- stored, lifted, and the old shape unchanged

def test_the_notice_survives_reopening_the_conversation(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    _ollama(monkeypatch, [], text="Entropy measures disorder.")
    client = TestClient(app)
    convo = _convo(client)
    fresh = _ask(client, convo, GENERAL_Q, model="claude")
    messages = client.get(f"/api/conversations/{convo}").json()["messages"]
    reopened = [m for m in messages if m["role"] == "assistant"][-1]
    assert reopened["requested_provider"] == "claude"
    assert reopened["provider_note"] == fresh["provider_note"]
    assert reopened["payload"]["provider_note"] == fresh["provider_note"]


def test_a_turn_stored_before_the_keys_existed_loads_unchanged(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    _ollama(monkeypatch, [], text="Entropy measures disorder.")
    client = TestClient(app)
    convo = _convo(client)
    _ask(client, convo, GENERAL_Q, model="local")
    messages = client.get(f"/api/conversations/{convo}").json()["messages"]
    old = [m for m in messages if m["role"] == "assistant"][-1]
    assert old["provider"] == "ollama"
    assert old["requested_provider"] is None and old["provider_note"] is None
    assert "provider_note" not in old["payload"]
    # and the response schema accepts a stored payload that never had them
    assert schemas.Message.model_fields["provider_note"].default is None


def test_both_keys_are_persisted_and_lifted():
    assert {"requested_provider", "provider_note"} <= set(chat._PAYLOAD_KEYS)
    assert {"requested_provider", "provider_note"} <= set(chat._LIFTED)
