"""Chat answers "which technical queries are waiting for their evidence" by code (lead-4, 26 Nov 2026, G7): through the queries' own
visibility rule (the reader's own or assigned queries; an administrator sees all), a query counts as waiting when its newest
evidence job is queued or running, the same thing the queries page shows as "Preparing the evidence". Invented mail only."""

from __future__ import annotations

from app import chat_records as R
from app import db, technical_query_jobs
from app.config import settings
from tests.test_technical_queries import (  # noqa: F401 - the autouse fixture
    envelope,
    import_message,
    temp_storage,
)


def _query(n: int, owner: str = "u1") -> str:
    mail = {
        **envelope(f"message-{n}"),
        "provider_thread_id": f"thread-{n}",
    }  # one query per invented thread
    q, _dup = import_message(mail, owner, False, False)
    return q["id"]


def test_the_queries_waiting_for_evidence_are_counted_through_their_own_visibility():
    a, b, c, d = _query(1), _query(2), _query(3), _query(4, owner="owner")
    for q in (a, b, c, d):
        technical_query_jobs.enqueue(q, [], "u1", False, False, start_thread=False)
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {technical_query_jobs.TABLE} SET state='running' WHERE query_id=?",
            (b,),
        )
        conn.execute(
            f"UPDATE {technical_query_jobs.TABLE} SET state='done' WHERE query_id=?",
            (c,),
        )
    mine = R.queries_waiting("u1", False)
    assert mine.startswith(
        "2 of 3 technical queries are waiting for their evidence (1 queued, 1 being prepared)"
    )
    assert R.TQ_BOUNDARY in mine and mine.count("\n- ") == 2
    assert R.queries_waiting("someone-else", False).startswith(
        "0 of 0 technical queries"
    )  # sees none of them
    assert R.queries_waiting("someone-else", True).startswith(
        "3 of 4 technical queries"
    )  # an administrator sees all


def test_a_query_whose_evidence_failed_is_said_apart():
    q = _query(1)
    technical_query_jobs.enqueue(q, [], "u1", False, False, start_thread=False)
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {technical_query_jobs.TABLE} SET state='failed' WHERE query_id=?",
            (q,),
        )
    assert "The evidence of 1 could not be prepared." in R.queries_waiting("u1", False)


def test_with_technical_queries_switched_off_it_says_it_cannot_answer(monkeypatch):
    monkeypatch.setattr(settings, "technical_queries_enabled", False)
    assert R.queries_waiting("u1", True).startswith(R.CANNOT)
