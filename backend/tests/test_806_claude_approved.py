"""#806 S3: the Claude lane refuses a prompt that carries a document the owner
has not approved - and a prompt whose caller declared nothing (fail closed).

The check sits where EVERY Claude call reserves its cost before it is sent
(`claude_spend.reserve_all`): the `metered` lane and the `ClaudeProvider` lane
both. A document is identified by its file's sha256, listed in
`<data_dir>/claude_approved_documents.json` (outside git, owner-edited).
Invented documents only.
"""
from __future__ import annotations

import json

import pytest

from app import claude_approved, claude_spend, db, submittal_review
from app.config import Settings, settings

NOW = "2026-10-11T00:00:00Z"


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "s3.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc, sha in (("doc_a", "aa" * 32), ("doc_b", "bb" * 32)):
            conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                         "uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)", (doc, f"{doc}.pdf", sha, f"{doc}.pdf", NOW))
    yield
    db.reset_connection()


def _approve(*entries):
    claude_approved.list_path().write_text(json.dumps({"documents": [
        {"sha256": sha, "status": status, "label": "invented", "approved_by": "owner", "approved_on": "2026-10-11"}
        for sha, status in entries]}), encoding="utf-8")


def _reserve(step="s3-test"):
    return claude_spend.reserve(step, 0.01, model="claude-sonnet-5")


# ---------------------------------------------------------------- the guard

def test_the_guard_ships_on_and_is_off_only_in_the_suite():
    assert Settings.model_fields["claude_approved_list_enforced"].default is True


def test_a_caller_that_declared_nothing_is_refused_before_anything_is_held():
    _approve(("aa" * 32, "approved"))
    with pytest.raises(claude_spend.DocumentNotApproved) as caught:
        _reserve()
    assert caught.value.code == claude_approved.UNDECLARED
    assert not [e for e in claude_spend.entries() if e.get("reserved")]      # nothing held


def test_an_approved_document_passes_and_an_unapproved_one_refuses_the_whole_prompt():
    _approve(("aa" * 32, "approved"))
    with claude_approved.carrying(["doc_a"]):
        held = _reserve()
    assert held.step == "s3-test"
    with claude_approved.carrying(["doc_a", "doc_b"]):
        with pytest.raises(claude_spend.DocumentNotApproved) as caught:
            _reserve()
    assert caught.value.code == claude_approved.NOT_APPROVED
    assert "doc_b" in str(caught.value) and "doc_a" not in str(caught.value)
    assert "doc_b.pdf" not in str(caught.value)                             # ids, never a file name


def test_chat_consent_replaces_history_scope_for_one_request_only():
    # User consent for doc_a must not inherit doc_b from older chat history,
    # and must not make a later non-chat call to doc_b pass the owner list.
    with claude_approved.carrying(["doc_b"]):
        with claude_approved.per_request_consent(["doc_a"]):
            assert claude_approved.carried() == {"doc_a"}
            assert _reserve().step == "s3-test"
        assert claude_approved.carried() == {"doc_b"}
        with pytest.raises(claude_spend.DocumentNotApproved):
            _reserve()


def test_a_missing_or_empty_or_broken_list_approves_nothing():
    for write in (None, "{}", "not json"):
        if write is not None:
            claude_approved.list_path().write_text(write, encoding="utf-8")
        with claude_approved.carrying(["doc_a"]):
            with pytest.raises(claude_spend.DocumentNotApproved):
                _reserve()


def test_a_pending_entry_is_not_an_approval():
    _approve(("aa" * 32, "pending_owner"))
    with claude_approved.carrying(["doc_a"]):
        with pytest.raises(claude_spend.DocumentNotApproved):
            _reserve()


def test_a_document_the_library_does_not_hold_is_refused():
    _approve(("aa" * 32, "approved"))
    with claude_approved.carrying(["doc_zzz"]):
        with pytest.raises(claude_spend.DocumentNotApproved) as caught:
            _reserve()
    assert caught.value.code == claude_approved.UNKNOWN_DOCUMENT


