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


# ---- the page record: a run that reads no page never replaces a good reading (owner, 12 Nov) -------------------------


def _page_world(tmp_path, monkeypatch, *, ledger_pages):
    import json

    from app import comparison, db, submittal_review

    s.setup_world(tmp_path, monkeypatch)
    submittal_review.ensure_schema()
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, completed_at, outcome_json)"
            " VALUES ('old-normal', ?, 'completed', '2026-11-01', '2026-11-01', '2026-11-01T10:00:00Z', ?)",
            (
                s.PAPER,
                json.dumps(
                    {"page_coverage": {"pages_total": 5, "pages_read": [1, 2, 3, 4, 5]}}
                ),
            ),
        )
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at)"
            " VALUES ('ai-run', ?, 'running', '2026-11-11', '2026-11-11')",
            (s.PAPER,),
        )
    monkeypatch.setattr(
        comparison,
        "pages_read_with_reading",
        lambda _d: {"pages_total": ledger_pages or None},
    )
    return conn


def _outcome(conn, run="ai-run"):
    import json

    row = conn.execute(
        "SELECT outcome_json FROM review_runs WHERE id = ?", (run,)
    ).fetchone()
    return json.loads(row["outcome_json"])


def test_a_stored_reading_with_pages_survives_an_ai_review_that_reads_none(
    tmp_path, monkeypatch
):
    conn = _page_world(tmp_path, monkeypatch, ledger_pages=0)
    agent_review_jobs._done(
        conn, "job-x", "ai-run", {"partial": False, "stop_reason": None, "counts": {}}
    )
    cov = _outcome(conn)["page_coverage"]
    assert cov["pages_total"] == 5
    assert (
        cov["carried_from_run"] == "old-normal"
        and cov["carried_from_at"] == "2026-11-01T10:00:00Z"
    )


def test_the_papers_current_ledger_is_used_when_it_holds_pages(tmp_path, monkeypatch):
    conn = _page_world(tmp_path, monkeypatch, ledger_pages=7)
    agent_review_jobs._done(
        conn, "job-x", "ai-run", {"partial": False, "stop_reason": None, "counts": {}}
    )
    cov = _outcome(conn)["page_coverage"]
    assert cov["pages_total"] == 7 and "carried_from_run" not in cov


def test_with_no_reading_anywhere_no_page_record_is_invented(tmp_path, monkeypatch):
    conn = _page_world(tmp_path, monkeypatch, ledger_pages=0)
    with conn:
        conn.execute("DELETE FROM review_runs WHERE id = 'old-normal'")
    agent_review_jobs._done(
        conn, "job-x", "ai-run", {"partial": False, "stop_reason": None, "counts": {}}
    )
    assert "page_coverage" not in _outcome(conn)
