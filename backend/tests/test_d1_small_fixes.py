"""D1 small fixes after R50c/R50d: a dropped book's rules are LEFT OUT with one reason and not counted as stored rules; consent is
per run and per user; the stored-list intersection and the hash and block cases of the consent are each their own test."""

# ruff: noqa: F811
from __future__ import annotations

import json

from app import agent_review_items as it
from app import agent_review_rules as rules
from app import claude_approved, db, review_shown
from tests import agent_review_support as s
import pytest

from tests.test_agent_review_1749 import _real_plan_world
from tests.test_d1_claude_by_choice import _plan, _start, lib  # noqa: F401 - fixture
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

KIND = {"kind": "datasheet", "known": True, "method": "r", "guess": False}
WORDS = "its rule book was not on the list shown before the start"


def _build(conn, run, shown):
    return it.build_items_for_run(
        conn,
        s.PAPER,
        KIND,
        run,
        frozenset({s.PAPER, s.STD}),
        cache={},
        equipment_type=None,
        ask_unapproved="off",
        shown=shown,
    )


def test_the_rules_of_a_book_not_on_the_list_are_left_out_with_one_reason_and_not_counted_as_stored_rules(
    tmp_path, monkeypatch
):
    conn, run, _plan = _real_plan_world(tmp_path, monkeypatch, with_decisions=False)
    everything = _build(conn, run, None)
    asked_all = [i for i in everything["items"] if i["source"] == "rule"]
    stored = everything["rule_labels"]["candidates"]["rows"]
    assert asked_all and stored >= len(asked_all)
    dropped = _build(
        conn, run, frozenset({s.PAPER})
    )  # the list names the paper, not the rule book
    assert [
        i for i in dropped["items"] if i["source"] == "rule"
    ] == []  # nothing of that book is asked
    left = [
        r
        for r in dropped["rule_labels"]["left_out"]
        if r["reason"] == rules.NOT_ON_LIST
    ]
    assert len(left) == stored  # every rule of the book, one record each
    assert len({str(r["rule_version_id"]) for r in left}) == len(left)
    assert rules.REASON_WORDS[rules.NOT_ON_LIST] == WORDS
    assert dropped["rule_labels"]["counts"][rules.NOT_ON_LIST] == stored
    # the summary line counts only the stored rules of the books on the list
    text = " ".join(dropped["rule_labels"]["summary_lines"])
    assert "(0 stored rules" in text and f"({stored} stored rules" not in text
    assert any(
        f"{WORDS} {stored}" in line for line in dropped["rule_labels"]["summary_lines"]
    )
    # no list: nothing changes
    assert (
        _build(conn, run, frozenset({s.PAPER, s.STD}))["rule_labels"]["counts"][
            rules.NOT_ON_LIST
        ]
        == 0
    )
    assert it.build_items_for_run  # the plan's own route
    assert json.dumps(dropped["rule_labels"]["left_out"])  # serialisable


def test_a_dropped_books_rules_are_written_as_left_out_rows_of_the_run(
    tmp_path, monkeypatch
):
    from app import agent_review_jobs

    conn, run, _plan = _real_plan_world(tmp_path, monkeypatch, with_decisions=False)
    doc = _build(conn, run, frozenset({s.PAPER}))
    agent_review_jobs._write_rules("rule-run", doc, {}, "datasheet")
    got = (
        db.connect()
        .execute(
            "SELECT asked, left_out_reason FROM agent_review_rule WHERE run_id = 'rule-run'"
        )
        .fetchall()
    )
    assert got and all(r["asked"] == 0 and r["left_out_reason"] == WORDS for r in got)


@pytest.fixture
def lib_consent(lib):
    ids = {d["id"] for d in _plan(lib, "claude")["leaving"]}
    run_id, _ = _start(lib, "claude", ids)
    return db.connect(), run_id, {"con": lib["con"], "sub": lib["sub"]}


def test_consent_applies_only_where_the_run_s_stored_list_still_names_the_document(
    lib_consent,
):
    conn, run, ids = lib_consent
    assert review_shown.consented_ids(conn, run, [ids["con"]]) == {ids["con"]}
    with conn:  # the stored list no longer names it (the record alone is not enough)
        review_shown.record_in(conn, run, [ids["sub"]], "t")
    assert review_shown.consented_ids(conn, run, [ids["con"]]) == frozenset()


def test_consent_does_not_cover_a_file_replaced_after_the_start(lib_consent):
    conn, run, ids = lib_consent
    with conn:
        conn.execute(
            "UPDATE documents SET sha256 = ? WHERE id = ?", ("99" * 32, ids["con"])
        )
    assert review_shown.consented_ids(conn, run, [ids["con"]]) == frozenset()


def test_a_document_blocked_after_the_start_is_refused_at_send_time_despite_the_consent(
    lib_consent,
):
    conn, run, ids = lib_consent
    from app import claude_spend

    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["72" * 32]})
    )
    with claude_approved.carrying([ids["con"]]), claude_spend.for_run(run):
        found = claude_approved.refusal()
    assert found is not None and "blocked" in found[1]


def test_consent_is_per_run_and_per_user(lib_consent):
    conn, run, ids = lib_consent
    from app import claude_spend

    with (
        claude_approved.carrying([ids["con"]]),
        claude_spend.for_run(run),
        claude_approved.acting_as("adm"),
    ):
        assert claude_approved.refusal() is None  # the user who started the run
    with (
        claude_approved.carrying([ids["con"]]),
        claude_spend.for_run(run),
        claude_approved.acting_as("someone-else"),
    ):
        found = (
            claude_approved.refusal()
        )  # a second user calling a Claude route on that run: no consent from it
    assert found is not None and ids["con"] in found[1]
    with claude_approved.carrying([ids["con"]]), claude_spend.for_run(run):
        assert (
            claude_approved.refusal() is None
        )  # the run's own background job (no caller named) is the run's requester
