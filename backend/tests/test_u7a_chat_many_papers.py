"""Chat with several selected papers (owner's own use, planner 25 Nov 2026 23:35, note A): every selected paper is named to Claude
and searched on its own, the tool budget covers one read each, the answer says by code how many were read and how many are still
processing, and "review these" offers the real Review. No network: the Claude transport is faked. Invented documents only."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import chat_coverage, chat_tools, db, states
from app.config import settings
from app.main import app
from tests.test_chat import temp_storage  # noqa: F401 - the fixture is autouse
from tests.test_chat_claude_first import _on, _scripted, _text, _tool_use
from tests.test_claude_scope_named_document import _upload

pytestmark = pytest.mark.usefixtures("temp_storage")


def _three(client) -> list[str]:
    ids = [
        _upload(
            client,
            f"INV-PAPER-{n}.pdf",
            [f"{n}.1 Scope", f"The invented item {n} is rated for zeta service."],
        )
        for n in (1, 2, 3)
    ]
    with db.connect() as conn:  # the third is still being read in
        conn.execute(
            "UPDATE documents SET status = ? WHERE id = ?", (states.CHUNKING, ids[2])
        )
    return ids


def test_a_search_over_several_picked_papers_gives_each_its_own_passages(monkeypatch):
    seen = []

    def search(query, *, limit, allowed_document_ids):
        seen.append((limit, allowed_document_ids))
        (doc,) = allowed_document_ids
        return {
            "hits": [
                {
                    "chunk_id": f"{doc}-{i}",
                    "document_id": doc,
                    "filename": doc,
                    "page_start": 1,
                    "page_end": 1,
                    "text": "t",
                    "score": 1.0,
                }
                for i in range(6)
            ]
        }

    monkeypatch.setattr(chat_tools.search_mod, "search", search)
    run = chat_tools.run_search_documents(
        {"query": "zeta", "document_ids": ["d1", "d2", "d3", "d_secret"]},
        allowed_document_ids=frozenset({"d1", "d2", "d3"}),
    )
    docs = [s["document_id"] for s in run.sources_added]
    assert sorted(set(docs)) == [
        "d1",
        "d2",
        "d3",
    ]  # every picked paper, never one it may not read
    assert all(docs.count(d) == chat_tools.PER_PAPER for d in ("d1", "d2", "d3"))
    assert {lim for lim, _ in seen} == {chat_tools.PER_PAPER}


def test_the_tool_budget_covers_one_read_per_selected_paper():
    assert chat_coverage.tool_cap(6, frozenset({"a"})) == 6
    assert chat_coverage.tool_cap(6, frozenset(f"d{i}" for i in range(10))) == 12
    assert (
        chat_coverage.tool_cap(6, frozenset(f"d{i}" for i in range(20)))
        == 22
    )


def test_ten_papers_answer_with_every_paper_named_and_the_coverage_line(
    monkeypatch, tmp_path
):
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    ids = _three(client)
    calls: list = []
    _scripted(
        monkeypatch,
        [
            _tool_use(
                "search_documents", {"query": "zeta service", "document_ids": ids}
            ),
            _text("Found it."),
        ],
        calls,
    )
    convo = client.post("/api/conversations").json()["id"]
    r = client.post(
        f"/api/conversations/{convo}/ask",
        json={
            "question": "What do these papers say about zeta service?",
            "model": "claude",
            "document_ids": ids,
        },
    )
    assert r.status_code == 200, r.text
    first = json.dumps(calls[0]["messages"][0])
    assert (
        all(i in first for i in ids) and "still being read in" in first
    )  # every paper named, its state said
    got = r.json()
    cov = got["paper_coverage"]
    assert (cov["selected"], cov["read"], cov["processing"]) == (3, 2, 1)
    assert cov["sentence"] == "Read 2 of 3 selected papers; 1 still processing."
    assert cov["sentence"] in got["notices"] and got["review_offer"] == []
    stored = (
        db.connect()
        .execute(
            "SELECT payload FROM messages WHERE id = ?",
            (got["assistant_message"]["id"],),
        )
        .fetchone()
    )
    assert (
        json.loads(stored["payload"])["paper_coverage"] == cov
    )  # a reopened answer keeps the line


def test_review_these_offers_the_real_review_for_each_selected_paper(
    monkeypatch, tmp_path
):
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    ids = _three(client)
    _scripted(
        monkeypatch,
        [
            _tool_use("search_documents", {"query": "scope", "document_ids": ids}),
            _text("Found it."),
        ],
    )
    convo = client.post("/api/conversations").json()["id"]
    got = client.post(
        f"/api/conversations/{convo}/ask",
        json={
            "question": "Review these papers",
            "model": "claude",
            "document_ids": ids,
        },
    ).json()
    assert sorted(o["document_id"] for o in got["review_offer"]) == sorted(ids)
    assert chat_coverage.REVIEW_WORDS in got["notices"]
    reopened = client.get(f"/api/conversations/{convo}").json()["messages"][-1]  # a reopened answer keeps the offer
    assert sorted(o["document_id"] for o in reopened["review_offer"]) == sorted(ids)
    assert reopened["paper_coverage"]["selected"] == 3


def test_one_selected_paper_is_unchanged(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    one = _upload(
        client,
        "INV-PAPER-9.pdf",
        ["9.1 Scope", "The invented item 9 is rated for zeta service."],
    )
    calls: list = []
    _scripted(
        monkeypatch,
        [_tool_use("search_documents", {"query": "zeta"}), _text("Found it.")],
        calls,
    )
    convo = client.post("/api/conversations").json()["id"]
    got = client.post(
        f"/api/conversations/{convo}/ask",
        json={
            "question": "What does it say about zeta service?",
            "model": "claude",
            "document_ids": [one],
        },
    ).json()
    assert got.get(
        "paper_coverage"
    ) is None and "THE READER SELECTED" not in json.dumps(calls[0]["messages"][0])
    assert settings.chat_tool_max_calls == 6
