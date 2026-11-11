"""Standing approval (#1584 comment 6806441133, to be confirmed by the owner, order 12 N3): the rule books the AI reviewer asks rules from join the approved list
with the paper, even when nothing cited them; the register and a blocked hash never do. Invented documents, no Claude call."""

from __future__ import annotations

import json

import pytest

import tests.test_agent_review_job as job_tests
from app import (
    claude_approved,
    claude_auto_approve,
    claude_spend,  # noqa: F401
    db,
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

_REAL_SCOPE = claude_auto_approve._scope_of_run


@pytest.fixture(autouse=True)
def _everything_in_scope(monkeypatch):
    """Direct calls of the hook: the caller may read every document (the scope tests put the real function back)."""
    monkeypatch.setattr(
        claude_auto_approve,
        "_scope_of_run",
        lambda _rid: frozenset(
            r["id"] for r in db.connect().execute("SELECT id FROM documents")
        ),
    )


def _approved(sha):
    return [r for r in _rows_for(sha) if r["status"] == "approved"]


def test_a_rule_book_nothing_cited_is_approved_with_the_paper():
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_B, role=STANDARD)
    _set_list((SHA_A, "approved"))
    assert (
        _refused_code([paper, book]) == "not_approved"
    )  # before: the book is not on the list, the call is refused
    claude_auto_approve.on_agent_standards(paper, [book])
    (row,) = _approved(SHA_B)
    assert row["source"] == f"auto: asked by AI review of {paper}"
    with claude_approved.carrying([paper, book]):
        assert (
            claude_approved.refusal() is None
        )  # the gate lets the run's declared documents through


def test_the_register_and_a_blocked_hash_are_never_approved_by_it():
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    register = _doc(
        "doc_reg",
        SHA_B,
        role=STANDARD,
        filename=f"Copy of {claude_approved.REGISTER_NAME_KEY}.pdf",
    )
    blocked = _doc("doc_blocked", OWNER_HASH, role=STANDARD)
    _set_list((SHA_A, "approved"))
    claude_auto_approve.on_agent_standards(paper, [register, blocked])
    assert _approved(SHA_B) == [] and _approved(OWNER_HASH) == []
    assert [r["status"] for r in _rows_for(SHA_B)] == ["blocked"]
    assert _refused_code([paper, register]) == "not_approved"
    assert _refused_code([paper, blocked]) == "not_approved"


def test_a_paper_that_does_not_qualify_brings_no_rule_book():
    paper = _doc(
        "doc_paper", SHA_A, role=STANDARD
    )  # a standard is not a paper under review
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
    assert [r["status"] for r in _rows_for(SHA_B)] == [
        "pending_owner"
    ]  # not rewritten, not approved over


def test_an_unknown_book_or_an_empty_list_is_harmless():
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    claude_auto_approve.on_agent_standards(paper, ["doc_nobody", None, ""])
    claude_auto_approve.on_agent_standards("doc_nobody", ["doc_nobody"])
    claude_auto_approve.on_agent_standards(paper, [])
    rows = json.loads(claude_approved.list_path().read_text())["documents"]
    assert [r["document_id"] for r in rows] == [
        "doc_paper"
    ]  # the paper only (set by its role); no book, no stranger


@pytest.mark.usefixtures("job_world")
def test_the_runner_hands_the_books_of_its_items_to_the_approval(monkeypatch):
    """The call site: the job's runner names the books of the items it will ask, once, before its first call."""
    seen = []
    monkeypatch.setattr(
        claude_auto_approve,
        "on_agent_standards",
        lambda paper, books: seen.append((paper, sorted(set(books)))),
    )
    run_id, job_id = job_tests.start()
    job_tests.run_job(job_id)
    assert seen == [(s.PAPER, [s.STD])]
    assert run_id


def test_a_document_that_is_not_a_rule_book_is_not_approved_by_the_hook():
    """An invented rule row that points at a non-standard document (a mis-attributed item)."""
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    other = _doc("doc_other", SHA_B, role="SUPPORTING_DOCUMENT")
    bare = _doc("doc_bare", SHA_C)  # no role at all
    _set_list((SHA_A, "approved"))
    claude_auto_approve.on_agent_standards(paper, [other, bare])
    assert _approved(SHA_B) == [] and _approved(SHA_C) == []
    assert (
        _refused_code([paper, other]) == "not_approved"
    )  # the gate refuses it, as before


def test_a_book_outside_the_callers_scope_is_not_approved(monkeypatch):
    """Items can come from a reused run chosen under another caller's scope: intersection, never union (rule 5)."""
    from app import review_jobs

    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    inside = _doc("doc_in", SHA_B, role=STANDARD)
    outside = _doc("doc_out", SHA_C, role=STANDARD)
    run_id, _job = review_jobs.enqueue(
        paper, allowed_document_ids=frozenset({paper}), requested_by=None
    )
    monkeypatch.setattr(claude_auto_approve, "_scope_of_run", _REAL_SCOPE)
    monkeypatch.setattr(
        review_jobs, "_scope_of", lambda _user: frozenset({paper, inside})
    )
    _set_list((SHA_A, "approved"))
    claude_auto_approve.on_agent_standards(paper, [inside, outside], run_id)
    assert len(_approved(SHA_B)) == 1 and _approved(SHA_C) == []
    assert _refused_code([paper, outside]) == "not_approved"


def test_a_review_whose_scope_cannot_be_found_approves_nothing(monkeypatch):
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_B, role=STANDARD)
    monkeypatch.setattr(claude_auto_approve, "_scope_of_run", _REAL_SCOPE)
    claude_auto_approve.on_agent_standards(paper, [book])  # no run id, none in force
    claude_auto_approve.on_agent_standards(paper, [book], "no-such-run")
    assert _approved(SHA_B) == []


@pytest.mark.parametrize("block_file", ["missing", "empty"])
def test_switch_on_with_no_block_file_or_an_empty_one_refuses_every_call_and_approves_nothing(
    block_file,
):
    paper = _doc("doc_paper", SHA_A, role=SUBMITTAL)
    book = _doc("doc_book", SHA_B, role=STANDARD)
    _set_list((SHA_A, "approved"), (SHA_B, "approved"))  # even an owner-approved list
    path = claude_approved.block_file_path()
    if block_file == "missing":
        path.unlink()
    else:
        path.write_text(json.dumps({"blocked_sha256": []}), encoding="utf-8")
    other = _doc("doc_other", SHA_C, role=STANDARD)
    claude_auto_approve.on_agent_standards(paper, [other])
    assert _approved(SHA_C) == []  # fail closed: nothing added
    for ids in ([paper], [book], [paper, book], [paper, other]):
        assert _refused_code(ids) == "not_approved"
