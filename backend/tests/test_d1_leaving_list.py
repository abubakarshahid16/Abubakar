"""D1 PR 2 (owner, 12 Nov 2026, #1584): "the screen lists every document that will leave the Mac before the review starts".
`plan_for` lists them (`documents.leaving`), the start stores the list shown with the run, and a run with a stored list sends
only what it names. Invented documents; no call is made."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import (
    claude_approved,
    contract_yes,
    db,
    review_engine,
    review_engine_start,
    review_leaving,
    review_shown,
)
from app.config import settings
from app.main import app
from tests.test_b1_review_engine import _doc, open_facts
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

SPEC_NAME, CONTRACT_NAME = (
    "SAES-Q-001 invented spec.pdf",
    "SAES-C-001 invented contract.pdf",
)


@pytest.fixture
def lib(world, monkeypatch):  # noqa: F811
    """The p3 world (a paper citing API 610 and the rule book that holds it) plus a cited specification and a cited contract."""
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )
    spec = _doc("spec_1", "71" * 32, "SPECIFICATION", filename=SPEC_NAME)
    con = _doc("con_1", "72" * 32, "CONTRACT_DOCUMENT", filename=CONTRACT_NAME)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,1,0)",
            (world["sub"], "Per API 610, SAES-Q-001, SAES-C-001 and SAES-Z-999."),
        )
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET filename = 'API 610 invented.pdf' WHERE id = ?",
            (world["std"],),
        )
    world["spec"], world["con"] = spec, con
    world["scope"] = world["scope"] | {spec, con}
    return world


def _plan(w, engine="automatic", scope=None, projects=()):
    return review_engine.plan_for(
        db.connect(), w["sub"], scope or w["scope"], engine, project_ids=projects
    )["documents"]


def _approve(*ids):
    shas = [
        db.connect()
        .execute("SELECT sha256 FROM documents WHERE id = ?", (i,))
        .fetchone()[0]
        for i in ids
    ]
    claude_approved.list_path().write_text(
        json.dumps(
            {
                "documents": [
                    {"sha256": s, "status": "approved", "label": "invented"}
                    for s in shas
                ]
            }
        ),
        encoding="utf-8",
    )


def _by_id(docs):
    return {d["id"]: d for d in docs["leaving"]}


def test_the_list_names_the_paper_the_rule_book_and_the_approved_specification_with_kind_and_why(
    lib, monkeypatch
):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _approve(lib["sub"], lib["std"], lib["spec"])
    got = _by_id(_plan(lib))
    assert (
        got[lib["sub"]]["kind"] == "paper"
        and got[lib["sub"]]["why"] == "paper under review"
    )
    assert (
        got[lib["std"]]["kind"] == "rule book"
        and got[lib["std"]]["why"] == "cited by the paper"
    )
    assert (
        got[lib["spec"]]["kind"] == "specification"
        and got[lib["spec"]]["why"] == "cited by the paper"
    )
    assert (
        got[lib["spec"]]["title"] == SPEC_NAME
    )  # a display title, never the internal id
    assert lib["con"] not in got


def test_what_will_not_go_is_listed_with_the_reason(lib, monkeypatch):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _approve(
        lib["sub"], lib["std"], lib["con"]
    )  # the specification is not approved; the contract is, but has no yes
    docs = _plan(lib)
    reasons = {n.get("title") or n.get("name"): n["reason"] for n in docs["not_sent"]}
    assert reasons[SPEC_NAME] == review_leaving.NOT_APPROVED_SPEC
    assert (
        reasons[CONTRACT_NAME] == "a contract goes only with the owner's recorded yes"
    )
    assert reasons["SAES-Z-999"] == review_leaving.NOT_HELD
    assert lib["spec"] not in _by_id(docs) and lib["con"] not in _by_id(docs)


def test_a_contract_with_a_recorded_yes_may_be_listed(lib, monkeypatch):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _approve(lib["sub"], lib["std"], lib["con"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_role='CONTRACT_DOCUMENT' WHERE document_id=?",
            (lib["con"],),
        )
    contract_yes.grant(lib["con"], "owner")
    assert lib["con"] in _by_id(_plan(lib))


def test_a_blocked_document_is_not_listed(lib, monkeypatch):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    _approve(lib["sub"], lib["std"], lib["spec"])
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["71" * 32]})
    )
    docs = _plan(lib)
    assert lib["spec"] not in _by_id(docs)
    assert any(n["reason"] == review_leaving.BLOCKED_WORDS for n in docs["not_sent"])


def test_a_document_the_caller_may_not_read_is_counted_never_named(lib):
    docs = _plan(lib, scope=lib["scope"] - {lib["spec"]})
    assert docs["not_readable"] == 1
    assert SPEC_NAME not in json.dumps(docs) and lib["spec"] not in json.dumps(docs)


def test_local_only_lists_nothing_and_says_so(lib):
    docs = _plan(lib, engine="local")
    assert docs["leaving"] == [] and docs["summary"] == "Nothing leaves this Mac"


def test_the_papers_chosen_for_a_general_review_are_listed_including_a_specification(
    lib,
):
    other = _doc(
        "spec_2", "73" * 32, "SPECIFICATION", filename="Invented project spec.pdf"
    )
    got = _by_id(_plan(lib, projects=(other,), scope=lib["scope"] | {other}))
    assert (
        got[other]["kind"] == "specification"
        and got[other]["why"] == "chosen by you for this review"
    )


def test_the_plan_route_lists_and_the_start_route_stores_the_shown_list_without_titles(
    lib,
):
    client = TestClient(app)
    plan = client.get(
        "/api/reviews/plan",
        params={"submittal_document_id": lib["sub"], "engine": "automatic"},
        headers=lib["admin"],
    ).json()
    ids = [d["id"] for d in plan["documents"]["leaving"]]
    assert lib["sub"] in ids
    started = client.post(
        "/api/reviews/start",
        json={
            "submittal_document_id": lib["sub"],
            "engine": "automatic",
            "shown_document_ids": ids,
        },
        headers=lib["admin"],
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["review_run_id"]
    assert review_shown.shown_ids(db.connect(), run_id) == frozenset(ids)
    stored = (
        db.connect()
        .execute(
            "SELECT plan_json FROM review_engine_choice WHERE run_id = ?", (run_id,)
        )
        .fetchone()[0]
    )
    assert SPEC_NAME not in stored  # the stored choice holds ids, never a file name


def test_the_stored_list_is_only_what_was_shown_and_still_allowed(lib):
    run_id, _ = review_engine_start.start(
        lib["sub"],
        lib["scope"],
        "adm",
        "automatic",
        shown_document_ids=(lib["sub"], "never-listed"),
    )
    assert review_shown.shown_ids(db.connect(), run_id) == frozenset({lib["sub"]})


def test_a_start_that_showed_no_list_stores_none(lib):
    run_id, _ = review_engine_start.start(lib["sub"], lib["scope"], "adm", "automatic")
    assert review_shown.shown_ids(db.connect(), run_id) is None


def test_a_run_with_a_stored_list_sends_only_what_the_list_names(lib):
    run_id, _ = review_engine_start.start(
        lib["sub"], lib["scope"], "adm", "automatic", shown_document_ids=(lib["sub"],)
    )
    with claude_approved.carrying([lib["sub"]]), claude_approved.reviewing(run_id):
        assert claude_approved.refusal() is None
    with (
        claude_approved.carrying([lib["sub"], lib["std"]]),
        claude_approved.reviewing(run_id),
    ):
        found = claude_approved.refusal()  # a rule book the screen did not show
    assert (
        found is not None
        and lib["std"] in found[1]
        and "shown before the start" in found[1]
    )


def test_a_run_without_a_stored_list_keeps_todays_behaviour_for_the_paper_and_rule_books(
    lib,
):
    run_id, _ = review_engine_start.start(lib["sub"], lib["scope"], "adm", "automatic")
    with (
        claude_approved.carrying([lib["sub"], lib["std"]]),
        claude_approved.reviewing(run_id),
    ):
        assert claude_approved.refusal() is None


def test_the_ai_run_that_follows_the_rule_check_stores_the_same_list(lib, monkeypatch):
    run_id, _ = review_engine_start.start(
        lib["sub"],
        lib["scope"],
        "adm",
        "automatic",
        shown_document_ids=(lib["sub"], lib["std"]),
    )
    job_id = (
        db.connect()
        .execute("SELECT id FROM jobs WHERE review_run_id = ?", (run_id,))
        .fetchone()["id"]
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_engine_choice SET then_ai = 1 WHERE run_id = ?", (run_id,)
        )
    monkeypatch.setattr(review_engine_start.agent_review_gate, "enabled", lambda: True)
    seen = {}

    def enqueue(doc, **kw):
        conn = db.connect()
        with conn:
            kw["in_transaction"](conn, "ai-run")
        seen["list"] = review_shown.shown_ids(conn, "ai-run")
        return "ai-run", "ai-job"

    monkeypatch.setattr(review_engine_start.agent_review_jobs, "enqueue", enqueue)
    assert review_engine_start.follow_up(job_id, "done") == "ai-run"
    assert seen["list"] == frozenset({lib["sub"], lib["std"]})
