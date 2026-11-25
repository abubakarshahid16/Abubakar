"""Update 7, builder C: the chat faults of the planner's live test (19 Nov 2026 02:00 and 02:05). Invented text only.

1. Model = Claude with no document chosen: a document tool reads nothing and says "no documents were given to search"; the answer
   carries code's notice, never "found nothing".
2. "How many contracts" (and a paper kind) is counted by code from the document register, no model.
3. A follow-up "check in database" keeps the earlier question; in Claude mode with no document chosen it is searched on the local
   model (nothing leaves the Mac) and says so.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat, chat_model, chat_tools, corpus, db, intent
from app import search as search_mod
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_audit_fixes import _ask, _local_model
from tests.test_chat_claude_first import _on, _scripted, _text, _tool_use

pytestmark = pytest.mark.usefixtures("temp_storage")


# ------------------------------------------------------------------ 1. no documents given


def test_a_document_tool_with_no_documents_in_scope_searches_nothing_and_says_so(
    monkeypatch,
):
    searched: list = []
    monkeypatch.setattr(
        search_mod, "search", lambda *a, **k: searched.append(k) or {"hits": []}
    )
    for name in sorted(chat_tools.DOCUMENT_TOOLS):
        run, image = chat_tools.dispatch(name, {"query": "x", "document_id": "d"}, allowed_document_ids=frozenset(),
                                         pages_used=[])  # fmt: skip
        assert (
            run.label == chat_tools.NO_DOCUMENTS_LABEL
            and run.ok is False
            and image is None
        )
        assert (
            "no documents were given to search" in run.note.lower()
            and "nothing" in run.note
        )
    assert searched == []


def test_claude_mode_with_no_document_chosen_tells_the_model_and_the_reader(
    monkeypatch, tmp_path
):
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_tool_use("search_documents", {"query": "invented process study"}),
                            _text("No documents were given to search.")], calls)  # fmt: skip
    client = TestClient(app)
    upload(client)  # the library is not empty: "found nothing" would be false
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "what is an invented process study", model="claude")
    told = calls[1]["messages"][-1]["content"][0]["content"][0]["text"]
    assert told == chat_tools.NO_DOCUMENTS_NOTE
    assert chat.NO_DOCUMENTS_NOTICE in (body.get("notices") or [])
    assert not body.get("passages")


# ------------------------------------------------------------------ 2. counted by code


def test_how_many_contracts_is_a_register_count():
    assert corpus.inventory_question("How many contracts do we have?") == [
        "CONTRACT_DOCUMENT"
    ]
    assert corpus.inventory_question("how many procedures are there") == [
        "KIND:procedure"
    ]
    assert (
        corpus.inventory_question("how many contracts cover welding") is None
    )  # content: retrieval as before
    assert (
        corpus.inventory_question("how many procedural steps") is None
    )  # no typo repair into a kind


def test_contracts_and_a_paper_kind_are_counted_from_the_register_with_their_boundary(
    monkeypatch,
):
    client = TestClient(app)
    a = upload(client)
    b = upload(
        client,
        blocks=(
            ["Invented second paper", "with some other words on its only page here"],
        ),
    )
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE document_classification SET document_role = 'CONTRACT_DOCUMENT' WHERE document_id = ?",
            (a,),
        )
        conn.execute(
            "DELETE FROM document_kinds WHERE document_id IN (?, ?)", (a, b)
        )  # a: no recorded kind
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, router_version, routed_at)"
            " VALUES (?, 'procedure', 'suggested', 'test', '2026-01-01T00:00:00Z')",
            (b,),
        )
    both = frozenset({a, b})
    said = corpus.inventory_statement(["CONTRACT_DOCUMENT"], allowed_document_ids=both)
    assert said["loaded"] == 1 and said["text"].startswith(
        "1 contract document is loaded and readable by you"
    )
    kind = corpus.inventory_statement(["KIND:procedure"], allowed_document_ids=both)
    assert kind["loaded"] == 1 and "1 document recorded as a procedure" in kind["text"]
    assert "1 document you can read has no recorded kind" in kind["text"]
    assert (
        corpus.inventory_statement(
            ["KIND:procedure"], allowed_document_ids=frozenset()
        )["loaded"]
        == 0
    )


def test_how_many_contracts_in_claude_mode_calls_no_model(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_text("should not be asked")], calls)
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    body = _ask(client, convo, "How many contracts do we have?", model="claude")
    assert calls == [] and body["answer_type"] == "metadata"
    assert "contract document" in body["answer"]


# ------------------------------------------------------------------ 3. follow-up keeps the question


@pytest.mark.parametrize("text", ["check in database", "Check in the database", "please check in my files",
                                  "look it up in the library", "search the database for it"])  # fmt: skip
def test_a_look_it_up_follow_up_is_the_previous_question_asked_of_the_documents(text):
    r = intent.route(
        text, has_previous_answer=True, document_in_scope=False, web_enabled=False
    )
    assert r["kind"] == intent.REWRITE and "check_documents" in r["styles"]


def test_a_new_question_that_names_its_subject_is_not_a_follow_up():
    r = intent.route("search the library for welding", has_previous_answer=True, document_in_scope=False,
                     web_enabled=False)  # fmt: skip
    assert r["kind"] != intent.REWRITE


def test_check_in_database_in_claude_mode_with_nothing_chosen_runs_locally_on_the_earlier_question(
    monkeypatch, tmp_path
):
    _on(monkeypatch, tmp_path)
    claude_calls: list = []
    _scripted(
        monkeypatch,
        [_text("A general answer about the invented coating system.")],
        claude_calls,
    )
    client = TestClient(app)
    upload(client)
    convo = client.post("/api/conversations").json()["id"]
    _ask(
        client,
        convo,
        "what is the dry film thickness of coating system 4",
        model="claude",
    )
    sent_before = len(claude_calls)
    local = _local_model(monkeypatch, text="The NDFT is 280 um [S1].")
    monkeypatch.setattr(
        chat_model.settings, "reasoning_provider", "claude"
    )  # Claude stays the chosen engine
    asked: list = []
    real = chat._document_answer

    def spy(conversation_id, resolved, *a, **k):
        asked.append((resolved, k.get("model")))
        return real(conversation_id, resolved, *a, **k)

    monkeypatch.setattr(chat, "_document_answer", spy)
    body = _ask(client, convo, "check in database", model="claude")
    assert (
        asked
        and "dry film thickness" in asked[0][0]
        and asked[0][1] == chat_model.LOCAL
    )
    assert len(claude_calls) == sent_before  # nothing more went to Claude
    assert chat.LOCAL_LIBRARY_NOTICE in (body.get("notices") or [])
    assert local is not None
