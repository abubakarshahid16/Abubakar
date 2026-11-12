"""The chat has its OWN engine setting under REASONING_PROVIDER=per_task (`chat_model_engine`, env CHAT_MODEL_ENGINE).

The setting only says whether Claude MAY BE OFFERED in chat; the reader still picks per request. No new outbound path: a
Claude chat answer still goes through `ClaudeProvider` (`reader_transport`), the USD caps, per-request consent and the block
list. Invented documents, injected transports, no socket, no model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import chat_model, claude_approved, claude_spend, local_engine_bar
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr1_model_lane import KEY, _ask, _ollama, _stream_events

REPO = Path(__file__).resolve().parents[2]
OTHER_PAPER = [["ZZQ-OTHER-PAPER the widget torque is 777 newton metres"]]
PLAIN_OFF = "Claude is switched off for chat on this computer."


def _lane(monkeypatch, tmp_path, *, provider="per_task", engine="claude"):
    """Provider switch, chat engine, both egress flags and a key; env cleared so settings decide."""
    for name in ("REASONING_PROVIDER", "CHAT_MODEL_ENGINE", "STANDARDS_READER_ENABLED",
                 "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY", "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", settings.data_dir / tmp_path.name)
    monkeypatch.setattr(settings, "reasoning_provider", provider)
    monkeypatch.setattr(settings, "chat_model_engine", engine)
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    # No test here may reach a real local model: every local fall-back is answered from a fixed reply.
    _ollama(monkeypatch, [])


def _fake_claude(monkeypatch, seen, *, tool_first=None, text="Water boils at 100 C at sea level."):
    """Replace the provider class with one whose two transports are injected (the same `ClaudeProvider` code runs: caps,
    ledger, approved list). `tool_first`: Claude's first reply is that tool call, the second is `text`."""
    calls = {"n": 0}

    def payload():
        calls["n"] += 1
        if tool_first and calls["n"] == 1:
            return {"model": "claude-sonnet-5", "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": "toolu_1", "name": "search_documents", "input": tool_first}],
                    "usage": {"input_tokens": 500, "output_tokens": 40}}
        return {"model": "claude-sonnet-5", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": text}], "usage": {"input_tokens": 700, "output_tokens": 60}}

    def send(url, *, headers, body, timeout):
        seen.append(body)
        return payload()

    def stream_send(url, *, headers, body, timeout, cancel=None):
        seen.append(body)
        yield from _stream_events(payload())

    class Injected(rp.ClaudeProvider):
        def __init__(self, model=None, *, transport=None, step=None, stream_transport=None):
            super().__init__(model, transport=send, stream_transport=stream_send, step=step)

    monkeypatch.setattr(rp, "ClaudeProvider", Injected)


def _two_documents(client):
    first = upload(client)
    second = upload(client, blocks=OTHER_PAPER)
    return first, second


# ------------------------------------------------------------- the picker

def test_the_default_is_off_and_the_picker_says_why_in_plain_words(monkeypatch, tmp_path):
    _lane(monkeypatch, tmp_path, engine="ollama")
    assert type(settings).model_fields["chat_model_engine"].default == "ollama"
    out = TestClient(app).get("/api/chat/models").json()
    by_id = {m["id"]: m for m in out["models"]}
    assert by_id["claude"]["available"] is False
    assert by_id["claude"]["reason"] == PLAIN_OFF
    assert by_id["local"]["available"] is True and out["default"] == "local"
    text = json.dumps(out)
    assert "REASONING_PROVIDER" not in text and "per_task" not in text and KEY not in text


def test_with_the_chat_engine_on_the_picker_offers_claude_but_keeps_local_as_default(monkeypatch, tmp_path):
    _lane(monkeypatch, tmp_path)
    out = TestClient(app).get("/api/chat/models").json()
    by_id = {m["id"]: m for m in out["models"]}
    assert by_id["claude"]["available"] is True and by_id["claude"]["reason"] is None
    assert by_id["local"]["available"] is True
    assert out["default"] == "local", "under per_task the reader chooses Claude per request"


@pytest.mark.parametrize("setting,expect", [
    ("egress", "Claude access is switched off in the settings."),
    ("key", "No Claude key is set on this computer."),
])
def test_the_picker_gives_plain_words_for_the_other_causes(monkeypatch, tmp_path, setting, expect):
    _lane(monkeypatch, tmp_path)
    if setting == "egress":
        monkeypatch.setattr(settings, "standards_reader_enabled", False)
    else:
        monkeypatch.setattr(settings, "anthropic_api_key", "")
    claude = {m["id"]: m for m in TestClient(app).get("/api/chat/models").json()["models"]}["claude"]
    assert claude["available"] is False and claude["reason"] == expect


@pytest.mark.parametrize("engine", ["ollama", "claude"])
def test_under_ollama_nothing_is_offered_whatever_the_chat_engine_says(monkeypatch, tmp_path, engine):
    _lane(monkeypatch, tmp_path, provider="ollama", engine=engine)
    claude = {m["id"]: m for m in TestClient(app).get("/api/chat/models").json()["models"]}["claude"]
    assert claude["available"] is False
    assert claude["reason"] == "Claude is switched off on this computer."
    assert isinstance(chat_model.provider("claude"), rp.OllamaProvider)


def test_under_claude_the_picker_is_as_before(monkeypatch, tmp_path):
    _lane(monkeypatch, tmp_path, provider="claude", engine="ollama")
    out = TestClient(app).get("/api/chat/models").json()
    assert out["default"] == "claude"
    assert {m["id"]: m for m in out["models"]}["claude"]["available"] is True


# ------------------------------------------------- what is sent, and when

def test_engine_off_a_claude_request_never_leaves_and_the_answer_says_why(monkeypatch, tmp_path):
    seen: list = []
    local_seen: list = []
    _lane(monkeypatch, tmp_path, engine="ollama")
    _fake_claude(monkeypatch, seen)
    _ollama(monkeypatch, local_seen)
    client = TestClient(app)
    doc, _ = _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1", model="claude", document_ids=[doc])
    assert seen == [], "Claude was called although chat is switched off for it"
    assert body["provider"] == "ollama"
    assert "switched off for chat" in body["provider_note"]
    assert claude_spend.entries() == []


def test_with_the_engine_on_a_general_question_with_no_document_sends_no_library_text(monkeypatch, tmp_path):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen)
    client = TestClient(app)
    _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "What is the boiling point of water at sea level?", model="claude")
    assert seen, "Claude never got the general question"
    assert body["provider"] == "claude"
    sent = json.dumps(seen)
    for fragment in ("NDFT", "280", "ZZQ-OTHER-PAPER", "777", "spec.pdf"):
        assert fragment not in sent, f"library text {fragment!r} left with a general question"
    assert [e["step"] for e in claude_spend.entries()] == ["chat"]


