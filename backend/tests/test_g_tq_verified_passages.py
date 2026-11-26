"""A technical query's draft is written from the passages its engineer verified; the answer lane's fit gate only flags them (lead-4,
26 Nov 2026: the gate refused 3 of 12 answerable questions before any model call). Invented documents, quotes and figures; the model
call is replaced (no model, no network)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import answer as answer_mod
from app import db
from app.access import AccessScope
from app.api.technical_queries import generate_query_draft
from app.config import settings
from app.technical_queries import (
    REVIEWER_CAPABILITY,
    add_evidence,
    confirm_question,
    ensure_schema,
    import_message,
    update_evidence,
)

from .test_technical_queries import envelope

QUOTE = "Each drain point shall have a valve of 50 mm."
#: A question that shares no distinctive word with the verified passage: the old lane's word gate refused it before any model call.
QUESTION = "Which isolation size applies at the lowest outlets?"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "queries.sqlite")
    monkeypatch.setattr(settings, "technical_queries_enabled", True)
    monkeypatch.setattr(settings, "answer_judge_enabled", False)
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES ('u1','u1@example.test','User One','test','2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
            (
                "doc-w",
                "invented-contract.pdf",
                "d" * 64,
                10,
                "/tmp/w.pdf",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,?)",
            ("doc-w", 3, "Front words. " + QUOTE + " More words.", 70, 1),
        )
    ensure_schema()
    yield
    db.reset_connection()


#: A forged weak-fit verdict of the answer lane's word gate (no word of the question in any passage).
WEAK = {"ok": False, "reason": "forged: no word of the question is in the passage", "coverage": 0.0, "terms": ["isolation"],
        "covered": [], "absent_from_corpus": []}  # fmt: skip


@pytest.fixture
def weak_gate(monkeypatch):
    monkeypatch.setattr(
        answer_mod, "_assess_candidates", lambda *a, **k: (dict(WEAK), 0)
    )


def _model(calls: list, text: str):
    def fake(prompt: str, timeout: float = 180.0) -> dict:
        calls.append(prompt)
        return {"response": text, "model": "invented-local", "done_reason": "stop"}

    return fake


def _verified_query() -> str:
    item, _ = import_message(envelope("weak-fit"), "u1", False, False)
    item = add_evidence(
        item["id"],
        "doc-w",
        QUOTE,
        3,
        3,
        None,
        frozenset({"doc-w"}),
        "u1",
        False,
        False,
        "u1",
    )
    update_evidence(
        item["id"],
        item["evidence"][0]["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        False,
        False,
        reviewer=True,
    )
    confirm_question(item["id"], QUESTION, "u1", False, False, "u1", reviewer=True)
    return item["id"]


def _scope() -> AccessScope:
    return AccessScope(
        "u1", frozenset({"doc-w"}), capabilities=frozenset({REVIEWER_CAPABILITY})
    )


def test_a_weak_fit_verified_passage_still_reaches_the_draft_and_is_flagged(
    monkeypatch, weak_gate
):
    calls: list = []
    monkeypatch.setattr(
        answer_mod, "_call_model", _model(calls, "The outlets take a 50 mm valve [S1].")
    )
    seen = {}
    real = answer_mod.answer

    def spy(question, **kwargs):
        seen["result"] = real(question, **kwargs)
        return seen["result"]

    monkeypatch.setattr(answer_mod, "answer", spy)
    drafted = generate_query_draft(_verified_query(), _scope())
    assert len(calls) == 1  # the model was asked: no refusal before it
    assert QUOTE in calls[0]  # with the verified passage itself
    assert (
        seen["result"]["fit"]["flag"] == "weak fit"
    )  # the weak fit is flagged, never a block
    draft = drafted["drafts"][-1]
    assert "50 mm" in draft["answer"] and draft["model"] == "invented-local"


def test_the_chat_lane_still_refuses_the_same_weak_fit_without_verified_passages(
    monkeypatch, weak_gate
):
    calls: list = []
    monkeypatch.setattr(answer_mod, "_call_model", _model(calls, "x [S1]"))
    hit = {"chunk_id": "c1", "document_id": "doc-w", "filename": "invented-contract.pdf", "section": "", "page_start": 3, "page_end": 3,
           "locator": None, "text": QUOTE, "score": 1.0, "rrf": 1.0, "rerank_score": None, "identifier_hits": []}  # fmt: skip
    monkeypatch.setattr(
        answer_mod.search_mod,
        "search",
        lambda *a, **k: {
            "hits": [hit],
            "mode": "hybrid",
            "reranked": False,
            "timings": {},
            "total": 1,
            "seconds": 0.0,
        },
    )
    got = answer_mod.answer(
        QUESTION,
        tier="generated",
        allowed_document_ids=frozenset({"doc-w"}),
        model="local",
    )
    assert (
        got["answer_type"] == "insufficient_evidence" and calls == []
    )  # same passage, same weak fit: refused, no model asked
    assert got["reason"] == WEAK["reason"]


def test_when_the_passages_do_not_hold_the_answer_the_draft_says_not_found_and_names_what_it_searched(
    monkeypatch, weak_gate
):
    calls: list = []
    monkeypatch.setattr(
        answer_mod, "_call_model", _model(calls, "INSUFFICIENT EVIDENCE")
    )
    drafted = generate_query_draft(_verified_query(), _scope())
    draft = drafted["drafts"][-1]
    assert len(calls) == 1
    assert (
        draft["answer"]
        == "Not found in the chosen papers. Searched: invented-contract.pdf page 3."
    )
    assert "do not contain the answer" in str(
        draft.get("unresolved_json") or draft.get("unresolved")
    )


def test_a_refusal_that_is_not_a_not_found_is_still_refused(monkeypatch):
    monkeypatch.setattr(
        answer_mod, "_call_model", _model([], "")
    )  # an empty reply: the model did not answer
    with pytest.raises(HTTPException) as refused:
        generate_query_draft(_verified_query(), _scope())
    assert refused.value.status_code == 409
