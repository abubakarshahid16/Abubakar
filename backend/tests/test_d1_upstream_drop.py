"""D1 (R50b finding 1): a rule book the list shown before the start does not name is dropped BEFORE any request is built. Its rules
are not asked, none of its text is sent, the run goes on with the listed books and the result says "1 not sent". The send-time
refusal stays the last line of defence."""

# ruff: noqa: F811
from __future__ import annotations

import json

from app import (
    agent_review_jobs,
    claude_approved,
    claude_auto_approve,
    claude_spend,
    db,
    review_shown,
    submittal_review,
)
from tests import agent_review_support as s

BOOKS = ("book_1", "book_2", "book_3", "book_4")


def _setup(tmp_path, monkeypatch, listed):
    s.setup_world(tmp_path, monkeypatch)
    submittal_review.ensure_schema()
    conn = db.connect()
    for b in BOOKS:
        s.add_document(conn, b, f"{b}.pdf", s.STD_PAGE)
    with conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('rr', ?, 'running', 't', 't')",
            (s.PAPER,),
        )
        for n, b in enumerate(BOOKS):
            conn.execute(
                "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id, selection_reason,"
                " selection_method, included, created_at) VALUES (?, 'rr', ?, 'x', 'scope', 1, 't')",
                (f"a{n}", b),
            )
        review_shown.record_in(conn, "rr", listed, "t")
    items = [
        {"item_id": f"R-{b}", "source": "rule", "standard_document_id": b}
        for b in BOOKS
    ]
    items.append({"item_id": "C-1", "source": "checklist"})  # no rule book: stays
    seen = {}

    def fake_build(_c, _p, _k, *_a, **_kw):
        return {
            "rule_labels": {"summary_lines": []},
            "items": list(items),
            "paper_kind": "datasheet",
        }

    def written(_run, doc, _cache, _kind):
        seen["items"] = list(doc["items"])

    monkeypatch.setattr(agent_review_jobs, "_scope_run_id", lambda *_a: "rr")
    monkeypatch.setattr(agent_review_jobs.items_mod, "build_items_for_run", fake_build)
    monkeypatch.setattr(agent_review_jobs, "_write_rules", written)
    monkeypatch.setattr(agent_review_jobs, "preflight", lambda *_a: None)
    monkeypatch.setattr(claude_auto_approve, "on_review_start", lambda *_a: None)
    kind = agent_review_jobs.agent_review_kind.PaperReading(
        "datasheet", True, "r", "t", False, None, None
    )
    plan = agent_review_jobs._plan(
        conn, "rr", s.PAPER, frozenset({s.PAPER, *BOOKS}), kind, lambda: None
    )
    return plan, seen


def _books_of(items):
    return {i["standard_document_id"] for i in items if i.get("standard_document_id")}


def test_three_listed_books_and_one_unlisted_the_run_asks_the_three_sends_nothing_of_the_fourth_and_counts_it(
    tmp_path, monkeypatch
):
    plan, seen = _setup(tmp_path, monkeypatch, [s.PAPER, "book_1", "book_2", "book_3"])
    assert _books_of(plan["items"]) == {
        "book_1",
        "book_2",
        "book_3",
    }  # the rules of the three are asked
    assert _books_of(seen["items"]) == {
        "book_1",
        "book_2",
        "book_3",
    }  # and recorded as asked: nothing of book_4
    assert any(
        i["item_id"] == "C-1" for i in plan["items"]
    )  # the rest of the run goes on
    # the run's declaration is now clean: no request carries the fourth book, so nothing is refused
    declared = sorted({s.PAPER} | _books_of(plan["items"]))
    with claude_approved.carrying(declared), claude_spend.for_run("rr"):
        assert claude_approved.refusal() is None
    outcome = json.loads(
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = 'rr'")
        .fetchone()[0]
        or "{}"
    )
    assert outcome[claude_auto_approve.SHOWN_KEY] == {
        "not_sent": 1,
        "found_during_review": 1,
    }


def test_a_request_that_still_carries_the_unlisted_book_is_refused_at_send_time(
    tmp_path, monkeypatch
):
    _setup(tmp_path, monkeypatch, [s.PAPER, "book_1", "book_2", "book_3"])
    with claude_approved.carrying([s.PAPER, *BOOKS]), claude_spend.for_run("rr"):
        found = claude_approved.refusal()
    assert found is not None and "book_4" in found[1]


def test_no_list_no_drop(tmp_path, monkeypatch):
    plan, _seen = _setup(tmp_path, monkeypatch, list(BOOKS) + [s.PAPER])
    assert _books_of(plan["items"]) == set(BOOKS)
