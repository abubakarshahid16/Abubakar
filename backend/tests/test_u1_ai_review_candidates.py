"""#1780 on INVENTED data: an AI review started on a paper that already has a normal review (stored per-rule scope decisions)
asks the same rules as a fresh run; the decisions only ADD candidates, never shrink them."""

from __future__ import annotations

from app import agent_review_items as it
from app import agent_review_jobs, scope_ledger
from tests import agent_review_support as s
from tests.test_agent_review_1749 import _real_plan_world


def _asked(plan):
    return {i["rule_version_id"] for i in plan["items"] if i["source"] == "rule"}


def test_same_paper_with_and_without_stored_decisions_asks_the_same_rules(
    tmp_path, monkeypatch
):
    _c, _r, fresh = _real_plan_world(tmp_path, monkeypatch)
    _c, _r, existing = _real_plan_world(
        tmp_path / "b", monkeypatch, with_decisions=True
    )
    assert _asked(existing) >= _asked(fresh) == {"req-a", "req-b", "req-c"}
    # and every candidate of the fresh run is still counted in the existing-run case
    assert (
        existing["block"]["candidates"]["rows"] >= fresh["block"]["candidates"]["rows"]
    )


def test_a_decision_rule_outside_the_selected_books_is_added_not_lost(
    tmp_path, monkeypatch
):
    conn, run, _plan = _real_plan_world(tmp_path, monkeypatch, with_decisions=True)
    scope_ledger.ensure_schema()
    with conn:
        conn.execute(
            "INSERT INTO review_scope_decisions VALUES (?,?,'checked','reached','x','code','x')",
            (run, "req-z"),  # a labelled rule of a book the selection did not include
        )
    allowed = frozenset({s.PAPER, s.STD, "doc_other"})
    kind = {"kind": "datasheet", "known": True, "method": "r", "guess": False}
    doc = it.build_items_for_run(conn, s.PAPER, kind, run, allowed, cache={}, equipment_type=None, ask_unapproved="off")  # fmt: skip
    got = {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}
    assert got == {"req-a", "req-b", "req-c", "req-z"}


def test_a_decision_rule_in_a_book_the_caller_may_not_read_is_not_added(
    tmp_path, monkeypatch
):
    conn, run, _plan = _real_plan_world(tmp_path, monkeypatch, with_decisions=True)
    with conn:
        conn.execute(
            "INSERT INTO review_scope_decisions VALUES (?,?,'checked','reached','x','code','x')",
            (run, "req-z"),
        )
    kind = {"kind": "datasheet", "known": True, "method": "r", "guess": False}
    doc = it.build_items_for_run(conn, s.PAPER, kind, run, frozenset({s.PAPER, s.STD}), cache={}, equipment_type=None, ask_unapproved="off")  # fmt: skip
    got = {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}
    assert "req-z" not in got  # rule 5: an intersection


def test_decisions_that_left_a_rule_out_do_not_keep_it_out(tmp_path, monkeypatch):
    """The live defect: the old engine marked most rules 'does not apply'/'needs another paper'; that must not shrink the set."""
    conn, run, _plan = _real_plan_world(tmp_path, monkeypatch, with_decisions=True)
    with conn:
        conn.execute(
            "INSERT INTO review_scope_decisions VALUES (?,?,'does_not_apply','other_paper','x','code','x')",
            (run, "req-c"),
        )
    kind = {"kind": "datasheet", "known": True, "method": "r", "guess": False}
    doc = it.build_items_for_run(conn, s.PAPER, kind, run, frozenset({s.PAPER, s.STD, "doc_other"}), cache={}, equipment_type=None, ask_unapproved="off")  # fmt: skip
    got = {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}
    assert "req-c" in got


def test_the_taken_from_sentence_is_true_in_each_case(tmp_path, monkeypatch):
    _c, _r, fresh = _real_plan_world(tmp_path, monkeypatch)
    _c, _r, existing = _real_plan_world(
        tmp_path / "b", monkeypatch, with_decisions=True
    )
    assert fresh["block"]["candidates"]["source"] == it.SOURCE_BOOKS
    assert existing["block"]["candidates"]["source"] == it.SOURCE_BOTH
    assert agent_review_jobs  # imported for the monkeypatched _plan