def test_a_request_that_does_not_say_claude_stays_local_under_per_task(monkeypatch, tmp_path):
    seen: list = []
    local_seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen)
    _ollama(monkeypatch, local_seen)
    client = TestClient(app)
    _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "What is the boiling point of water at sea level?")  # no model: "auto"
    assert seen == [] and body["provider"] == "ollama"
    assert chat_model.claude_will_answer(None) is False
    assert chat_model.claude_will_answer("claude") is True
    assert chat_model.claude_will_answer("local") is False


def test_with_a_document_selected_only_that_documents_passages_go(monkeypatch, tmp_path):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen, tool_first={"query": "NDFT coating system 1"},
                 text='The NDFT is 280 um [S1 "NDFT nominal dry film thickness of 280 um"].')
    client = TestClient(app)
    first, _ = _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1", model="claude", document_ids=[first])
    assert body["provider"] == "claude" and len(seen) == 2
    sent = json.dumps(seen)
    assert "280" in sent, "the selected document's passage did not reach Claude"
    assert "ZZQ-OTHER-PAPER" not in sent and "777" not in sent, "an unselected document's text left"


def test_the_block_list_still_refuses_a_selected_document(monkeypatch, tmp_path):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen, tool_first={"query": "NDFT coating system 1"})
    monkeypatch.setattr(claude_approved, "_blocked_ids", lambda hashes: frozenset(hashes))
    client = TestClient(app)
    first, _ = _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1", model="claude", document_ids=[first])
    assert not any("280" in json.dumps(b) for b in seen), "a blocked document's text was sent"
    assert body["provider"] != "claude" or body.get("answer_type") == "model_unavailable"


