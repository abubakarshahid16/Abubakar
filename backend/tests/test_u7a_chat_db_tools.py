"""Chat's database tools (owner, 25 Nov 2026, #1584: "Yes, allow it"), behind CHAT_DATABASE_TOOLS_ENABLED (off). A document the
caller may not read never appears; the client's register and a blocked file never appear; Local only and the local engine send
nothing; the tools are not offered with the switch off. No network: the Claude transport is faked. Invented documents only
(the register is named only through the app's own key, never written here)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import aim_review_store, aim_review_view, chat_db_tools, claude_approved, db
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage  # noqa: F401 - the fixture is autouse
from tests.test_chat_claude_first import _on, _scripted, _text, _tool_use

pytestmark = pytest.mark.usefixtures("temp_storage")

REGISTER_FILE = f"Copy of {claude_approved.REGISTER_NAME_KEY} (1).pdf"


def _doc(doc_id: str, filename: str, role: str, sha: str | None = None) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
            " VALUES (?, ?, ?, 1, ?, 'ready', '2026-11-25T00:00:00Z')",
            (doc_id, filename, sha or (doc_id * 8)[:64], f"/nowhere/{doc_id}"),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, title, suggested_by) VALUES (?, ?, ?, 'test')",
            (doc_id, role, filename.rsplit(".", 1)[0]),
        )


@pytest.fixture
def library(monkeypatch):
    monkeypatch.setattr(settings, "chat_database_tools_enabled", True)
    _doc("doc_c1", "INV-CONTRACT-1.pdf", "CONTRACT_DOCUMENT")
    _doc("doc_c2", "INV-CONTRACT-2.pdf", "CONTRACT_DOCUMENT")
    _doc("doc_secret", "INV-CONTRACT-SECRET.pdf", "CONTRACT_DOCUMENT")
    _doc("doc_reg", REGISTER_FILE, "CONTRACT_DOCUMENT")
    _doc("doc_marked", "INV-CONTRACT-3.pdf", "CONTRACT_DOCUMENT", sha="ab" * 32)
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["ab" * 32]}), encoding="utf-8"
    )
    return frozenset(
        {"doc_c1", "doc_c2", "doc_reg", "doc_marked"}
    )  # doc_secret: the caller may not read it


def test_a_document_the_caller_may_not_read_is_counted_never_named(library):
    got = chat_db_tools.list_documents({"role": "CONTRACT_DOCUMENT"}, allowed=library)
    ids = [d["id"] for d in got["documents"]]
    assert ids == ["doc_c1", "doc_c2"]
    assert "doc_secret" not in json.dumps(got) and "SECRET" not in json.dumps(got)
    assert got["not_readable_count"] == 1


def test_the_register_and_a_blocked_file_never_appear_anywhere(library):
    got = chat_db_tools.list_documents({}, allowed=library)
    text = json.dumps(got).lower()
    assert (
        claude_approved.REGISTER_NAME_KEY not in text.replace(" ", "")
        and "doc_reg" not in text
    )
    assert "doc_marked" not in text and got["withheld_count"] == 2
    assert (
        chat_db_tools.latest_review({"document_id": "doc_reg"}, allowed=library)[
            "found"
        ]
        is False
    )
    assert (
        chat_db_tools.latest_review({"document_id": "doc_marked"}, allowed=library)[
            "found"
        ]
        is False
    )
    assert not any(
        "deliverable" in t["name"] for t in chat_db_tools.TOOLS
    )  # no deliverables-status tool


def test_an_unreadable_block_file_withholds_everything(library):
    claude_approved.block_file_path().write_text("{not json", encoding="utf-8")
    got = chat_db_tools.list_documents({}, allowed=library)
    assert got["documents"] == [] and got["withheld_count"] == 4


def _face(monkeypatch, engine: str, words: str) -> None:
    """The paper's face review (`aim_review_face` through the runs list), as the tool reads it."""
    from app import aim_review_runs

    monkeypatch.setattr(
        aim_review_runs,
        "entries",
        lambda conn, allowed, document_id=None, *, newest_only=False: [
            {
                "review_run_id": "run_x",
                "status": "completed",
                "engine": engine,
                "engine_words": words,
            }
        ],
    )
    monkeypatch.setattr(
        aim_review_store, "run", lambda conn, run_id: {"run_id": run_id}
    )


