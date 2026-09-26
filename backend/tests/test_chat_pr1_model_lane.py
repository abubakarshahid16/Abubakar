"""Chat redesign PR 1 (owner order 2026-09-26): the chat's model lane.

Which engine answers (Claude when configured, else the local engine, and a
reader can only narrow to local), the output caps, the temperature, the USD
cap enforced before a call leaves, conversation memory filtered by permission
BEFORE it is assembled, and the additive answer fields - on a fresh answer and
on a reopened one, with a turn stored before they existed still loading.

No network: the Claude transport is injected. Synthetic documents only.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat, chat_model, chat_presentation, claude_spend, db
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse

KEY = "sk-ant-test-THIS-MUST-NEVER-APPEAR-0123456789"


def _claude_on(monkeypatch, tmp_path, seen, text="The thickness is 280 um [S1].", usage=None):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in ("STANDARDS_READER_ENABLED", "STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "ANTHROPIC_API_KEY",
                 "STANDARDS_READER_MODEL"):
        monkeypatch.delenv(name, raising=False)

    def send(url, *, headers, body, timeout):
        seen.append(body)
        return {"model": "claude-sonnet-5", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": text}],
                "usage": usage or {"input_tokens": 1200, "output_tokens": 80}}

    real = rp.ClaudeProvider

    def provider(role="reasoning", *, step=None):
        return real(settings.claude_reasoning_model, transport=send, step=step)

    monkeypatch.setattr(rp, "get_provider", provider)


def _ollama(monkeypatch, seen, text="The thickness is 280 um [S1]."):
    def post_json(path, body, timeout):
        seen.append(body)
        return {"response": text, "model": "qwen3.5:4b", "done_reason": "stop"}
    monkeypatch.setattr(chat_model.model_transport, "post_json", post_json)


def _ask(client, convo, question, **extra):
    return client.post(f"/api/conversations/{convo}/ask",
                       json={"question": question, "tier": "generated", **extra}).json()


# ---------------------------------------------------------------- the engine

def test_claude_answers_the_chat_when_configured_and_is_charged_to_chat(monkeypatch, tmp_path):
    seen: list = []
    _claude_on(monkeypatch, tmp_path, seen)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1")
    assert seen, "Claude was never called"
    assert body["provider"] == "claude" and body["model"] == "claude-sonnet-5"
    assert seen[0]["max_tokens"] == settings.chat_max_output_tokens == 1500
    ledger = claude_spend.entries()
    assert [e["step"] for e in ledger] == ["chat"]
    assert body["cost_usd"] == pytest.approx(ledger[0]["cost_usd"])


def test_local_preference_narrows_to_the_local_engine(monkeypatch, tmp_path):
    claude_seen: list = []
    local_seen: list = []
    _claude_on(monkeypatch, tmp_path, claude_seen)
    _ollama(monkeypatch, local_seen)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1", model="local")
    assert local_seen and not claude_seen
    assert body["provider"] == "ollama"


def test_without_claude_configured_the_local_engine_answers(monkeypatch):
    seen: list = []
    _ollama(monkeypatch, seen)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1", model="claude")
    assert seen and body["provider"] == "ollama"
    # the local engine keeps its own cap; its window has to hold the evidence
    assert seen[0]["options"]["num_predict"] == settings.max_output_tokens
    assert seen[0]["options"]["temperature"] == settings.chat_temperature_document == 0.2


def test_the_budget_cap_refuses_before_anything_is_sent(monkeypatch, tmp_path):
    seen: list = []
    _claude_on(monkeypatch, tmp_path, seen)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1")
    assert seen == [], "a call over the cap left the machine"
    assert body["answer_type"] == "model_unavailable"
    assert "spending cap" in body["reason"]
    assert claude_spend.entries() == []


def test_the_models_route_lists_only_what_can_run(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    out = TestClient(app).get("/api/chat/models").json()
    assert out["default"] == "local"
    by_id = {m["id"]: m for m in out["models"]}
    assert by_id["local"]["available"] is True
    assert by_id["claude"]["available"] is False and "REASONING_PROVIDER" in by_id["claude"]["reason"]
    assert KEY not in json.dumps(out)


# ----------------------------------------------------------------- memory

def test_the_model_sees_the_conversation_as_labelled_context(monkeypatch):
    seen: list = []
    _ollama(monkeypatch, seen)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "what is the NDFT for coating system no. 1")
    _ask(client, convo, "what is its dry film thickness")
    second = seen[-1]["prompt"]
    assert second.startswith("Conversation so far (context only")
    assert "User: what is the NDFT for coating system no. 1" in second
    assert "Assistant: The thickness is 280 um" in second
    # an earlier answer's citation marker named ITS sources, not these
    assert "[S1]" not in second.split("Question:")[0].split("\n\n")[0]
    # the turn being answered is the Question, not part of the history
    history_block = second.split("[S1]")[0]
    assert "what is its dry film thickness" not in history_block


def test_a_withheld_turn_never_reaches_the_model():
    """THE MUTATION TARGET: permissions are applied before history is sent."""
    client = TestClient(app)
    doc = upload(client)
    convo = client.post("/api/conversations").json()["id"]
    conn = db.connect()
    chat._insert_message(conn, convo, role="user", text="what does the hidden one say")
    chat._insert_message(conn, convo, role="assistant", text="HIDDEN-DOC SENTENCE 777",
                         answer_type="extract",
                         payload={"passage": {"document_id": "doc_not_granted", "text": "x"}})
    chat._insert_message(conn, convo, role="user", text="and the visible one")
    chat._insert_message(conn, convo, role="assistant", text="VISIBLE SENTENCE",
                         answer_type="extract", payload={"passage": {"document_id": doc, "text": "y"}})
    turns = chat_model.history(convo, allowed_document_ids=frozenset({doc}))
    text = json.dumps(turns)
    assert "HIDDEN-DOC SENTENCE 777" not in text
    assert chat.WITHHELD_TEXT not in text
    assert "VISIBLE SENTENCE" in text


def test_history_keeps_the_newest_turns_within_its_budget():
    client = TestClient(app)
    doc = upload(client)
    convo = client.post("/api/conversations").json()["id"]
    conn = db.connect()
    for i in range(6):
        chat._insert_message(conn, convo, role="user", text=f"question number {i} " + "x" * 200)
    turns = chat_model.history(convo, allowed_document_ids=frozenset({doc}), token_budget=150)
    assert turns and turns[-1]["text"].startswith("question number 5")
    assert "question number 0" not in json.dumps(turns)


# ------------------------------------------------------------- the schema

def test_an_answer_carries_its_used_line_sources_and_verification():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = client.post(f"/api/conversations/{convo}/ask",
                       json={"question": "what is the NDFT for coating system no. 1"}).json()
    assert body["answer_type"] == "extract"
    assert body["answer_kind"] == "document"
    assert body["used_line"].startswith("Checked your document")
    assert body["sources"][0]["n"] == 1 and body["sources"][0]["display_name"] == "spec"
    assert body["sources"][0]["page"] == 1
    assert body["verification"] == {"verified": 1, "total": 1, "method": "verbatim quotation"}
    assert [s["label"] for s in body["steps"]][0] == "Searched your documents"
    reopened = client.get(f"/api/conversations/{convo}").json()["messages"][-1]
    for key in ("answer_kind", "used_line", "sources", "verification", "steps"):
        assert reopened[key] == body[key], key


def test_generated_prose_claims_no_verification_it_has_not_done(monkeypatch):
    seen: list = []
    _ollama(monkeypatch, seen)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1")
    assert body["answer_type"] == "generated"
    assert body["verification"] is None
    assert body["sources"] and body["sources"][0]["cited"] is True


def test_a_turn_stored_before_the_new_fields_still_loads():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    conn = db.connect()
    chat._insert_message(conn, convo, role="user", text="old question")
    chat._insert_message(conn, convo, role="assistant", text="old answer", answer_type="extract",
                         payload={"retrieval_mode": "hybrid"})
    got = client.get(f"/api/conversations/{convo}")
    assert got.status_code == 200
    old = got.json()["messages"][-1]
    assert old["text"] == "old answer" and old["answer_kind"] is None and old["sources"] == []


def test_a_withheld_turn_loses_its_sources_too():
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    conn = db.connect()
    chat._insert_message(conn, convo, role="assistant", text="secret", answer_type="extract",
                         payload={"sources": [{"n": 1, "kind": "document", "document_id": "doc_x",
                                               "display_name": "Hidden plan", "cited": True}],
                                  "used_line": "Checked Hidden plan"})
    msg = chat.get_messages(convo, allowed_document_ids=frozenset())[-1]
    assert msg["text"] == chat.WITHHELD_TEXT
    assert "Hidden plan" not in json.dumps(msg)


def test_the_used_line_counts_documents_by_their_recorded_role():
    result = {"answer_type": "extract", "seconds": 6.2,
              "answer_passages": [{"document_id": "a"}, {"document_id": "b"}, {"document_id": "c"}]}
    roles = {"a": {"document_role": "CONTRACTOR_SUBMITTAL"},
             "b": {"document_role": "COMPANY_STANDARD"}, "c": {"document_role": "COMPANY_STANDARD"}}
    assert chat_presentation._what_was_checked(["a", "b", "c"], roles) == "your submittal and 2 standards"
    assert chat_presentation._seconds(6.2) == "6 s"


def test_answer_passes_history_to_the_prompt_only_through_the_labelled_block(monkeypatch):
    prompts: list = []
    monkeypatch.setattr(answer_mod, "_call_model",
                        lambda prompt, timeout=180.0: prompts.append(prompt) or {"response": "x [S1]."})
    client = TestClient(app)
    upload(client)
    everything = frozenset(r["id"] for r in db.connect().execute("SELECT id FROM documents"))
    answer_mod.answer("what is the NDFT for coating system no. 1", tier="generated",
                      allowed_document_ids=everything,
                      history=chat_model.transcript([{"role": "user", "text": "EARLIER TURN"}]))
    assert prompts and prompts[0].index("EARLIER TURN") < prompts[0].index("[S1]")


def test_the_local_engine_gets_the_smaller_history_budget(monkeypatch):
    """Evidence first: on the local engine's small window, memory is capped
    harder so it never pushes a retrieved passage out."""
    seen: list = []
    _ollama(monkeypatch, seen)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    monkeypatch.setattr(settings, "chat_history_local_token_budget", 20)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    conn = db.connect()
    chat._insert_message(conn, convo, role="user", text="LONG EARLIER QUESTION " + "y" * 300)
    _ask(client, convo, "what is the NDFT for coating system no. 1")
    assert "LONG EARLIER QUESTION" not in seen[-1]["prompt"]
