"""A refusal can be audited: each point the claim checker removed is recorded
with its reason (stored with the answer, never shown as an answer). Found
2026-10-06 on the real app: a Claude answer was refused as "0 of 1 points
found" and nothing said what was removed or why. Invented documents only."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import answer, db
from app.main import app
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse
from tests.test_chat_claude_first import _on, _scripted, _text, _tool_use

pytestmark = pytest.mark.usefixtures("temp_storage")

SRC = [{"chunk_id": "c1", "document_id": "d", "filename": "STD-A-001.pdf", "page_start": 5,
        "page_end": 5, "section": "4.1", "score": 1.0,
        "text": "4.1 Abbreviations ZQAT Zeta Quench Anneal Treatment"}]


def test_each_removed_point_is_recorded_with_its_reason():
    dropped: list[dict] = []
    text, _v, _c, removed = answer.verify_claims(
        'ZQAT is a treatment [S1].\n\nLet me confirm directly.\n\n'
        'ZQAT means Zeta Quench Anneal Treatment [S1 "ZQAT Zeta Quench Anneal Treatment"].',
        SRC, dropped=dropped)
    assert text == "ZQAT means Zeta Quench Anneal Treatment [S1]."
    whys = {d["why"] for d in dropped}
    assert whys == {"quoted words not found on the cited page",
                    "promises an action instead of answering"}, dropped
    assert dropped[0]["text"].startswith("ZQAT is a treatment")
    # nothing is recorded when nothing is removed, and the default is unchanged
    again: list[dict] = []
    answer.verify_claims('ZQAT means Zeta Quench Anneal Treatment [S1 "ZQAT Zeta Quench Anneal Treatment"].',
                         SRC, dropped=again)
    assert again == []
    assert answer.verify_claims("plain words only.", SRC)[3] == 0


def test_a_refused_claude_answer_stores_what_was_removed(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    upload(client)
    _scripted(monkeypatch, [_tool_use("search_documents", {"query": "coating system"}),
                            _text("Coating system 1 has an NDFT of 999 um [S1].")])
    convo = client.post("/api/conversations").json()["id"]
    r = client.post(f"/api/conversations/{convo}/ask", json={"question": "what is the NDFT"})
    assert r.status_code == 200, r.text
    row = db.connect().execute("SELECT payload FROM messages WHERE id = ?",
                               (r.json()["assistant_message"]["id"],)).fetchone()
    payload = json.loads(row["payload"] or "{}")
    assert payload.get("removed_points"), payload.keys()
    assert "999" in payload["removed_points"][0]["text"]


def test_when_every_claude_point_fails_the_document_is_still_quoted(monkeypatch, tmp_path):
    """THE CLASS FIX (audit 118; mutation M2042): Claude's only point has a
    quote that is not word for word on the page, so the checker removes it.
    That must not end in a refusal when the document answers the question:
    the existing pipeline answers from the passages it quotes."""
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    upload(client)
    _scripted(monkeypatch, [_tool_use("search_documents", {"query": "NDFT coating system"}),
                            _text('The NDFT is 280 um [S1 "nominal dry film of two hundred and eighty"].')])
    convo = client.post("/api/conversations").json()["id"]
    r = client.post(f"/api/conversations/{convo}/ask",
                    json={"question": "what is the NDFT for coating system no. 1", "tier": "extract"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"], body
    assert body["answer_type"] != "insufficient_evidence", body["answer_type"]
    assert "two hundred and eighty" not in body["answer"]
    assert any("None of Claude's own points" in n for n in body.get("notices") or []), body.get("notices")
    row = db.connect().execute("SELECT payload FROM messages WHERE id = ?",
                               (body["assistant_message"]["id"],)).fetchone()
    assert json.loads(row["payload"] or "{}").get("removed_points")