def test_the_latest_review_gives_counts_and_comments_with_page_never_the_papers_quote(
    library, monkeypatch
):
    _face(monkeypatch, "claude", "Claude")
    view = {
        "status": "completed",
        "finished_at": "2026-11-25T00:00:00Z",
        "mark": "AI, to be checked",
        "counts": {"points": 7, "comments": 2, "by_shown_label": {"Question": 2}},
        "comments": [
            {
                "shown_label": "Question",
                "page": 3,
                "comment": "Invented comment.",
                "standard": "INV-STD",
                "clause": "4.1",
                "quote": "an invented quote of the paper",
            }
        ],
    }
    monkeypatch.setattr(aim_review_view, "build", lambda conn, run, scope: view)
    got = chat_db_tools.latest_review({"document_id": "doc_c1"}, allowed=library)
    assert got["counts"]["points"] == 7 and got["top_comments"][0]["page"] == 3
    assert "invented quote" not in json.dumps(got)
    assert (
        chat_db_tools.latest_review({"document_id": "doc_secret"}, allowed=library)[
            "found"
        ]
        is False
    )


def test_technical_query_items_say_they_are_not_here_yet(library):
    assert chat_db_tools.tq_open_items({"query": "INV-TQ-1"}, allowed=library) == {
        "found": False,
        "note": chat_db_tools.TQ_NOT_HERE,
    }


def _names(body: dict) -> set[str]:
    return {t["name"] for t in body.get("tools") or []}


def test_claude_lists_the_records_with_the_switch_on_and_only_readable_ones_reach_it(
    library, monkeypatch, tmp_path
):
    from app import chat

    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(
        monkeypatch,
        [
            _tool_use("list_documents", {"role": "CONTRACT_DOCUMENT"}),
            _text("Two contracts."),
        ],
        calls,
    )
    convo = chat.create_conversation()["id"]
    chat.ask(
        convo,
        "List the contracts we hold",
        allowed_document_ids=library,
        model="claude",
    )
    assert calls and chat_db_tools.NAMES <= _names(calls[0])
    sent = json.dumps(calls[1]["messages"])
    assert "doc_c1" in sent and "doc_c2" in sent
    assert (
        "doc_secret" not in sent and "SECRET" not in sent
    )  # the caller may not read it: counted, never named
    assert "doc_reg" not in sent and "doc_marked" not in sent


def test_with_the_switch_off_the_tools_are_never_offered(
    library, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "chat_database_tools_enabled", False)
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_text("Hello.")], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    client.post(
        f"/api/conversations/{convo}/ask",
        json={"question": "What is a gate valve?", "model": "claude"},
    )
    assert all(not (chat_db_tools.NAMES & _names(b)) for b in calls)


def test_local_only_and_the_local_engine_send_nothing(library, monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    calls: list = []
    _scripted(monkeypatch, [_tool_use("list_documents", {}), _text("x")], calls)
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    client.post(
        f"/api/conversations/{convo}/ask",
        json={"question": "List the contracts we hold", "model": "local"},
    )
    assert calls == []  # not one request reached Claude


def test_the_latest_review_is_the_files_face_and_names_a_local_rough_draft(
    library, monkeypatch
):
    """Review of update 12, N9: the tool gives the review the paper's row opens (its face) and names the engine, so a local
    rough draft is never handed over as if it were the review."""
    words = "Local model: rough draft, not scored as reliable"
    _face(monkeypatch, "local", words)
    view = {"status": "completed", "finished_at": None, "mark": "AI, to be checked",
            "counts": {"points": 1, "comments": 0, "by_shown_label": {}}, "comments": []}  # fmt: skip
    monkeypatch.setattr(aim_review_view, "build", lambda conn, run, scope: view)
    got = chat_db_tools.latest_review({"document_id": "doc_c1"}, allowed=library)
    assert got["engine"] == "local" and got["engine_words"] == words


@pytest.mark.parametrize(
    "question, records",
    [
        ("List the contracts we hold", True),
        ("Which documents do we have?", True),
        ("How many datasheets are there", True),
        ("Show me all the procedures", True),
        ("What is the latest review of the pump paper", True),
        ("What is the design pressure in the datasheet", False),
        ("What does the contract say about payment", False),
        ("Which standards does this datasheet cite", False),
        ("What is the set pressure", False),
    ],
)
def test_only_a_question_about_the_librarys_records_takes_the_records_path(
    library, question, records
):
    assert chat_db_tools.asks_the_records(question) is records