def test_the_spend_cap_still_refuses_before_anything_is_sent(monkeypatch, tmp_path):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    client = TestClient(app)
    _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "What is the boiling point of water at sea level?", model="claude")
    assert seen == [] and claude_spend.entries() == []


# --------------------------------------------------- the local-engine bar

def test_the_chat_engine_never_bars_a_review_and_is_not_a_review_engine(monkeypatch, tmp_path):
    _lane(monkeypatch, tmp_path)
    for name in local_engine_bar.REVIEW_ENGINE_SETTINGS:
        monkeypatch.setattr(settings, name, "ollama")
    monkeypatch.setattr(settings, "agent_review_engine", "ollama")
    assert "chat_model_engine" not in local_engine_bar.REVIEW_ENGINE_SETTINGS
    assert local_engine_bar.is_claude_lane_run() is False
    assert local_engine_bar.is_claude_lane_run(agent_job=True) is False


# --------------------------------------------------------- every home

def test_the_setting_is_written_in_every_home():
    assert "CHAT_MODEL_ENGINE=ollama" in (REPO / "backend" / ".env.example").read_text(encoding="utf-8")
    assert "`CHAT_MODEL_ENGINE`" in (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "| `chat_model_engine` | `ollama` |" in (REPO / "docs" / "security" / "ai-register.md").read_text(encoding="utf-8")
    assert "`chat_model_engine`" in (REPO / "docs" / "architecture-call-graph.md").read_text(encoding="utf-8")


def test_small_talk_names_who_answers_per_request(monkeypatch, tmp_path):
    from app import chat_answers

    _lane(monkeypatch, tmp_path)
    said = chat_answers.small_talk("about_the_assistant", examples=[], model=None)["answer"]
    assert "nothing you type leaves it" in said and "sent to it" not in said
    said = chat_answers.small_talk("about_the_assistant", examples=[], model="claude")["answer"]
    assert "sent to it" in said


def test_no_selection_claude_asks_to_search_and_gets_no_library_text(monkeypatch, tmp_path):
    """The fake Claude DOES call search_documents; with no document selected the tool scope is empty."""
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen, tool_first={"query": "NDFT coating system 1"})
    client = TestClient(app)
    _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "what is NDFT", model="claude")
    assert len(seen) >= 1
    sent = json.dumps(seen)
    assert "280" not in sent and "ZZQ" not in sent and "777" not in sent


def test_earlier_turns_that_quoted_a_document_are_not_sent_without_a_selection(monkeypatch, tmp_path):
    seen: list = []
    _lane(monkeypatch, tmp_path)
    _fake_claude(monkeypatch, seen, tool_first={"query": "NDFT coating system 1"},
                 text='The NDFT is 280 um [S1 "NDFT nominal dry film thickness of 280 um"].')
    client = TestClient(app)
    first, _ = _two_documents(client)
    convo = client.post("/api/conversations").json()["id"]
    first_body = _ask(client, convo, "what is the NDFT for coating system no. 1", model="claude", document_ids=[first])
    assert first_body["provider"] == "claude"
    before = len(seen)
    second_body = _ask(client, convo, "What is the boiling point of water at sea level?", model="claude")
    assert len(seen) > before and second_body["provider"] == "claude"
    sent = json.dumps(seen[before:])
    for fragment in ("280", "nominal dry film", "ZZQ", "777"):
        assert fragment not in sent, fragment
