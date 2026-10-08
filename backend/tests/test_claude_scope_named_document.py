"""Claude lane scope: a document the question NAMES narrows what Claude's tools
may read, exactly as it narrows the old pipeline (CLAUDE.md rule 5: scope only
ever narrows). Found 2026-10-06 on the real app: "What does <standard> say
about <abbreviation>" searched every standard in Claude mode.

No network: the Claude transport is faked. Invented documents only.
"""
from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import chat, db
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app
from tests.test_chat import temp_storage  # noqa: F401 - the fixture is autouse
from tests.test_chat_claude_first import _on, _scripted, _text, _tool_use

pytestmark = pytest.mark.usefixtures("temp_storage")


def _upload(client, filename: str, lines: list[str]) -> str:
    path = settings.data_dir / filename
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post("/api/documents",
                             files={"file": (filename, fh, "application/pdf")}).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def test_scope_unit_named_document_only_narrows():
    allowed = frozenset({"a", "b", "c"})
    named = {"document_id": "a", "scope_ids": None}
    assert chat.claude_scope(allowed, document_id=None, picked=False, understood=named) == frozenset({"a"})
    # a named document the reader cannot read never widens or leaks
    assert chat.claude_scope(allowed, document_id=None, picked=False,
                             understood={"document_id": "zz"}) == allowed
    several = {"document_id": None, "scope_ids": ["a", "c", "zz"]}
    assert chat.claude_scope(allowed, document_id=None, picked=False,
                             understood=several) == frozenset({"a", "c"})
    # an @-picked set always wins; a selected document wins over a name
    assert chat.claude_scope(frozenset({"b"}), document_id=None, picked=True,
                             understood=named) == frozenset({"b"})
    assert chat.claude_scope(allowed, document_id="c", picked=False,
                             understood=named) == frozenset({"c"})
    assert chat.claude_scope(allowed, document_id=None, picked=False, understood=None) == allowed


def test_a_question_naming_a_standard_limits_claudes_search_to_it(monkeypatch, tmp_path):
    _on(monkeypatch, tmp_path)
    client = TestClient(app)
    named = _upload(client, "STD-A-001.pdf", [
        "4.1 Abbreviations", "ZQAT Zeta Quench Anneal Treatment",
        "ZQAT shall be recorded on the inspection sheet."])
    other = _upload(client, "STD-B-002.pdf", [
        "7.2 Heat work", "ZQAT shall be done after welding and the zeta quench anneal",
        "treatment record kept for every batch of the supplied parts."])
    assert named != other
    _scripted(monkeypatch, [_tool_use("search_documents", {"query": "ZQAT"}), _text("Found it.")])
    convo = client.post("/api/conversations").json()["id"]
    r = client.post(f"/api/conversations/{convo}/ask",
                    json={"question": "What does STD-A-001 say about ZQAT"})
    assert r.status_code == 200, r.text
    row = db.connect().execute("SELECT payload FROM messages WHERE id = ?",
                               (r.json()["assistant_message"]["id"],)).fetchone()
    import json
    ids = {p["document_id"] for p in (json.loads(row["payload"] or "{}").get("passages") or [])}
    assert ids == {named}, ids
