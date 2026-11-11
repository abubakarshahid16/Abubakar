"""Standing approval (owner 16.7 point 3, order 12 N3): the rule books the AI reviewer asks rules from join the approved list
with the paper, even when nothing cited them; the register and a blocked hash never do. Invented documents, no Claude call."""

from __future__ import annotations

import json

import tests.test_agent_review_job as job_tests
from app import (
    claude_approved,
    claude_auto_approve,
    claude_spend,  # noqa: F401
    )
from app.config import settings
from tests import agent_review_support as s
from tests.test_1584_claude_auto_approve import (  # noqa: F401  (the autouse world is the one of #1584's tests)
    OWNER_HASH,
    SHA_A,
    SHA_B,
    SHA_C,
    STANDARD,
    SUBMITTAL,
    _doc,
    _refused_code,
    _rows_for,
    _set_list,
    world,
)
from tests.test_agent_review_job import world as job_world  # noqa: F401


def _approved(sha):
    return [r for r in _rows_for(sha) if r["status"] == "approved"]


def test_a_rule_book_nothing_cited_is_approved_with_the_paper():
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_B, role=STANDARD)
    _set_list((SHA_A, "approved"))
    assert _refused_code([paper, book]) == "not_approved"  # before: the book is not on the list, the call is refused
    claude_auto_approve.on_agent_standards(paper, [book])
    (row,) = _approved(SHA_B)
    assert row["source"] == f"auto: asked by AI review of {paper}"
    with claude_approved.carrying([paper, book]):
        assert claude_approved.refusal() is None  # the gate lets the run's declared documents through


def test_the_register_and_a_blocked_hash_are_never_approved_by_it():
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    register = _doc("doc_reg", SHA_B, role=STANDARD, filename="Engineering Deliverables.pdf")
    blocked = _doc("doc_blocked", OWNER_HASH, role=STANDARD)
    _set_list((SHA_A, "approved"))
    claude_auto_approve.on_agent_standards(paper, [register, blocked])
    assert _approved(SHA_B) == [] and _approved(OWNER_HASH) == []
    assert [r["status"] for r in _rows_for(SHA_B)] == ["blocked"]
    assert _refused_code([paper, register]) == "not_approved"
    assert _refused_code([paper, blocked]) == "not_approved"


def test_a_paper_that_does_not_qualify_brings_no_rule_book():
    paper = _doc("doc_paper", SHA_A, role=STANDARD)  # a standard is not a paper under review
    book = _doc("doc_book", SHA_B, role=STANDARD)
    claude_auto_approve.on_agent_standards(paper, [book])
    assert _rows_for(SHA_B) == []


def test_the_switch_off_writes_nothing(monkeypatch):
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_C, role=STANDARD)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    claude_auto_approve.on_agent_standards(paper, [book])
    assert not claude_approved.list_path().is_file() or _rows_for(SHA_C) == []


def test_a_pending_owner_row_is_left_as_the_owner_wrote_it():
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_B, role=STANDARD)
    _set_list((SHA_B, "pending_owner"))
    claude_auto_approve.on_agent_standards(paper, [book])
    assert [r["status"] for r in _rows_for(SHA_B)] == ["pending_owner"]  # not rewritten, not approved over


def test_an_unknown_book_or_an_empty_list_is_harmless():
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    claude_auto_approve.on_agent_standards(paper, ["doc_nobody", None, ""])
    claude_auto_approve.on_agent_standards("doc_nobody", ["doc_nobody"])
    claude_auto_approve.on_agent_standards(paper, [])
    rows = json.loads(claude_approved.list_path().read_text())["documents"]
    assert [r["document_id"] for r in rows] == ["doc_paper"]  # the paper only (set by its role); no book, no stranger


def test_the_runner_hands_the_books_of_its_items_to_the_approval(tmp_path, monkeypatch, job_world):  # noqa: F811
    """The call site: the job's runner names the books of the items it will ask, once, before its first call."""
    seen = []
    monkeypatch.setattr(claude_auto_approve, "on_agent_standards", lambda paper, books: seen.append((paper, sorted(set(books)))))
    run_id, job_id = job_tests.start()
    job_tests.run_job(job_id)
    assert seen == [(s.PAPER, [s.STD])]
    assert run_id
