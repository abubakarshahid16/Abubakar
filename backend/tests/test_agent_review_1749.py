"""Issue #1749 on INVENTED data: D2 (the AI reviewer asked no rule: a run with no per-rule scope decisions) and D1 (an illegal
class/word pair was stored, and one such row took the whole line list down with a 500)."""

# ruff: noqa: F811
from __future__ import annotations

import itertools

import pytest

from app import agent_review_items as it
from app import agent_review_jobs, agent_review_schema, db, submittal_review
from app import agent_review_wording as wording
from app.agent_review_verdict import RULE_NOT_APPROVED
from app.api import agent_review_schemas as contract
from tests import agent_review_support as s
from tests.test_agent_review_items import (  # noqa: F401 - the same invented rule book and labels
    KIND,
    PAPER,
    SKILL,
    STD,
    _label,
    con,
)
from tests.test_agent_review_routes import client, finished_run  # noqa: F401

# ---- D2 ------------------------------------------------------------------------------------------------------------


def _fresh_run(con, included=(STD,), run="run-fresh"):
    """A run that went through the classic SELECTION only: books chosen, no per-rule scope decision (what the AI reviewer's
    inline selection stores)."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS review_applicable_standards (review_run_id TEXT, standard_document_id TEXT, included INTEGER)"
    )
    con.execute(
        "INSERT INTO review_runs VALUES (?, ?, 'running', '2026-01-04')", (run, PAPER)
    )
    for d in included:
        con.execute(
            "INSERT INTO review_applicable_standards VALUES (?, ?, 1)", (run, d)
        )
    return run


def test_a_run_without_scope_decisions_is_seen_as_one(con):
    run = _fresh_run(con)
    assert it.has_scope_decisions(con, run) is False
    assert it.has_scope_decisions(con, None) is False
    assert it.has_scope_decisions(con, "run-new") is True


def test_the_old_path_asks_no_rule_for_a_run_with_no_scope_decisions(con):
    """The defect: candidates come only from stored per-rule decisions, so a run without them asks 0 and leaves out 0."""
    run = _fresh_run(con)
    doc = it.build_items(con, PAPER, KIND, skills=[SKILL], cache={}, run_id=run)
    assert doc["counts"]["rule"] == 0
    assert (
        sum(
            doc["rule_labels"]["counts"]["needs_another_paper"]
            .get("by_kind", {})
            .values()
        )
        == 0
    )


def test_the_rules_of_the_selected_books_are_the_candidates_each_asked_or_left_out_with_one_reason(
    con,
):
    run = _fresh_run(con)
    rows = it.selected_book_rows(con, run, {STD, PAPER})
    assert len(rows) == 8  # every stored rule of the one selected book
    doc = it.build_items(
        con, PAPER, KIND, skills=[SKILL], cache={}, run_id=run, requirement_rows=rows
    )
    asked = {i["rule_version_id"] for i in doc["items"] if i["source"] == "rule"}
    assert asked == {
        "r-limit",
        "r-coat",
        "r-table",
        "r-advice",
    }  # the labelled, AI-approved, datasheet ones
    left = doc["rule_labels"]["left_out"]
    ids = [str(x["rule_version_id"]) for x in left]
    assert len(ids) == len(set(ids))  # one reason each
    assert not asked & set(ids)
    assert len(asked) + len(left) + doc["rules_left_out"].get("stored_repeat", 0) == 8


def test_a_book_the_selection_did_not_include_is_not_a_candidate_and_is_counted_apart(
    con,
):
    con.execute("INSERT INTO documents VALUES ('doc_other', 'other.pdf')")
    con.execute(
        "INSERT INTO standard_requirements (id, standard_document_id, requirement_text, source_text, requirement_type)"
        " VALUES ('r-elsewhere', 'doc_other', 'x', 'x', 'statement')"
    )
    _label(con, "r-elsewhere")
    run = _fresh_run(con)
    rows = it.selected_book_rows(con, run, {STD, "doc_other"})
    assert "r-elsewhere" not in {r["id"] for r in rows}
    assert it.books_not_selected(con, run, "datasheet", {STD, "doc_other"}) == {
        "books": 1,
        "ai_approved_of_this_kind": 1,
    }


def test_a_book_the_caller_may_not_read_is_never_a_candidate(con):
    run = _fresh_run(con)
    assert it.selected_book_rows(con, run, {PAPER}) == []  # rule 5: an intersection


def test_plan_asks_the_selected_books_rules_when_no_scope_decisions_exist(
    tmp_path, monkeypatch
):
    """_plan end to end on the invented world: the inline selection stores no per-rule decision; the rules still get asked."""
    s.setup_world(tmp_path, monkeypatch)
    conn = db.connect()
    s.add_document(conn, "doc_std_x", "INV-STD-9.pdf", s.STD_PAGE)
    seen = {}

    def fake_build(_c, _p, _k, **kw):
        seen.update(kw)
        return {
            "rule_labels": {"summary_lines": []},
            "items": [],
            "paper_kind": "datasheet",
        }

    monkeypatch.setattr(agent_review_jobs, "_scope_run_id", lambda *_a: "rr")
    monkeypatch.setattr(agent_review_jobs.items_mod, "build_items", fake_build)
    monkeypatch.setattr(agent_review_jobs, "_write_rules", lambda *_a: None)
    monkeypatch.setattr(agent_review_jobs, "preflight", lambda *_a: None)
    monkeypatch.setattr(
        agent_review_jobs.claude_auto_approve, "on_review_start", lambda *_a: None
    )
    kind = agent_review_jobs.agent_review_kind.PaperReading(
        "datasheet", True, "r", "t", False, None, None
    )
    plan = agent_review_jobs._plan(
        conn, "rr", s.PAPER, frozenset({s.PAPER, "doc_std_x"}), kind, lambda: None
    )
    assert (
        seen["requirement_rows"] == []
    )  # by book: the list is passed (not None), here the book holds no rule
    assert plan["block"]["candidates"]["source"] == "the rules of the selected books"
    assert "no per-rule scope decision exists" in plan["block"]["summary_lines"][-1]


# ---- D1 ------------------------------------------------------------------------------------------------------------

LABELS = (
    wording.WORD_QUERY, wording.THINKS_MET, wording.THINKS_NOT_MET, "Pass", "Fail", wording.WORD_NOT_REVIEWED,
)  # fmt: skip


def _lines():
    """Every shape of line the core can classify: verdict x ai verdict x reason code x tier x error x silence x holds."""
    for verdict, ai, code, tier, err, silent, held in itertools.product(
        ("Pass", "Fail", "Query"),
        (None, "Pass", "Fail"),
        (None, "not_applicable", "sheet_silent"),
        (None, RULE_NOT_APPROVED),
        (None, "stop_max_tokens"),
        (False, True),
        (False, True),
    ):
        yield {
            "item_id": "S-1", "verdict": verdict, "ai_verdict": ai, "reason_code": code, "rule_tier": tier,
            "error": err, "silence_query": silent, "conditional_hold": held, "why": "w",
            **({"decided_by": "decided by code", "compare": {"decided": True, "verdict": "meets" if verdict == "Pass" else "does_not_meet"}} if verdict != "Query" else {}),
        }  # fmt: skip


def test_every_class_the_core_can_return_has_a_legal_pair_in_the_contract():
    seen = set()
    for line in _lines():
        cls, word = agent_review_jobs.contract_class_and_word(line)
        assert word in contract.LINE_TABLE[cls][0], (cls, word)
        seen.add((cls, word))
    assert (
        "Not applicable",
        "Not applicable",
    ) in seen  # the pair that was stored as ("Not applicable", "Query")
    assert {c for c, _ in seen} >= {
        "Proven by code", "AI opinion, engineer to confirm", "AI opinion, rule not yet approved",
        "Query for the engineer", "Not applicable", "Not reviewed",
    }  # fmt: skip


@pytest.mark.parametrize("cls", wording.CLASSES)
@pytest.mark.parametrize("label", LABELS)
def test_every_core_class_with_every_label_is_either_legal_or_refused_never_stored_wrong(
    cls, label
):
    word = contract.legal_word(cls, label)
    assert word is None or word in contract.LINE_TABLE[cls][0]


def test_a_pair_the_contract_refuses_is_not_stored_as_it_is(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    real = wording.apply
    monkeypatch.setattr(
        wording, "apply",
        lambda line: real(line) if line.get("error") else {**line, "verdict_class": "Proven by code", "verdict_label": "Query", "not_proven_reason": None},
    )  # fmt: skip
    with pytest.raises(agent_review_jobs.IllegalLine):
        agent_review_jobs.contract_class_and_word({"item_id": "S-1"})
    run_id = "r-refused"
    agent_review_schema.ensure_schema()
    line = {"item_id": "S-1", "verdict": "Query", "checklist": True, "tier": None}
    agent_review_jobs.store_line(run_id, line, None)
    row = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_line WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert (row["verdict_class"], row["word"]) == ("Not reviewed", "Not reviewed")
    assert "cannot carry the word" in row["reason"]
    assert line["error"].startswith(
        "refused at write"
    )  # the CRS copy sees the same line


def test_a_not_applicable_line_is_stored_with_the_contracts_own_word(
    tmp_path, monkeypatch
):
    s.setup_world(tmp_path, monkeypatch)
    run_id = "r-na"
    agent_review_schema.ensure_schema()
    line = {
        "item_id": "S-EQ-17",
        "verdict": "Query",
        "reason_code": "not_applicable",
        "checklist": True,
        "tier": None,
        "why": "w",
    }
    agent_review_jobs.store_line(run_id, line, None)
    row = dict(
        db.connect()
        .execute("SELECT * FROM agent_review_line WHERE run_id = ?", (run_id,))
        .fetchone()
    )
    assert (row["verdict_class"], row["word"]) == ("Not applicable", "Not applicable")


def test_the_line_list_reads_a_row_stored_with_the_old_pair_and_one_bad_row_does_not_take_it_down(
    client,
):
    run_id = finished_run(client)
    conn = db.connect()
    with conn:  # the row the live database holds, and one the contract can never accept
        conn.execute(
            "UPDATE agent_review_line SET verdict_class = 'Not applicable', word = 'Query' WHERE run_id = ? AND item_id = 'R-coat'",
            (run_id,),
        )
        conn.execute(
            "UPDATE agent_review_line SET verdict_class = 'Proven by code', word = 'Query' WHERE run_id = ? AND item_id = 'R-frame'",
            (run_id,),
        )
    r = client.get(f"/api/reviews/runs/{run_id}/agent/lines")
    assert r.status_code == 200, r.text
    by_id = {x["item_id"]: x for x in r.json()["lines"]}
    assert (by_id["R-coat"]["verdict_class"], by_id["R-coat"]["word"]) == (
        "Not applicable",
        "Not applicable",
    )
    assert (by_id["R-frame"]["verdict_class"], by_id["R-frame"]["word"]) == (
        "Not reviewed",
        "Not reviewed",
    )
    assert "could not be read" in by_id["R-frame"]["reason"]
    assert (
        by_id["R-mark"]["word"] == "AI verdict: not met"
    )  # a textual not met: no failed comparison, no absence proof  # the other lines are untouched
    stored = conn.execute(
        "SELECT word FROM agent_review_line WHERE run_id = ? AND item_id = 'R-coat'",
        (run_id,),
    ).fetchone()
    assert stored["word"] == "Query"  # old rows are not rewritten


# ---- review round R19: the page, the repeats, the real build, the narrowing, the two tables ---------------------------


def _real_plan_world(tmp_path, monkeypatch, *, with_decisions=False):
    """_plan on the REAL build_items over an invented library: 5 stored rules of one selected book (2 are the same rule),
    3 of them labelled AI approved for a datasheet; one more labelled rule sits in a book the run did not select."""
    s.setup_world(tmp_path, monkeypatch)
    submittal_review.ensure_schema()
    agent_review_schema.ensure_schema()
    conn = db.connect()
    s.add_document(conn, "doc_other", "INV-OTHER.pdf", s.STD_PAGE)
    run = "rr-real"
    with conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES (?,?, 'running','x','x')",
            (run, s.PAPER),
        )
        for rid, book, text in (
            ("req-a", s.STD, "frame width at least 40 mm"),
            ("req-b", s.STD, "coating in two layers"),
            ("req-c", s.STD, "marking colour blue"),
            ("req-d", s.STD, "an unlabelled statement"),
            ("req-a-twin", s.STD, "Frame width at least 40 mm."),
            ("req-z", "doc_other", "a rule in another book"),
        ):
            conn.execute(
                "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text, source_text,"
                " requirement_type, created_at, updated_at) VALUES (?,?,?,?,?,?,?,'x','x')",
                (rid, book, "1", 1, text, text, "statement"),
            )
        for n, (book, inc) in enumerate(((s.STD, 1), ("doc_other", 0))):
            conn.execute(
                "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id, included, created_at)"
                " VALUES (?,?,?,?,'x')",
                (f"ras-{n}", run, book, inc),
            )
    s.label_rows(conn, ["a", "b", "c", "z"])
    if with_decisions:
        from app import scope_ledger

        scope_ledger.ensure_schema()
        with conn:
            for rid in ("req-a", "req-b"):
                conn.execute(
                    "INSERT INTO review_scope_decisions VALUES (?,?,'checked','reached','x','code','x')",
                    (run, rid),
                )
    monkeypatch.setattr(agent_review_jobs, "_scope_run_id", lambda *_a: run)
    monkeypatch.setattr(agent_review_jobs, "preflight", lambda *_a: None)
    monkeypatch.setattr(
        agent_review_jobs.claude_auto_approve, "on_review_start", lambda *_a: None
    )
    kind = agent_review_jobs.agent_review_kind.PaperReading(
        "datasheet", True, "r", "t", False, None, None
    )
    plan = agent_review_jobs._plan(
        conn, run, s.PAPER, frozenset({s.PAPER, s.STD, "doc_other"}), kind, lambda: None
    )
    return conn, run, plan


def test_plan_with_the_real_builder_asks_rules_and_accounts_for_every_candidate(
    tmp_path, monkeypatch
):
    conn, run, plan = _real_plan_world(tmp_path, monkeypatch)
    asked = {i["rule_version_id"] for i in plan["items"] if i["source"] == "rule"}
    block = plan["block"]
    cand = block["candidates"]
    left = {str(x["rule_version_id"]) for x in block["left_out"]}
    assert asked == {"req-a", "req-b", "req-c"}
    assert cand["source"] == "the rules of the selected books" and cand["rows"] == 5
    assert cand["repeats"] == 1  # the twin
    assert (
        len(asked) + len(left) + cand["repeats"] == cand["rows"]
    )  # exactly: nothing lost, nothing counted twice
    assert not asked & left
    assert cand["books_not_selected"] == {"books": 1, "ai_approved_of_this_kind": 1}
    rows = conn.execute(
        "SELECT asked, COUNT(*) FROM agent_review_rule WHERE run_id = ? GROUP BY asked",
        (run,),
    ).fetchall()
    assert {r[0]: r[1] for r in rows}[1] == 3


def test_with_per_rule_scope_decisions_the_candidates_are_those_decisions_as_before(
    tmp_path, monkeypatch
):
    _conn, _run, plan = _real_plan_world(tmp_path, monkeypatch, with_decisions=True)
    asked = {i["rule_version_id"] for i in plan["items"] if i["source"] == "rule"}
    assert asked == {
        "req-a",
        "req-b",
    }  # only the rules the stored decisions name, not the whole book
    assert plan["block"]["candidates"]["source"] == "per-rule scope decisions"
    assert not any(
        "rules came from the rule books" in x for x in plan["block"]["summary_lines"]
    )


def test_books_not_selected_counts_only_books_the_caller_may_read(con):
    con.execute("INSERT INTO documents VALUES ('doc_other', 'other.pdf')")
    con.execute(
        "INSERT INTO standard_requirements (id, standard_document_id, requirement_text, source_text, requirement_type)"
        " VALUES ('r-else', 'doc_other', 'x', 'x', 'statement')"
    )
    _label(con, "r-else")
    run = _fresh_run(con)
    assert (
        it.books_not_selected(con, run, "datasheet", {STD})["ai_approved_of_this_kind"]
        == 0
    )
    assert (
        it.books_not_selected(con, run, "datasheet", {STD, "doc_other"})[
            "ai_approved_of_this_kind"
        ]
        == 1
    )


def test_the_rules_used_route_says_where_the_rules_came_from_and_keeps_it_after_a_restart(
    client,
):
    run_id = finished_run(client)
    body = client.get(f"/api/reviews/runs/{run_id}/rules-used").json()
    assert body["candidates_from"] == "the rules of the selected books"
    assert body["same_rule_repeats"] == 0
    assert body["other_books"] == {
        "books": 0,
        "ai_approved_rules": 0,
        "boundary": "rule books the person who started this review may read",
    }
    db.reset_connection()  # a restart: only what the run row stored is left
    again = client.get(f"/api/reviews/runs/{run_id}/rules-used").json()
    assert (
        again["candidates_from"] == body["candidates_from"]
        and again["other_books"] == body["other_books"]
    )


def test_an_old_run_without_it_shows_null_never_zero(client):
    run_id = finished_run(client)
    with db.connect() as conn:
        conn.execute(
            "UPDATE agent_review_run SET equipment_json = '{}' WHERE run_id = ?",
            (run_id,),
        )
    body = client.get(f"/api/reviews/runs/{run_id}/rules-used").json()
    assert (
        body["candidates_from"],
        body["same_rule_repeats"],
        body["other_books"],
    ) == (None, None, None)


def test_the_database_copy_of_the_class_word_tier_table_equals_the_contracts():
    assert set(agent_review_schema.CLASSES) == set(contract.LINE_TABLE)
    words = {w for ws, _t in contract.LINE_TABLE.values() for w in ws}
    tiers = {t for _w, ts in contract.LINE_TABLE.values() for t in ts if t is not None}
    assert set(agent_review_schema.WORDS) == words
    assert set(agent_review_schema.TIERS) == tiers
