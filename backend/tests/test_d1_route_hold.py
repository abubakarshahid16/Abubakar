"""D1 (R50): the shown-list hold THROUGH the entry points that declare a review's documents, not through a hand-rebuilt declaration.
A cited specification on the approved list, with no list shown before the start, is refused inside:
the comparison (`comparison.run_comparison`), the clause review's start and its restore path, and a `claude_api` route.
Each test fails when the entry point's `reviewing(...)` is taken out (it then knows no run, so the hold does not apply).
Invented documents; nothing is sent."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import (
    classification,
    claude_approved,
    clause_review,
    clause_review_claude,
    comparison,
    review_shown,
    submittal_review,
)
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_838_local_when_not_approved import (  # noqa: F401 - fixtures and helpers
    SHEET,
    STANDARD,
    Local,
    _approve,
    _asked_locally,
    _cloud_route,
    lane,
    no_cloud,
)
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import world  # noqa: F401 - fixture

SPEC = "SPECIFICATION"
HELD = "not on the list shown before the start"


@pytest.fixture
def held(world, monkeypatch):
    """The cited standard of the world is a specification on the approved list; no list was shown for the run."""
    sub, run, scope = world
    classification.set_role("doc_std", SPEC)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _approve(SHEET, STANDARD)
    assert review_shown.shown_ids(
        __import__("app.db", fromlist=["connect"]).connect(), run
    ) is None
    return sub, run, scope


def test_the_comparison_declares_the_run_so_a_cited_specification_with_no_shown_list_is_refused(
    held, monkeypatch
):
    _sub, run, scope = held
    seen = []

    def inside(*_a, **_k):  # what a model call made inside the comparison would be asked
        seen.append((claude_approved.review_run(), claude_approved.refusal()))
        return {}

    monkeypatch.setattr(comparison, "_run_comparison", inside)
    comparison.run_comparison(run, allowed_document_ids=scope)
    assert seen and seen[0][0] == run
    code, reason = seen[0][1]
    assert code == claude_approved.NOT_APPROVED and HELD in reason


def _clause_review_world(monkeypatch, run, seen):
    monkeypatch.setattr(settings, "ai_clause_review_engine", "claude")
    monkeypatch.setattr(clause_review, "eligible", lambda sub: ("procedure", "ok"))
    monkeypatch.setattr(
        clause_review,
        "requirements_for",
        lambda review_run_id, scope: [{"id": "r1", "standard_document_id": "doc_std"}],
    )
    monkeypatch.setattr(rp, "claude_unavailable_for_task", lambda engine: (None, ""))

    def lane_asked(engine, role="reasoning", *, step=None):  # what `claude_for_task` asks the gate, here a recorder
        seen.append(claude_approved.refusal())
        return None

    monkeypatch.setattr(rp, "claude_for_task", lane_asked)


def test_the_clause_review_start_declares_the_run_and_says_the_list_was_not_shown(
    held, monkeypatch
):
    _sub, run, scope = held
    seen: list = []
    _clause_review_world(monkeypatch, run, seen)
    handled, why = clause_review_claude.for_review(run, scope)
    assert handled is False
    assert seen and seen[0] is not None and seen[0][0] == claude_approved.NOT_APPROVED
    assert HELD in why and "not available" not in why  # the reason names the list, not "not available"


def test_the_clause_review_restore_path_declares_the_run(held, monkeypatch):
    _sub, run, _scope = held
    seen: list = []
    _clause_review_world(monkeypatch, run, seen)
    row = {
        "asks": "{}",
        "documents": json.dumps(["doc_sheet", "doc_std"]),
        "review_run_id": run,
        "document_id": "doc_sheet",
        "model": "invented",
    }
    clause_review_claude._restore_closed(row, None, {}, [], {})
    assert seen and seen[0] is not None and seen[0][0] == claude_approved.NOT_APPROVED
    assert HELD in seen[0][1]


def test_a_claude_api_route_holds_the_cited_specification_and_says_why(
    held, lane, no_cloud, monkeypatch
):
    _sub, run, _scope = held
    asked_cloud = _cloud_route(monkeypatch)
    Local.answer = "{}"
    body = TestClient(app).post(f"/api/reviews/runs/{run}/claude/recheck").json()
    assert asked_cloud == [] and _asked_locally() >= 1  # it ran on the local model, nothing went to Claude
    assert body["local_instead"].startswith(
        "ran on the local model: 1 of 2 document(s) in its prompt are specifications that were not on the list shown"
    )


def test_the_run_note_counts_every_held_specification_not_only_the_applied_standards(
    held, monkeypatch
):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    from app import agent_general_job as general
    from app import agent_review_schema
    from app.db import connect

    _sub, run, _scope = held
    conn = connect()
    agent_review_schema.create_tables(conn)
    base = review_shown.cited_unshown(conn, run)
    assert base == 1  # the applied standard (a specification)
    for doc in ("doc_plan_spec", "doc_project_spec"):
        with conn:
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',1,'2026-11-12T00:00:00Z')",
                (doc, f"{doc}.pdf", f"sha-{doc}", f"{doc}.pdf"),
            )
        classification.set_role(doc, SPEC)
    with conn:
        conn.execute(
            "INSERT INTO agent_review_rule (run_id, rule_key, asked, standard_document_id) VALUES (?,?,1,?)",
            (run, "R-plan", "doc_plan_spec"),
        )
    assert review_shown.cited_unshown(conn, run) == 2  # + an AI-reviewer plan item
    with conn:
        general.record_request(conn, run, ["doc_project_spec"])
    assert review_shown.cited_unshown(conn, run) == 3  # + a general review's project paper
    review_shown.record_in(conn, run, ["doc_plan_spec"], "2026-11-12T00:00:00Z")
    assert review_shown.cited_unshown(conn, run) == 2  # a shown one is not counted