def test_a_prompt_declared_to_carry_no_document_passes():
    with claude_approved.carrying(()):
        assert _reserve().step == "s3-test"


def test_nested_declarations_add_and_end_with_their_block():
    _approve(("aa" * 32, "approved"))
    with claude_approved.carrying(["doc_a"]):
        with claude_approved.carrying(["doc_b"]):
            assert claude_approved.carried() == {"doc_a", "doc_b"}
            with pytest.raises(claude_spend.DocumentNotApproved):
                _reserve()
        assert claude_approved.carried() == {"doc_a"}
        _reserve()
    assert claude_approved.carried() is None


def test_a_refusal_is_a_cap_style_stop_and_is_written_to_the_ledger_at_no_cost():
    with claude_approved.carrying(["doc_b"]):
        with pytest.raises(claude_spend.BudgetExceeded) as caught:           # callers that stop on a cap stop on this
            _reserve("datasheet-ai-reader")
    assert caught.value.count_key == "document_not_approved"
    line = claude_spend.entries()[-1]
    assert line["refused"] == claude_approved.NOT_APPROVED and line["documents"] == ["doc_b"]
    assert line["step"] == "datasheet-ai-reader" and line["cost_usd"] == 0


def test_the_metered_lane_never_calls_the_transport_for_an_unapproved_document():
    sent = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        return {"model": "m", "stop_reason": "end_turn", "content": [], "usage": {}}
    call = claude_spend.metered(send, "s3-test")
    body = {"model": "claude-sonnet-5", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}]}
    with claude_approved.carrying(["doc_b"]):
        with pytest.raises(claude_spend.DocumentNotApproved):
            call("https://api.anthropic.com/v1/messages", headers={}, body=body, timeout=1)
    assert sent == []
    _approve(("bb" * 32, "approved"))
    with claude_approved.carrying(["doc_b"]):
        call("https://api.anthropic.com/v1/messages", headers={}, body=body, timeout=1)
    assert len(sent) == 1


# ---------------------------------------------------------------- the list's audit trail

def test_a_change_to_the_list_is_written_to_the_audit_table_once():
    assert claude_approved.sync_audit() is False                             # no list, no history: nothing to say
    _approve(("aa" * 32, "approved"), ("bb" * 32, "pending_owner"))
    assert claude_approved.sync_audit() is True
    assert claude_approved.sync_audit() is False                             # unchanged: not written twice
    row = db.connect().execute("SELECT actor_username, detail FROM audit_events WHERE action = ?",
                               (claude_approved.AUDIT_ACTION,)).fetchone()
    assert row["actor_username"] == "file edit (owner)"
    assert json.loads(row["detail"]) == {"entries_by_status": {"approved": 1, "pending_owner": 1}}
    _approve(("aa" * 32, "approved"), ("bb" * 32, "approved"))
    assert claude_approved.sync_audit() is True
    assert claude_approved.counts() == {"approved": 2}


# ---------------------------------------------------------------- what the reader is told

def test_the_reader_is_told_it_is_the_approved_list_not_the_spending_cap():
    from app import chat_model
    refused = claude_spend.DocumentNotApproved(claude_approved.NOT_APPROVED, "1 of 1 document(s) ... (ids: doc_b)")
    cap = claude_spend.BudgetExceeded("the per-step cap")
    assert claude_spend.refusal_words(refused, "the cap words").startswith(claude_spend.NOT_APPROVED_WORDS)
    assert "doc_b" in claude_spend.refusal_words(refused, "the cap words")
    assert claude_spend.refusal_words(cap, "the cap words") == "the cap words (the per-step cap)"
    assert chat_model.fallback_words(refused) == (
        "a document here is not approved for the cloud model; answered locally")
    assert chat_model.fallback_words(cap) == "the Claude spending cap would be exceeded"

