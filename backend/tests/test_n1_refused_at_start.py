# ruff: noqa: F811
"""Live fault of 15 Nov 2026: the AI review of a Local-only start was refused in one second ("the item list failed its checks"). A
Local-only start stored the empty list "shown before the start"; the AI job read it as "no rule book may be used", dropped every book
and every checklist item that cites one, and left the item file's counts stale. The list restricts what is SENT to Claude."""

from __future__ import annotations

import json

import pytest

from app import (
    agent_review_items,
    agent_review_jobs,
    claude_auto_approve,
    db,
    review_engine,
    review_engine_start,
    review_shown,
    submittal_review,
)
from app import agent_review_local as local_mod
from app.config import settings
from tests import agent_review_support as s
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures


# ---------------------------------------------------------------- the plan of the AI job on a stored empty list


def _job_world(tmp_path, monkeypatch, listed):
    s.setup_world(tmp_path, monkeypatch)
    submittal_review.ensure_schema()
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('rr', ?, 'running', 't', 't')",
            (s.PAPER,),
        )
        if listed is not None:
            review_shown.record_in(conn, "rr", listed, "t")
    # the checklist items cite a rule book, as the live ones do; the rules too
    doc, cache = s.item_doc()
    skill = {**s.item("R-coat"), "item_id": "S-1", "source": "skill"}
    doc["items"] = [skill, *doc["items"]]
    doc["counts"] = {"skill": 1, "rule": len(doc["items"]) - 1}
    seen = {}

    def fake_build(_c, _p, _k, *_a, cache=None, shown=None, **_kw):
        seen["shown"] = shown
        cache.update({k: dict(v) for k, v in cache_src.items()})
        out = json.loads(json.dumps(doc))
        if shown is not None:  # what the real builder does: a book not on the list is left out of the rules
            out["items"] = [i for i in out["items"] if i["standard_document_id"] in shown]
            out["counts"] = {"skill": sum(i["source"] == "skill" for i in out["items"]), "rule": sum(i["source"] == "rule" for i in out["items"])}
        return out

    cache_src = cache
    monkeypatch.setattr(agent_review_jobs, "_scope_run_id", lambda *_a: "rr")
    monkeypatch.setattr(agent_review_jobs.items_mod, "build_items_for_run", fake_build)
    monkeypatch.setattr(agent_review_jobs, "_write_rules", lambda *_a: None)
    monkeypatch.setattr(claude_auto_approve, "on_review_start", lambda *_a: None)
    monkeypatch.setattr(claude_auto_approve, "note_unshown_for", lambda *_a: seen.setdefault("noted", True))
    kind = agent_review_jobs.agent_review_kind.PaperReading("datasheet", True, "r", "t", False, None, None)
    return conn, kind, seen


def _plan(conn, kind):
    return agent_review_jobs._plan(conn, "rr", s.PAPER, frozenset({s.PAPER, s.STD}), kind, lambda: None)


def test_a_local_run_with_a_stored_empty_list_keeps_every_book_and_is_not_refused(tmp_path, monkeypatch):
    conn, kind, seen = _job_world(tmp_path, monkeypatch, [])
    monkeypatch.setattr(local_mod, "local_run", lambda _r: True)
    plan = _plan(conn, kind)
    assert plan["stop"] is None and len(plan["items"]) == 5  # the checklist item and the four rules: nothing was dropped
    assert seen["shown"] is None and "noted" not in seen  # the list was not read, and no "not sent" note was made


def test_the_same_empty_list_on_a_claude_run_still_sends_nothing_but_is_not_a_refusal_either(tmp_path, monkeypatch):
    conn, kind, seen = _job_world(tmp_path, monkeypatch, [])
    monkeypatch.setattr(local_mod, "local_run", lambda _r: False)
    plan = _plan(conn, kind)
    assert plan["items"] == [] and not str(plan["stop"] or "").startswith("refused")  # nothing shown, nothing asked; counts stay consistent
    assert seen["shown"] == frozenset() and seen["noted"] is True


def test_a_claude_run_with_a_list_that_names_the_book_is_unchanged(tmp_path, monkeypatch):
    conn, kind, seen = _job_world(tmp_path, monkeypatch, [s.STD])
    monkeypatch.setattr(local_mod, "local_run", lambda _r: False)
    plan = _plan(conn, kind)
    assert plan["stop"] is None and len(plan["items"]) == 5


def test_dropping_a_book_keeps_the_item_files_counts_equal_to_its_items():
    doc = {"items": [{"item_id": "S-1", "source": "skill", "standard_document_id": "b1"},
                     {"item_id": "R-1", "source": "rule", "standard_document_id": "b1"},
                     {"item_id": "R-2", "source": "rule", "standard_document_id": "b2"}],
           "counts": {"skill": 1, "rule": 2}}  # fmt: skip
    conn = db.connect()
    with conn:
        review_shown.record_in(conn, "rx", ["b2"], "t")
    assert review_shown.drop_unlisted(conn, "rx", doc) == ["b1"]
    assert [i["item_id"] for i in doc["items"]] == ["R-2"] and doc["counts"] == {"skill": 0, "rule": 1}


# ---------------------------------------------------------------- a refusal says which check and which item


def test_a_refusal_names_the_check_and_the_item_in_plain_words(tmp_path, monkeypatch):
    conn, kind, _seen = _job_world(tmp_path, monkeypatch, None)
    doc, cache = s.item_doc()
    doc["counts"] = {"skill": 17, "rule": 0}  # the live string
    why = agent_review_jobs.preflight(conn, s.PAPER, kind, doc, cache)
    assert why.startswith("the item list failed its checks: counts ") and "do not match items" in why and why.endswith("(1 problem(s))")
    doc, cache = s.item_doc()
    doc["items"][0]["question"] = ""
    why = agent_review_jobs.preflight(conn, s.PAPER, kind, doc, cache)
    assert "R-coat: empty question" in why  # the item id, no document text
    assert agent_review_items.validate(*s.item_doc()) == []


# ---------------------------------------------------------------- the start stores no list when nothing leaves


def test_a_start_that_sends_nothing_stores_no_list_and_one_that_sends_stores_what_was_shown(world, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    run_id, plan = review_engine_start.start(world["sub"], world["scope"], "adm", "local", shown_document_ids=())
    assert plan["text_leaves"] is False
    assert review_shown.shown_ids(db.connect(), run_id) is None  # an empty list would have meant "no book may be used"
    real = review_engine.plan_for

    def leaving(*a, **k):
        got = real(*a, **k)
        return {**got, "text_leaves": True, "documents": {**(got.get("documents") or {}), "leaving": [{"id": world["std"], "kind": "k", "why": "w"}]}}

    monkeypatch.setattr(review_engine, "plan_for", leaving)
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'completed' WHERE id = ?", (run_id,))
    run_b, _plan_b = review_engine_start.start(world["sub"], world["scope"], "adm", "local", shown_document_ids=(world["std"],))
    assert review_shown.shown_ids(db.connect(), run_b) == frozenset({world["std"]})  # a start that sends still stores its list
