"""The fresh review of #1926 (lead-4, 26 Nov 2026): Chat's records answers and database tools must never hand a model a document
the block list withholds, whichever paper a text is about, nor reach a model later as history, nor answer from the records over
papers the reader picked. Invented papers, invented checksums; the register is named only through the app's own key."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import (
    chat,
    chat_db_tools,
    chat_model,
    chat_records,
    claude_approved,
    db,
    tag_cross,
)
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage  # noqa: F401 - the fixture
from tests.test_u14_chat_records import _doc, _entry

pytestmark = pytest.mark.usefixtures("temp_storage")

BLOCKED_SHA = "cd" * 32


def _blocked_doc(doc_id: str, filename: str, kind: str = "datasheet") -> None:
    _doc(doc_id, filename, kind)
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET sha256 = ? WHERE id = ?", (BLOCKED_SHA, doc_id)
        )
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": [BLOCKED_SHA]}), encoding="utf-8"
    )


@pytest.fixture
def library(monkeypatch):
    monkeypatch.setattr(settings, "chat_database_tools_enabled", True)
    _doc("doc_ok", "INV-WIDGET-OK.pdf", "datasheet")
    _blocked_doc("doc_blocked", "INV-BLOCKED-SHEET.pdf")
    return frozenset({"doc_ok", "doc_blocked"})


def test_the_cross_reference_check_never_compares_a_withheld_paper(library):
    with db.connect() as conn:
        papers = tag_cross._papers(conn)
    assert (
        "doc_ok" in papers and "doc_blocked" not in papers
    )  # never compared, so never named in a comment


def test_a_review_comment_that_names_a_withheld_paper_never_reaches_the_model(
    library, monkeypatch
):
    from app import aim_review_runs, aim_review_store, aim_review_view

    face = {
        **_entry("run-invented-ok", "doc_ok", "INV-WIDGET-OK.pdf", signed=False),
        "status": "completed",
    }
    monkeypatch.setattr(
        aim_review_runs,
        "entries",
        lambda conn, allowed, document_id=None, *, newest_only=False: [face],
    )
    monkeypatch.setattr(
        aim_review_store, "run", lambda conn, run_id: {"run_id": run_id}
    )
    comments = [
        {
            "shown_label": "Question",
            "page": 1,
            "comment": "For tag X, this paper states 10 bar, but INV-BLOCKED-SHEET states 12 bar.",
        },
        {
            "shown_label": "Question",
            "page": 2,
            "comment": "Invented comment about this paper only.",
        },
    ]
    view = {"status": "completed", "finished_at": None, "mark": "AI, to be checked", "comments": comments,
            "counts": {"points": 2, "comments": 2, "by_shown_label": {}}}  # fmt: skip
    monkeypatch.setattr(aim_review_view, "build", lambda conn, run, scope: view)
    got = chat_db_tools.latest_review({"document_id": "doc_ok"}, allowed=library)
    assert [c["comment"] for c in got["top_comments"]] == [
        "Invented comment about this paper only."
    ]
    assert "BLOCKED" not in json.dumps(got)


def test_the_records_answers_leave_out_the_reviews_of_withheld_papers(
    library, monkeypatch
):
    from app import aim_review_runs

    rows = [_entry("run-invented-ok", "doc_ok", "INV-WIDGET-OK.pdf", signed=True),
            _entry("run-invented-bl", "doc_blocked", "INV-BLOCKED-SHEET.pdf", signed=True)]  # fmt: skip
    monkeypatch.setattr(
        aim_review_runs,
        "entries",
        lambda conn, allowed, document_id=None, *, newest_only=False: rows,
    )
    text, named = chat_records.signed_reviews(library)
    assert "BLOCKED" not in text and named == ["doc_ok"]
    assert text.startswith("1 of 1 finished reviews is signed") and "1 review of papers withheld by the block list is not counted" in text  # fmt: skip
    text, named = chat_records.paper_review(
        "how many comments on the blocked review", library
    )
    assert "BLOCKED" not in text and named == []


def test_the_list_by_kind_never_names_a_withheld_paper(library):
    text, named = chat_records.papers_by_kind("list the datasheets", library)
    assert (
        "BLOCKED" not in text
        and named == ["doc_ok"]
        and "1 withheld by the block list" in text
    )


def test_a_records_answer_names_its_papers_and_never_reaches_a_model_as_history(
    library,
):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    got = client.post(
        f"/api/conversations/{convo}/ask",
        json={"question": "list the datasheets", "model": "local"},
    ).json()
    assert got["answer"].startswith("1 datasheet")
    stored = [
        m
        for m in chat.get_messages(convo, allowed_document_ids=library)
        if m["role"] == "assistant"
    ]
    assert stored and "doc_ok" in chat.referenced_document_ids(
        stored[-1]["payload"]
    )  # withheld when it is no longer readable
    turns = chat_model.history(convo, allowed_document_ids=library)
    assert [t["role"] for t in turns] == [
        "user"
    ]  # the question stays, the records answer never goes to a model


def test_a_records_answer_is_withheld_when_its_paper_is_no_longer_readable(library):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    client.post(
        f"/api/conversations/{convo}/ask",
        json={"question": "list the datasheets", "model": "local"},
    )
    later = [
        m
        for m in chat.get_messages(convo, allowed_document_ids=frozenset())
        if m["role"] == "assistant"
    ]
    assert later and later[-1]["text"] == chat.WITHHELD_TEXT


def test_with_papers_picked_the_records_never_answer_instead_of_the_papers(library):
    client = TestClient(app)
    convo = client.post("/api/conversations").json()["id"]
    got = client.post(f"/api/conversations/{convo}/ask",
                      json={"question": "list the datasheets", "model": "local", "document_ids": ["doc_ok"]}).json()  # fmt: skip
    assert got.get("input_kind") != "records_question" and not str(got.get("used_line") or "").startswith("Read from the app's records")  # fmt: skip
