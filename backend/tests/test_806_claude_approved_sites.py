"""#806 S3 at the call sites: each place that can call Claude declares the
documents its prompt carries, so the guard (`test_806_claude_approved.py`)
has something to check - and a site nobody listed fails a test here.

Invented documents and fake transports only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import claude_approved, claude_spend, datasheets, db
from app.config import settings
from tests.test_datasheet_ai import (AGREE, ROWS, _claude_env, _datasheet_pdf, _ingest,  # noqa: F401
                                     temp_storage)

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def guard_on(monkeypatch, temp_storage):  # noqa: F811
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)


def _approve(document_id):
    sha = db.connect().execute("SELECT sha256 FROM documents WHERE id = ?", (document_id,)).fetchone()["sha256"]
    claude_approved.list_path().write_text(json.dumps({"documents": [
        {"sha256": sha, "document_id": document_id, "status": "approved"}]}), encoding="utf-8")


# ---------------------------------------------------------------- the datasheet reader, end to end

def test_an_unapproved_datasheet_is_not_sent_and_the_code_reading_stands(tmp_path, monkeypatch):
    sent = _claude_env(monkeypatch)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    result = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert sent == []                                              # nothing left the machine
    assert result["facts"] == 4                                    # the code readers' facts are all there
    assert result["ai_reader"]["stopped"] == "document_not_approved"
    refused = [e for e in claude_spend.entries() if e.get("refused")]
    assert refused and refused[0]["documents"] == [doc] and refused[0]["cost_usd"] == 0


def test_an_approved_datasheet_is_read_by_the_ai(tmp_path, monkeypatch):
    sent = _claude_env(monkeypatch)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")
    doc = _ingest(_datasheet_pdf(tmp_path / "d.pdf", ROWS))
    _approve(doc)
    result = datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert len(sent) == 2 and result["ai_reader"]["stopped"] is None


# ---------------------------------------------------------------- a review declares its documents

def _review(tmp_path):
    from app import submittal_review
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc in ("sub", "std_in", "std_out"):
            conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                         "uploaded_at) VALUES (?,?,?,1,?,'ready',1,'2026-10-11T00:00:00Z')",
                         (doc, f"{doc}.pdf", f"sha-{doc}", f"{doc}.pdf"))
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                     " VALUES ('run','sub','pending','2026-10-11T00:00:00Z','2026-10-11T00:00:00Z')")
        for std, included in (("std_in", 1), ("std_out", 0)):
            conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
                         "selection_method,included,created_at) VALUES (?,?,?,'referenced',?,'2026-10-11T00:00:00Z')",
                         (f"a-{std}", "run", std, included))
    return "run"


def test_a_reviews_documents_are_its_submittal_and_the_standards_applied(tmp_path):
    run = _review(tmp_path)
    assert claude_approved.review_documents(run) == ["sub", "std_in"]
    assert claude_approved.review_documents("no-such-run") == []

    @claude_approved.for_review
    def step(review_run_id, extra):
        return claude_approved.carried(), extra
    assert step(run, 7) == (frozenset({"sub", "std_in"}), 7)
    assert claude_approved.carried() is None                       # and it ends with the call


def test_the_comparison_and_the_review_steps_run_under_the_reviews_declaration(tmp_path, monkeypatch):
    from app import ai_engineering_check, claude_recheck, comparison, crs_wording
    run = _review(tmp_path)
    monkeypatch.setattr(comparison, "_run_comparison", lambda *a, **k: claude_approved.carried())
    assert comparison.run_comparison(run, allowed_document_ids=frozenset()) == {"sub", "std_in"}
    for fn in (crs_wording.word_run, claude_recheck.recheck_run, ai_engineering_check.run_check):
        inner = fn.__wrapped__                                     # `for_review` wraps each of them
        assert inner.__name__ == fn.__name__


# ---------------------------------------------------------------- chat declares the conversation

def test_a_chat_turn_declares_every_document_the_conversation_referred_to(monkeypatch):
    from app import chat
    with db.connect() as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES"
                     " ('c1','t','2026-10-11T00:00:00Z','2026-10-11T00:00:00Z')")
        for n, payload in enumerate(({"passages": [{"document_id": "doc_x"}]},
                                     {"derived_document_ids": ["doc_y"]}, {})):
            conn.execute("INSERT INTO messages (id,conversation_id,ordinal,role,text,payload,created_at)"
                         " VALUES (?,?,?,?,?,?, '2026-10-11T00:00:00Z')",
                         (f"m{n}", "c1", n, "assistant", "x", json.dumps(payload)))
    assert chat.conversation_document_ids("c1") == {"doc_x", "doc_y"}
    turn = chat._declaring_the_conversation(lambda cid, question, **kw: claude_approved.carried())
    assert turn("c1", "a question", allowed_document_ids=frozenset()) == {"doc_x", "doc_y"}
    assert chat.ask.__wrapped__.__name__ == "ask"                  # the real turn is wrapped the same way


def test_a_general_answer_outside_a_conversation_is_a_declared_document_free_prompt(monkeypatch):
    from app import chat_answers, chat_model
    seen = []
    monkeypatch.setattr(chat_model, "generate",
                        lambda *a, **k: seen.append(claude_approved.carried()) or {"response": "ok"})
    chat_answers._generate("system", "prompt", 0.0, None)
    assert seen == [frozenset()]
    with claude_approved.carrying(["doc_x"]):                      # inside a conversation it adds nothing
        chat_answers._generate("system", "prompt", 0.0, None)
    assert seen[-1] == frozenset({"doc_x"})


# ---------------------------------------------------------------- nobody is missed

#: Every app module that can start a Claude call, and WHO declares for it:
#: itself (it names `claude_approved`), or the one caller named here.
DECLARED_BY = {
    "ai_engineering_check.py": "ai_engineering_check.py",
    "answer.py": "answer.py",
    "answerability.py": "answerability.py",
    "applicability.py": "applicability.py",
    "applicability_reasoning.py": "applicability.py",      # called per standard from there
    "chat_answers.py": "chat_answers.py",
    "chat_claude_first.py": "chat_claude_first.py",
    "chat_model.py": "chat.py",                             # the engine call; chat.ask and its callers declare
    "claude_api.py": "claude_api.py",
    "claude_datasheet.py": "claude_datasheet.py",
    "claude_recheck.py": "claude_recheck.py",
    "claude_selection.py": "claude_api.py",                 # the route builds the call
    "comparison.py": "comparison.py",                       # MATCH_ENGINE=claude, inside run_comparison
    "crs_wording.py": "crs_wording.py",
    "datasheet_ai.py": "datasheets.py",                     # read per document from extract_facts
    "field_naming.py": "comparison.py",                     # inside run_comparison
    "rule_eval.py": "rule_eval.py",
    "vision_reader.py": "datasheets.py",                    # read per page from extract_facts
}
#: The lane itself and its plumbing: they send what a caller declared.
THE_LANE = {"reasoning_provider.py", "claude_spend.py", "reader_transport.py", "reader_api.py",
            "claude_budget.py", "claude_approved.py"}
_STARTS_A_CALL = re.compile(r"get_provider\(|ClaudeProvider\(|claude_spend\.metered\(|reader_transport\.transport\(")


def test_every_module_that_can_call_claude_has_a_named_declarer():
    callers = {p.name for p in APP.glob("*.py")
               if p.name not in THE_LANE and _STARTS_A_CALL.search(p.read_text(encoding="utf-8"))}
    assert callers - set(DECLARED_BY) == set(), (
        f"a new module can start a Claude call: {sorted(callers - set(DECLARED_BY))}. Declare the documents "
        "its prompt carries (`claude_approved.carrying`) and add it to DECLARED_BY.")
    for module, declarer in DECLARED_BY.items():
        assert "claude_approved" in (APP / declarer).read_text(encoding="utf-8"), (
            f"{declarer} is named as the declarer for {module} and never mentions claude_approved")
