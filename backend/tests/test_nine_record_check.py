"""`scripts/nine_record_check.py`: a whole fake run's record holds, and each invariant fails on its own planted fault. Invented paper and
books; the fake model; no paid call, no socket."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import aim_review, aim_review_jobs, aim_review_store
from app.aim_review import engine as E
from app.aim_review import roles, updates
from app.config import settings
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import nine_record_check as NRC

RUN = "run_nine_check"


@pytest.fixture
def ran(tmp_path, monkeypatch):
    gen = open_aim_db(tmp_path, monkeypatch)
    conn = next(gen)
    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    with conn:
        aim_review_store.start_run(conn, RUN, PAPER, "2026-11-26T00:00:00Z")
    result = aim_review.run(conn, run_id=RUN, paper_id=PAPER, allowed_books=frozenset({BOOK_A, BOOK_B}), store=MemoryStore(),
                            max_usd=5.0, model=E.FakeModel(kind="datasheet", subject_key="test_item"))  # fmt: skip
    body = aim_review_jobs._result_dict(result)
    with conn:
        aim_review_store.finish_run(conn, RUN, body, "2026-11-26T00:01:00Z")
    updates.nine_end(RUN, body)
    yield conn
    next(gen, None)


def test_a_whole_fake_runs_record_holds(ran):
    assert NRC.check(ran, RUN) == []


def _one(conn, sql, args=()):
    with conn:
        conn.execute(sql, args)


def test_a_missing_role_row_is_a_problem(ran):
    _one(ran, f"DELETE FROM {roles.ROLES} WHERE run_id = ? AND role_no = 9", (RUN,))
    assert any("role rows" in p for p in NRC.check(ran, RUN))


def test_a_call_left_sent_is_a_problem(ran):
    _one(
        ran,
        f"UPDATE {roles.CALLS} SET state = 'sent' WHERE run_id = ? AND step = 'aim_identify'",
        (RUN,),
    )
    assert any("still 'sent'" in p for p in NRC.check(ran, RUN))


def test_a_page_the_document_does_not_hold_is_a_problem(ran):
    _one(
        ran,
        f"UPDATE {roles.READS} SET pages_json = '[999]' WHERE run_id = ? AND document_kind = 'paper'",
        (RUN,),
    )
    assert any("does not hold" in p for p in NRC.check(ran, RUN))


def test_a_claude_read_of_a_document_off_the_shown_list_is_a_problem(ran):
    from app import review_shown

    with ran:
        review_shown.record_in(ran, RUN, [PAPER, BOOK_B], "2026-11-26T00:00:00Z")
    assert any(
        f"document {BOOK_A}" in p and "shown list" in p for p in NRC.check(ran, RUN)
    )
    with ran:
        review_shown.record_in(
            ran, RUN, [PAPER, BOOK_A, BOOK_B], "2026-11-26T00:00:00Z"
        )
    assert NRC.check(ran, RUN) == []


def test_calls_that_differ_from_the_runs_stored_calls_are_a_problem(ran):
    _one(
        ran,
        f"DELETE FROM {roles.CALLS} WHERE run_id = ? AND step = 'aim_identify'",
        (RUN,),
    )
    got = NRC.check(ran, RUN)
    assert any("role 1" in p and "call row" in p for p in got)
    stored = json.loads(
        ran.execute(
            "SELECT calls_json FROM aim_runs WHERE run_id = ?", (RUN,)
        ).fetchone()[0]
    )
    _one(
        ran,
        "UPDATE aim_runs SET calls_json = ? WHERE run_id = ?",
        (json.dumps([c for c in stored if c.get("step") != "aim_select"]), RUN),
    )
    assert any("step aim_select" in p for p in NRC.check(ran, RUN))


def test_a_count_that_differs_from_its_rows_is_a_problem(ran):
    _one(ran, f"UPDATE {roles.ROLES} SET produced_json = ? WHERE run_id = ? AND role_no = 1",
         (json.dumps({"calls_answered": 7, "paper_pages_sent": 1}), RUN))  # fmt: skip
    got = NRC.check(ran, RUN)
    assert any("calls_answered" in p for p in got) and any(
        "paper_pages_sent" in p for p in got
    )


def test_a_database_with_no_record_says_so_and_the_script_exits_one(
    tmp_path, monkeypatch
):
    gen = open_aim_db(tmp_path, monkeypatch)
    conn = next(gen)
    try:
        assert NRC.check(conn, "run_x") == [
            "no role record in this database (the record was off for every run)"
        ]
        assert NRC.main(["--db", str(settings.db_path), "--run", "run_x"]) == 1
    finally:
        next(gen, None)


def _ledger_from_record(conn) -> list[dict]:
    """The ledger lines a real run of these calls would write: one reservation per Claude call, with the documents it carried."""
    lines = []
    for c in conn.execute(
        f"SELECT call_id, step FROM {roles.CALLS} WHERE run_id = ? AND state = 'answered'",
        (RUN,),
    ).fetchall():
        docs = [
            r[0]
            for r in conn.execute(
                f"SELECT document_id FROM {roles.READS} WHERE call_id = ?", (c[0],)
            )
        ]
        lines.append(
            {
                "run": RUN,
                "step": c[1],
                "reserved": True,
                "sent_documents": [{"document_id": d} for d in docs],
            }
        )
        lines.append({"run": RUN, "step": c[1], "settles": "r"})
    return lines


def test_every_ledger_reservation_must_match_a_record_call_by_step_and_documents(ran):
    lines = _ledger_from_record(ran)
    assert NRC.ledger_problems(ran, RUN, lines) == ([], 0)
    # a call the record does not show: the ledger saw a book leave that no record call of that step declares
    planted = [
        *lines,
        {
            "run": RUN,
            "step": "aim_judge",
            "reserved": True,
            "sent_documents": [{"document_id": "doc_not_declared"}],
        },
    ]
    problems, _n = NRC.ledger_problems(ran, RUN, planted)
    assert len(problems) == 1 and "aim_judge" in problems[0]
    # a record call with no ledger line (answered from the stored answers): counted, not a problem
    problems, n = NRC.ledger_problems(ran, RUN, lines[2:])
    assert problems == [] and n == 1
    # another run's lines are not this run's
    assert NRC.ledger_problems(ran, RUN, [{**planted[-1], "run": "other"}]) == (
        [],
        len(lines) // 2,
    )
