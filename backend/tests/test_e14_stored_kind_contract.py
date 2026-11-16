"""Order 14 lane E, review R99 finding 2 (rule 1): a kind STORED for a paper that says "contract", in any state, makes it a contract.

R99's case, rebuilt with invented data: the kind reader stored "contract" (suggested) for a contract file, the review page's confirm
then set its role to a contractor submittal, and the cover reader calls it a "datasheet" (a guess). Before the fix the contract check
read only the role and the cover reader, so the paper joined the Claude approved list by the upload route and Automatic would send
it. Both homes of the check are tested: `claude_auto_approve.is_contract_paper` (the approved list and the send-time gate) and
`review_engine.read_facts` (the one review button's decision).
"""

from __future__ import annotations

import sqlite3

import pytest

from app import (
    agent_review_kind,
    claude_approved,
    claude_auto_approve,
    db,
    review_engine,
    review_jobs,
)
from app.config import settings
from tests.test_b1_review_engine import (  # noqa: F401 - fixtures
    _approved,
    _doc,
    approvals,
    lane,
    world,
)
from tests.test_p3_review_jobs import temp_storage  # noqa: F401 - fixture

SUBMITTAL = "CONTRACTOR_SUBMITTAL"


def _store_kind(doc_id: str, kind: str, state: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_kinds (document_id, kind, state, routed_at) VALUES (?, ?, ?, 'x')",
            (doc_id, kind, state),
        )


@pytest.fixture
def cover_says_datasheet(monkeypatch):
    """The cover reader calls every paper a datasheet (known, a guess): the one scored kind, so Automatic would send it."""
    monkeypatch.setattr(
        agent_review_kind,
        "read_kind",
        lambda _conn, _doc: {
            "kind": "datasheet",
            "known": True,
            "method": "cover_title",
            "guess": True,
        },
    )


@pytest.mark.parametrize("state", ["suggested", "confirmed", "needs_engineer"])
def test_a_stored_contract_kind_is_a_contract_whatever_the_role_and_the_cover_say(
    approvals,  # noqa: F811 - the imported fixture
    cover_says_datasheet,
    state,
):
    paper = _doc("c_stored", "51" * 32)
    _store_kind(paper, "contract", state)
    from app import classification

    # the review page's confirm: runs the upload route of the approved list
    classification.set_role(paper, SUBMITTAL)
    assert claude_auto_approve.is_contract_paper(paper) is True
    # the review-start route
    review_jobs.enqueue(
        paper, allowed_document_ids=frozenset({paper}), requested_by=None
    )
    assert not _approved("51" * 32), "a contract joined the Claude approved list"
    # the send-time gate refuses it too
    assert paper in claude_approved.contracts_without_yes([paper])


def test_the_same_paper_with_a_stored_datasheet_kind_is_approved(
    approvals,  # noqa: F811 - the imported fixture
    cover_says_datasheet,
):
    """The control: the same steps on a paper whose stored kind is not a contract still approve it (the test can see approval)."""
    paper = _doc("d_stored", "52" * 32)
    _store_kind(paper, "datasheet", "suggested")
    from app import classification

    classification.set_role(paper, SUBMITTAL)
    assert claude_auto_approve.is_contract_paper(paper) is False
    assert _approved("52" * 32)


def test_an_unreadable_kinds_table_counts_as_a_contract():
    class Broken:
        def execute(self, sql, *_a):
            if "sqlite_master" in sql:
                return _One((1,))
            raise sqlite3.OperationalError("invented")

    class _One:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    assert claude_auto_approve.stored_kind_is_contract(Broken(), "any") is True


def test_no_kinds_table_is_no_stored_kind():
    conn = sqlite3.connect(":memory:")
    assert claude_auto_approve.stored_kind_is_contract(conn, "any") is False


def test_the_review_button_counts_a_stored_contract_kind(
    world,  # noqa: F811 - the imported fixture
    lane,  # noqa: F811 - the imported fixture
    cover_says_datasheet,
):
    """`review_engine.read_facts`: the paper is a contract, so Automatic sends nothing and Claude needs the explicit choice."""
    lane.setattr(settings, "agent_review_enabled", True)
    sub = world["sub"]
    facts, _ = review_engine.read_facts(db.connect(), sub, world["scope"])
    # before: a datasheet by its cover, not a contract
    assert facts.is_contract is False and facts.kind == "datasheet"
    _store_kind(sub, "contract", "suggested")
    facts, _ = review_engine.read_facts(db.connect(), sub, world["scope"])
    assert facts.is_contract is True and facts.kind == "datasheet"
    plan = review_engine.plan_for(db.connect(), sub, world["scope"], "automatic")
    ai = next(p for p in plan["parts"] if p["name"] == "ai_review")
    assert ai["engine"] != "claude" and plan["text_leaves"] is False
