"""Chat redesign PR 2 (owner order 2026-09-26): the router and the general path.

Every message is routed before anything is searched. What these tests hold:
  * small talk gets a natural reply and is never searched;
  * a general question is answered from general knowledge, LABELLED, never
    searched, never carrying a document citation or a source;
  * a question naming the reader's material goes to the documents and is never
    answered from general knowledge; one with no signal tries the documents
    first and only falls back to general knowledge, labelled, when they are
    silent;
  * a rewrite re-renders the previous answer without searching, keeping a
    document answer's own sources;
  * a compliance question ends with the engineer notice, and no route writes a
    finding;
  * on the Claude lane a document claim is shown only if its quote is on the
    page it cites.

No network: models are faked at the transport. Synthetic documents only.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat_answers, chat_model, db, intent
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_pr1_model_lane import _claude_on


# ------------------------------------------------------------------ routing

@pytest.mark.parametrize("text,prev,kind", [
    ("hi", False, "general"),
    ("thanks", True, "general"),
    ("What is sulfidation? Explain it like I'm not an engineer, in one paragraph.", True, "general"),
    ("What is the difference between barg and bara?", False, "general"),
    ("i would like to implement FEED documentation, can you help me with that?", False, "general"),
    ("Give me that in points, with a bit more detail.", True, "rewrite"),
    ("Explain simply", True, "rewrite"),
    ("Shorter", True, "rewrite"),
    ("Check against my documents", True, "rewrite"),
    ("Write that as a comment for the contractor.", True, "action"),
    ("Summarise that for my manager", True, "action"),
    ("Does our datasheet meet the hydrotest requirements?", True, "document"),
    ("is this compliant?", True, "document"),
    ("what is the NDFT for coating system no. 1", False, "document"),
    ("Summarise ABC-X-123 in plain English", False, "document"),
    ("what does clause 5.2 say", False, "document"),
    ("/records pump seal", False, "records"),
    ("/quote hydrotest pressure", False, "document"),
    ("what is corrosion allowance", False, "either"),
])
def test_every_message_is_routed_by_its_words(text, prev, kind):
    assert intent.route(text, has_previous_answer=prev)["kind"] == kind


def test_a_style_request_with_no_previous_answer_is_not_a_rewrite():
    assert intent.route("Give me that in points", has_previous_answer=False)["kind"] != "rewrite"


def test_a_selected_document_makes_an_unmarked_question_a_document_one():
    assert intent.route("what is corrosion allowance", document_in_scope=True)["kind"] == "document"


def test_a_compliance_question_is_flagged():
    assert intent.route("does it meet the requirements", has_previous_answer=True)["compliance"]


# ------------------------------------------------------------- the helpers

def _local_model(monkeypatch, text="Sulfidation is sulfur attack on steel at high temperature."):
    seen = []

    def post_json(path, body, timeout):
        seen.append(body)
        return {"response": text, "model": "qwen3.5:4b", "done_reason": "stop"}

    monkeypatch.setattr(chat_model.model_transport, "post_json", post_json)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    return seen


def _no_search(monkeypatch):
    called = []
    real = answer_mod.search_mod.search
    monkeypatch.setattr(answer_mod.search_mod, "search",
                        lambda *a, **k: called.append(a[0] if a else k.get("question")) or real(*a, **k))
    return called


def _ask(client, convo, question, **extra):
    return client.post(f"/api/conversations/{convo}/ask", json={"question": question, **extra}).json()


def _findings() -> int:
    conn = db.connect()
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='review_findings'").fetchone()
    return conn.execute("SELECT COUNT(*) FROM review_findings").fetchone()[0] if exists else 0


# -------------------------------------------------------------- small talk

def test_hi_gets_a_natural_reply_and_nothing_is_searched(monkeypatch):
    searched = _no_search(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "hi")
    assert body["answer"].startswith("Hi!")
    assert searched == []
    assert body["answer_kind"] == "general" and body["used_line"] == ""


# ---------------------------------------------------------------- general

def test_a_general_question_is_answered_labelled_and_never_searched(monkeypatch):
    seen = _local_model(monkeypatch)
    searched = _no_search(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "What is sulfidation? Explain it like I'm not an engineer, in one paragraph.")
    assert searched == []
    assert body["answer_type"] == "general" and body["answer_kind"] == "general"
    assert body["used_line"].startswith("General knowledge, not from your documents · Local model")
    assert body["sources"] == [] and body["passages"] == [] and body["verification"] is None
    assert seen[0]["system"] == chat_answers.GENERAL_SYSTEM
    assert seen[0]["options"]["temperature"] == settings.chat_temperature_general == 0.5
    # the styles the reader asked for reach the model
    assert "one short paragraph" in seen[0]["prompt"] and "not an engineer" in seen[0]["prompt"]


def test_a_general_answer_never_carries_a_document_citation(monkeypatch):
    _local_model(monkeypatch, text="Steel thins over time [S1]. Plan an allowance [S2].")
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "What is the difference between barg and bara?")
    assert "[S1]" not in body["answer"] and "[S2]" not in body["answer"]
    assert body["sources"] == []


def test_an_unmarked_question_the_documents_answer_is_a_document_answer(monkeypatch):
    seen = _local_model(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the nominal dry film thickness")
    assert body["answer_kind"] == "document"
    assert all(b.get("system") != chat_answers.GENERAL_SYSTEM for b in seen)


def test_an_unmarked_question_the_documents_miss_falls_back_to_labelled_general(monkeypatch):
    seen = _local_model(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is corrosion allowance")
    assert body["answer_type"] == "general"
    assert body["used_line"].startswith("General knowledge, not from your documents")
    assert body["notices"] == ["Your documents don't cover this, so this answer is general knowledge."]
    assert seen and seen[-1]["system"] == chat_answers.GENERAL_SYSTEM


def test_a_question_about_the_readers_documents_is_never_answered_from_general_knowledge(monkeypatch):
    """THE MUTATION TARGET: the asymmetry that matters."""
    seen = _local_model(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what does our datasheet say about the corrosion allowance")
    assert body["answer_kind"] == "document"
    assert body["answer_type"] != "general"
    assert all(b.get("system") != chat_answers.GENERAL_SYSTEM for b in seen)


# --------------------------------------------------------------- rewrites

def test_a_rewrite_of_a_general_answer_searches_nothing(monkeypatch):
    seen = _local_model(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "What is sulfidation? Explain it simply.")
    searched = _no_search(monkeypatch)
    body = _ask(client, convo, "Give me that in points, with a bit more detail.")
    assert searched == []
    assert body["answer_kind"] == "rewrite" and body["answer_type"] == "general"
    assert "Previous answer:\nSulfidation is sulfur attack" in seen[-1]["prompt"]
    assert "as short bullet points and with more detail" in seen[-1]["prompt"]
    assert body["used_line"].startswith("General knowledge · Local model")


def test_a_rewrite_of_a_document_answer_keeps_its_sources_and_searches_nothing(monkeypatch):
    seen = _local_model(monkeypatch, text="The NDFT is 280 um [S1].")
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    first = _ask(client, convo, "what is the NDFT for coating system no. 1", tier="generated")
    assert first["answer_type"] == "generated"
    searched = _no_search(monkeypatch)
    body = _ask(client, convo, "in points")
    assert searched == []
    assert body["answer_kind"] == "rewrite" and body["answer_type"] == "generated"
    assert [s["document_id"] for s in body["sources"]] == [s["document_id"] for s in first["sources"]]
    assert body["used_line"].startswith("Rewrote the answer from the same sources")
    assert "Previous answer:\nThe NDFT is 280 um" in seen[-1]["prompt"]


def test_check_against_my_documents_asks_the_previous_question_of_the_documents(monkeypatch):
    _local_model(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "What is the nominal dry film thickness? Explain it simply.")
    searched = _no_search(monkeypatch)
    body = _ask(client, convo, "Check against my documents")
    assert searched, "the documents were never searched"
    assert body["answer_kind"] == "document"


# ------------------------------------------------------ verdicts and drafts

def test_a_compliance_question_ends_with_the_engineer_notice_and_writes_nothing(monkeypatch):
    _local_model(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    before = _findings()
    body = _ask(client, convo, "is coating system no. 1 compliant with the NDFT requirement")
    assert intent.ENGINEER_NOTICE in body["notices"]
    assert _findings() == before


def test_an_action_returns_a_draft_and_writes_nothing(monkeypatch):
    _local_model(monkeypatch, text="Please state the hydrotest water chloride limit.")
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    _ask(client, convo, "What is sulfidation? Explain it simply.")
    before = _findings()
    body = _ask(client, convo, "Write that as a comment for the contractor.")
    assert body["answer_kind"] == "action"
    assert body["draft"] == {"type": "comment", "text": body["answer"], "status": "draft",
                             "source_ids": []}
    assert _findings() == before


def test_records_are_searched_as_records_not_documents(monkeypatch):
    from app import deliverables, review, risks
    for module in (review, deliverables, risks):
        module.ensure_schema()
    searched = _no_search(monkeypatch)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "/records pump")
    assert searched == []
    assert body["answer_type"] == "records" and body["answer_kind"] == "records"
    assert body["used_line"].startswith("Searched your workflow records · 0 found")


# --------------------------------------------------- the Claude lane quotes

def test_on_the_claude_lane_a_claim_whose_quote_is_not_on_the_page_is_removed(monkeypatch, tmp_path):
    """THE MUTATION TARGET: a document claim is shown only if its quote verifies."""
    seen: list = []
    text = ('**Partly.**\n'
            '- The NDFT is 280 um [S1 "NDFT nominal dry film thickness of 280 um"].\n'
            '- It must be applied in five coats [S1 "applied as five coats"].')
    _claude_on(monkeypatch, tmp_path, seen, text=text)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1", tier="generated")
    assert body["answer_type"] == "generated"
    assert "five coats" not in body["answer"]
    assert "280 um [S1]" in body["answer"] and '"' not in body["answer"]
    assert body["verification"] == {"verified": 1, "total": 2, "method": "quote found on the page"}
    assert body["sources"][0]["quotes"] == ["NDFT nominal dry film thickness of 280 um"]
    assert "exact words" in seen[0]["system"][0]["text"]


def test_on_the_claude_lane_an_answer_with_no_verified_claim_is_not_shown(monkeypatch, tmp_path):
    seen: list = []
    _claude_on(monkeypatch, tmp_path, seen, text='The NDFT is 999 um [S1 "a quote that is nowhere"].')
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is the NDFT for coating system no. 1", tier="generated")
    assert body["answer_type"] == "insufficient_evidence"
    assert body["answer"] is None
    assert "could be found on the page" in body["reason"]


def test_an_uncited_figure_is_not_shown_either():
    passages = [{"text": "The design pressure is 16 barg."}]
    clean, verification, _claims, removed = answer_mod.verify_claims(
        "Partly.\nThe chloride limit is 50 ppm.\nWhat I'd do: ask the vendor.", passages)
    assert "50 ppm" not in clean and "What I'd do: ask the vendor." in clean
    assert verification["total"] == 1 and removed == 1


def test_a_general_answer_is_refused_before_it_crosses_the_budget(monkeypatch, tmp_path):
    seen: list = []
    _claude_on(monkeypatch, tmp_path, seen)
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 0.0001)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "What is the difference between barg and bara?")
    assert seen == []
    assert body["answer_type"] == "model_unavailable" and "spending cap" in body["reason"]


def test_small_talk_says_honestly_who_answers(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    local = _ask(client, convo, "what can you do")["answer"]
    assert "nothing you type leaves it" in local
    _claude_on(monkeypatch, tmp_path, [])
    claude = _ask(client, convo, "what can you do")["answer"]
    assert "Claude" in claude and "nothing you type leaves" not in claude
    assert json.dumps(claude).count("sk-ant") == 0


def test_a_withheld_answer_is_never_the_one_rewritten(monkeypatch):
    """Permissions before history: "in points" after a turn the reader can no
    longer read must not re-render it - or hand its text to the model."""
    seen = _local_model(monkeypatch)
    from app import chat

    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    conn = db.connect()
    chat._insert_message(conn, convo, role="user", text="what does the hidden plan say")
    chat._insert_message(conn, convo, role="assistant", text="HIDDEN PLAN SENTENCE 4242",
                         answer_type="extract",
                         payload={"passage": {"document_id": "doc_not_granted", "text": "x"}})
    body = _ask(client, convo, "in points")
    assert body["answer_kind"] != "rewrite"
    assert "HIDDEN PLAN SENTENCE 4242" not in json.dumps(seen)
