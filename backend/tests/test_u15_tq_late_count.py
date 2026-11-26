"""The technical-query counts say how many open queries are late (owner's E5, 26 Nov 2026: in, waiting, late, done) and how many open
ones have a due date at all, so 'late' states its boundary. Invented queries only."""

from __future__ import annotations

from app import db
from app.technical_queries import import_message, metrics
from tests.test_technical_queries import envelope
from tests.test_tq_g_feature_off import on, storage  # noqa: F401 - helpers, fixture


def _query(name: str) -> str:
    """One query of its own (each mail its own thread: mails of one thread join one query)."""
    return import_message({**envelope(name), "provider_thread_id": f"thread-{name}"}, "u1", False, False)[0]["id"]


def _set(query_id: str, status: str, due: str | None) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE technical_queries SET status=?, due_at=? WHERE id=?", (status, due, query_id))


def test_an_open_query_past_its_due_date_is_late_and_a_closed_one_never_is(monkeypatch):
    on(monkeypatch)
    ids = [_query(f"late-{n}") for n in range(5)]
    _set(ids[0], "drafting", "2020-01-01")  # open, past due: late
    _set(ids[1], "awaiting_review", "2999-01-01")  # open, due later: not late
    _set(ids[2], "drafting", None)  # open, no due date: never late, not in the boundary
    _set(ids[3], "resolved", "2020-01-01")  # closed: never late
    _set(ids[4], "triage", "2020-01-02")  # open, past due: late
    got = metrics("u1", True, False)
    assert got["overdue"] == 2
    assert got["open_with_due_date"] == 3
    assert got["total"] == 5 and got["resolved"] == 1


def test_the_late_count_keeps_the_filter(monkeypatch):
    on(monkeypatch)
    a = _query("late-a")
    _set(a, "drafting", "2020-01-01")
    with db.connect() as conn:
        conn.execute("UPDATE technical_queries SET contractor_name='Invented A' WHERE id=?", (a,))
    assert metrics("u1", True, False, contractor="Invented A")["overdue"] == 1
    assert metrics("u1", True, False, contractor="Invented B")["overdue"] == 0


def test_an_empty_due_date_is_no_due_date(monkeypatch):
    on(monkeypatch)
    q = _query("late-empty")
    _set(q, "drafting", "")
    got = metrics("u1", True, False)
    assert got["overdue"] == 0 and got["open_with_due_date"] == 0
