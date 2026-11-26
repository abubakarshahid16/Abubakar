"""Question rules 4 (lead-4's live walk, 26 Nov 2026: queries prepared before update 15's fixes kept their old proposals): a query
prepared under rules 3 with no confirmed question is prepared again by "Prepare evidence for all"; an engineer's confirmed question is
never re-proposed. Invented queries only."""

from __future__ import annotations

from app import db
from app import technical_query_jobs as J

from .test_g_gmail_skipped_count import (  # noqa: F401 - fixtures used by name (temp_storage is autouse there)
    temp_storage,
    tq,
)


def _query(n: int):
    from app import technical_queries

    q, _ = technical_queries.import_message(
        {"provider": "gmail", "mailbox_id": "mb", "provider_message_id": f"r4-{n}", "provider_thread_id": f"r4-t{n}", "from_address":
         "a@vendor.example", "to_addresses": [], "cc_addresses": [], "subject": f"PRJ-INV-TQ-{n} - Invented", "body": "Invented?",
         "attachments": []}, "u1")  # fmt: skip
    return q["id"]


def test_a_query_prepared_under_rules_3_is_prepared_again_unless_its_question_was_confirmed(monkeypatch, temp_storage, tq):  # noqa: F811
    monkeypatch.setattr(J, "start", lambda: None)  # no thread in a test: the jobs stay queued
    old, confirmed, current = _query(1), _query(2), _query(3)
    with db.connect() as conn:
        for qid, rules in ((old, 3), (confirmed, 3), (current, J.QUESTION_RULES)):
            job = J.enqueue(qid, frozenset(), "u1", True, False)
            conn.execute("UPDATE query_evidence_jobs SET state='done', question_rules=? WHERE id=?", (rules, job))
        conn.execute("UPDATE technical_queries SET confirmed_question='Invented confirmed question?' WHERE id=?", (confirmed,))
        assert J.QUESTION_RULES == 4
        assert J.unprepared(conn) == [old]
