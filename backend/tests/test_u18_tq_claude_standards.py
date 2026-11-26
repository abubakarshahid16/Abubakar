"""A Claude draft of a technical query may also send the HELD STANDARDS of the query's kept, current evidence (owner, 26 Nov 2026 23:00
PKT: "Yes. Claude may read standards passages to write a query reply, same as it does for reviews"; CLAUDE.md rule 1, PR #1932): a
company standard by role, or an unroled public standard, that the caller may read, beside the contracts the engineer chooses. Never a
submittal or any other document; a standard the caller may not read is counted, never named; every file sent is in the consent record
first. The local draft is unchanged. Invented documents; no model, no network."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app import db
from app import technical_query_claude as C
from app.access import AccessScope
from app.api import technical_queries as api
from app.config import settings
from tests.test_tq_g_feature_off import (  # noqa: F401 - storage: the autouse database fixture
    REVIEWER,
    draft_ready,
    storage,
)

QUOTE = "q"


def _standard(
    doc: str, role: str | None, number: str, query_id: str, evidence_id: str
) -> None:
    """A held standard (role COMPANY_STANDARD, or no role and a public number) with one kept, current passage in the query."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,'ready','x')",
            (
                doc,
                f"{number}.pdf",
                doc.encode().hex().ljust(64, "0")[:64],
                1,
                f"{number}.pdf",
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO document_classification(document_id,document_role,document_number,suggested_by) VALUES (?,?,?,'rules')",
            (doc, role, number),
        )
        conn.execute(
            "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,supersession_state,evidence_state,"
            "created_at) VALUES (?,?,?,1,1,?,?,'current','verified','x')",
            (evidence_id, query_id, doc, QUOTE, f"h-{evidence_id}"),
        )


def _claude(monkeypatch):
    monkeypatch.setattr(settings, "technical_query_draft_engine", "claude")
    sent = []

    def answer(question, **kwargs):
        sent.append(kwargs.get("allowed_document_ids"))
        return {"answer_type": "generated", "answer": "It applies [S1].", "cited": [1], "model": "claude-synthetic",
                "passages": [{"document_id": "d1", "page_start": 1, "page_end": 1, "text": QUOTE}]}  # fmt: skip

    monkeypatch.setattr("app.answer.answer", answer)
    return sent


def test_a_claude_draft_also_sends_the_held_standards_of_the_kept_evidence_and_records_them_first(
    monkeypatch,
):
    item, _scope = draft_ready(monkeypatch, docs=("d1",))
    _standard("std-co", "COMPANY_STANDARD", "ZQ-STD-001", item["id"], "es1")
    scope = AccessScope("u1", frozenset({"d1", "std-co"}), capabilities=REVIEWER)
    sent = _claude(monkeypatch)
    drafted = api.generate_query_draft(
        item["id"], scope, api.GenerateDraftIn(engine="claude", document_ids=["d1"])
    )
    assert sent == [
        frozenset({"d1", "std-co"})
    ]  # the engineer's contract and the held standard, nothing else
    with db.connect() as conn:
        assert [e["document_ids"] for e in C.entries(conn, item["id"])] == [
            ["d1", "std-co"]
        ]  # every file sent, ids only
    assert drafted["drafts"][-1]["model"] == "claude-synthetic"


def test_a_held_standard_alone_may_be_sent_and_a_standard_may_be_ticked(monkeypatch):
    item, _scope = draft_ready(monkeypatch, docs=("d1",))
    _standard(
        "std-pub", None, "ISO 1234", item["id"], "es2"
    )  # an unroled public standard
    scope = AccessScope("u1", frozenset({"d1", "std-pub"}), capabilities=REVIEWER)
    sent = _claude(monkeypatch)
    api.generate_query_draft(
        item["id"],
        scope,
        api.GenerateDraftIn(engine="claude", document_ids=["std-pub"]),
    )
    assert sent == [frozenset({"std-pub"})]


def test_a_standard_the_caller_may_not_read_is_not_sent_and_counted_never_named(
    monkeypatch,
):
    item, _scope = draft_ready(monkeypatch, docs=("d1",))
    _standard("std-hidden", "COMPANY_STANDARD", "ZQ-STD-SECRET", item["id"], "es3")
    scope = AccessScope("u1", frozenset({"d1"}), capabilities=REVIEWER)
    sent = _claude(monkeypatch)
    drafted = api.generate_query_draft(
        item["id"], scope, api.GenerateDraftIn(engine="claude", document_ids=["d1"])
    )
    assert sent == [frozenset({"d1"})]
    assert (
        drafted["drafts"] == [] and drafted["source_access_revoked"]
    )  # the page hides drafts from a caller who cannot read all evidence
    with db.connect() as conn:
        marks = json.loads(
            conn.execute(
                "SELECT unresolved_json FROM query_drafts WHERE query_id=?",
                (item["id"],),
            ).fetchone()[0]
        )
    assert "1 held standard(s) you may not read were not sent." in marks
    assert not any("ZQ-STD-SECRET" in m or "std-hidden" in m for m in marks)
    with pytest.raises(HTTPException) as refused:  # nor may it be ticked
        api.generate_query_draft(
            item["id"],
            scope,
            api.GenerateDraftIn(engine="claude", document_ids=["std-hidden"]),
        )
    assert "not verified, current evidence of this query that you may read" in str(
        refused.value.detail
    )


def test_the_local_draft_is_unchanged_it_never_asks_claude(monkeypatch):
    item, _scope = draft_ready(monkeypatch, docs=("d1",))
    _standard("std-co", "COMPANY_STANDARD", "ZQ-STD-001", item["id"], "es1")
    scope = AccessScope("u1", frozenset({"d1", "std-co"}), capabilities=REVIEWER)
    seen = []
    monkeypatch.setattr("app.answer.answer", lambda q, **k: seen.append(k.get("model")) or {
        "answer_type": "generated", "answer": "It applies [S1].", "cited": [1], "model": "local-synthetic",
        "passages": [{"document_id": "d1", "page_start": 1, "page_end": 1, "text": QUOTE}]})  # fmt: skip
    api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="local"))
    assert seen == ["local"]
    with db.connect() as conn:
        assert (
            C.entries(conn, item["id"]) == []
        )  # no consent record: nothing went to Claude
