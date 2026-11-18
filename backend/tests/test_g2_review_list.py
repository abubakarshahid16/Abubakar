"""Piece G2 (order 14): the Review screen lists every paper the general review can take, not only contractor submittals.

Invented papers only. A paper with no role recorded stays in the list; a rule book does not; the filter only ever narrows what the
caller may read; the plan and the start take a paper with no role, and a contract is still never sent by Automatic."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import db, review_engine
from app.config import settings
from app.main import app
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures and helpers
    NOW,
    _doc,
    _user,
    temp_storage,
)


@pytest.fixture
def papers(temp_storage, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    ids = {
        "submittal": _doc("doc_g2_sub", "CONTRACTOR_SUBMITTAL", "Invented pump paper."),
        "spec": _doc("doc_g2_spec", "SPECIFICATION", "Invented specification."),
        "contract": _doc("doc_g2_contract", "CONTRACT_DOCUMENT", "Invented agreement."),
        "book": _doc("doc_g2_book", "COMPANY_STANDARD", "Invented rule book."),
        "template": _doc("doc_g2_tmpl", "CRS_TEMPLATE", "Invented template."),
        "norole": _doc(
            "doc_g2_norole", "CONTRACTOR_SUBMITTAL", "Invented paper with no role."
        ),
    }
    with (
        db.connect() as conn
    ):  # no role recorded: the classification row is absent, as for a fresh upload
        conn.execute(
            "DELETE FROM document_classification WHERE document_id = ?",
            (ids["norole"],),
        )
    ids["admin"] = _user("adm", list(ids.values()), admin=True)
    ids["reader"] = _user("rdr", [ids["submittal"], ids["book"], ids["norole"]])
    return ids


def _listed(headers, **params):
    r = TestClient(app).get("/api/documents", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return {d["id"] for d in r.json()}


def test_the_route_tells_the_screen_to_exclude_only_the_rule_book_and_the_template(
    papers,
):
    got = (
        TestClient(app)
        .get("/api/document-kinds/role-suggestion", headers=papers["admin"])
        .json()
    )
    assert got["exclude_roles"] == ["COMPANY_STANDARD", "CRS_TEMPLATE"]


def test_the_way_back_switch_gives_no_exclusion_so_the_old_list_stays(
    papers, monkeypatch
):
    monkeypatch.setattr(settings, "review_old_engine_enabled", True)
    got = (
        TestClient(app)
        .get("/api/document-kinds/role-suggestion", headers=papers["admin"])
        .json()
    )
    assert got["exclude_roles"] == [] and got["review_roles"] == [
        "CONTRACTOR_SUBMITTAL"
    ]


def test_exclude_role_keeps_every_paper_including_one_with_no_role(papers):
    got = _listed(papers["admin"], exclude_role=["COMPANY_STANDARD", "CRS_TEMPLATE"])
    assert got == {
        papers["submittal"],
        papers["spec"],
        papers["contract"],
        papers["norole"],
    }


def test_the_old_role_filter_does_not_list_a_paper_with_no_role(papers):
    assert papers["norole"] not in _listed(
        papers["admin"], document_role=["CONTRACTOR_SUBMITTAL"]
    )


def test_exclude_role_only_narrows_what_the_caller_may_read(papers):
    got = _listed(papers["reader"], exclude_role=["COMPANY_STANDARD", "CRS_TEMPLATE"])
    assert got == {
        papers["submittal"],
        papers["norole"],
    }  # never the spec or contract the reader holds no grant for


def test_an_unknown_role_to_exclude_is_refused(papers):
    r = TestClient(app).get(
        "/api/documents",
        params={"exclude_role": ["NOT_A_ROLE"]},
        headers=papers["admin"],
    )
    assert r.status_code == 422


def test_the_total_count_header_counts_the_excluded_list(papers):
    r = TestClient(app).get(
        "/api/documents",
        params={"exclude_role": ["COMPANY_STANDARD", "CRS_TEMPLATE"]},
        headers=papers["admin"],
    )
    assert r.headers["X-Total-Count"] == "4"


@pytest.fixture
def real_roles(papers, monkeypatch):
    """The real read of a paper's role and approval; only the lane, the engines and the kind are opened (the facts of the paper stay real)."""
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    monkeypatch.setattr(settings, "claude_spend_log", settings.data_dir / "spend.jsonl")
    real = review_engine.read_facts

    def opened(conn, document_id, allowed):
        facts, reading = real(conn, document_id, allowed)
        return (
            dataclasses.replace(
                facts,
                kind="datasheet",
                agent_enabled=True,
                provider="per_task",
                agent_engine_claude=True,
                step_engine_claude=True,
                lane_open=True,
                caps_ok=True,
                books_ok=True,
                kind_scored=True,
                scored_allowed=True,
            ),
            reading,
        )

    monkeypatch.setattr(review_engine, "read_facts", opened)
    return papers


def _plan(ids, doc, engine):
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={"submittal_document_id": ids[doc], "engine": engine},
        headers=ids["admin"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_the_plan_takes_a_paper_with_no_role_like_a_submittal(real_roles):
    none, sub = (
        _plan(real_roles, "norole", "automatic"),
        _plan(real_roles, "submittal", "automatic"),
    )
    assert none["refused"] is None and none["text_leaves"] is True
    assert none["method"] == sub["method"] == "general"
    assert {d["id"] for d in none["documents"]["leaving"]} >= {real_roles["norole"]}


def test_a_contract_is_never_sent_by_automatic_but_the_explicit_choice_lists_it(
    real_roles,
):
    auto = _plan(real_roles, "contract", "automatic")
    assert real_roles["contract"] not in {d["id"] for d in auto["documents"]["leaving"]}
    chosen = _plan(real_roles, "contract", "claude")
    assert real_roles["contract"] in {d["id"] for d in chosen["documents"]["leaving"]}


def test_the_start_takes_a_paper_with_no_role_and_records_no_role(real_roles):
    shown = [real_roles["norole"]]
    r = TestClient(app).post(
        "/api/reviews/start",
        json={
            "submittal_document_id": real_roles["norole"],
            "engine": "claude",
            "shown_document_ids": shown,
        },
        headers=real_roles["admin"],
    )
    assert r.status_code == 200, r.text
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM document_classification WHERE document_id = ? AND document_role IS NOT NULL",
                (real_roles["norole"],),
            ).fetchone()[0]
            == 0
        )  # nothing set a role silently
