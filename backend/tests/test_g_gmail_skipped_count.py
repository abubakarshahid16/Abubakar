"""The import job never counts a listed message that was not imported as "imported" (owner's first live import, 26 Nov 2026: 77 listed,
36 imported, the page said "imported 77 of 77"). Invented messages and addresses; no Gmail, no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import db, gmail_import_jobs, gmail_worker
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "g.sqlite")
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        gmail_import_jobs.create_tables(conn)
    yield
    db.reset_connection()


def _msg(sender: str, labels=("L1",)):
    return SimpleNamespace(
        from_address=sender,
        label_ids=list(labels),
        subject="Invented subject",
        provider_message_id="x",
    )


def test_the_skip_rule_names_own_mail_and_another_label():
    assert (
        gmail_worker.skip_reason(
            _msg("Box <box@example.test>"), "L1", "box@example.test"
        )
        == gmail_worker.OWN_MAIL
    )
    assert (
        gmail_worker.skip_reason(
            _msg("a@vendor.example", ("L2",)), "L1", "box@example.test"
        )
        == gmail_worker.OTHER_LABEL
    )
    assert (
        gmail_worker.skip_reason(_msg("a@vendor.example"), "L1", "box@example.test")
        is None
    )


def test_the_job_counts_our_replies_apart_and_says_imported_only_of_the_rest(
    monkeypatch,
):
    from app import technical_query_replies as R

    senders = {
        "m1": "a@vendor.example",
        "m2": "box@example.test",
        "m3": "box@example.test",
        "m4": "b@vendor.example",
    }
    client = SimpleNamespace(
        list_message_ids=lambda label: list(senders),
        message=lambda mid: _msg(senders[mid]),
    )

    def fake(
        client, mid, **kw
    ):  # the importer: our own mail is kept with its query (`technical_query_replies`), never a query
        return (
            {"own_reply": R.ATTACHED}
            if senders[mid].startswith("box@")
            else {"query_id": "q"}
        )

    monkeypatch.setattr(gmail_worker, "_process_message", fake)
    job_id = gmail_import_jobs.enqueue("mb", "import", "L1")
    monkeypatch.setattr(gmail_import_jobs, "_checked", lambda mailbox_id: None)
    gmail_import_jobs._import(
        job_id,
        client,
        {"id": "mb", "email": "box@example.test", "owner_user_id": "u1"},
        "L1",
        None,
    )
    with db.connect() as conn:
        job = gmail_import_jobs.latest(conn, "mb")
    assert job["total"] == 4 and job["done"] == 4 and job["failed"] == 0
    assert job["imported"] == 2 and job["skipped"] == {
        R.ATTACHED: 2
    }  # never "imported 4 of 4"
    with db.connect() as conn:
        assert json.loads(
            conn.execute(
                "SELECT skipped_json FROM gmail_import_jobs WHERE id=?", (job_id,)
            ).fetchone()[0]
        ) == {R.ATTACHED: 2}


# ---- our own replies are kept with the query they answer, marked sent by us (lead-4, 26 Nov 2026)
from app import technical_query_replies as replies  # noqa: E402


def _mail(
    mid,
    sender,
    thread,
    subject="PRJ-INV-TQ-7 - Invented question",
    labels=("L1",),
    when="2026-11-20T10:00:00Z",
):
    return SimpleNamespace(provider_message_id=mid, thread_id=thread, from_address=sender, to_addresses=["box@example.test"], cc_addresses=[],
                           subject=subject, body="Invented body.", received_at=when, attachments=[], label_ids=list(labels))  # fmt: skip


@pytest.fixture
def tq(monkeypatch):
    from app import technical_queries

    monkeypatch.setattr(settings, "technical_queries_enabled", True)
    monkeypatch.setattr(settings, "upload_dir", settings.data_dir / "uploads")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES ('u1','u1@example.test','U','x','2026-01-01T00:00:00Z')"
        )
    technical_queries.ensure_schema()


def _client(mails):
    return SimpleNamespace(
        list_message_ids=lambda label: [m.provider_message_id for m in mails],
        message=lambda mid: next(m for m in mails if m.provider_message_id == mid),
        raw_message=lambda mid: b"From: invented\r\n\r\nbody",
    )


def _counts():
    with db.connect() as conn:
        queries = conn.execute("SELECT COUNT(*) FROM technical_queries").fetchone()[0]
        rows = conn.execute(
            "SELECT provider_message_id, is_inbound, query_id FROM query_messages ORDER BY provider_message_id"
        ).fetchall()
    return queries, [(r[0], r[1]) for r in rows], {r[2] for r in rows}


def test_our_reply_read_before_the_question_is_kept_with_its_query_and_never_makes_a_query(
    monkeypatch, tq
):
    # Gmail lists the newest first: our reply comes before the contractor's question it answers
    mails = [_mail("m2-ours", "Box <box@example.test>", "t1", "RE: PRJ-INV-TQ-7 - Invented question", when="2026-11-21T10:00:00Z"),
             _mail("m1-theirs", "a@vendor.example", "t1")]  # fmt: skip
    monkeypatch.setattr(gmail_import_jobs, "_checked", lambda mailbox_id: None)
    job_id = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs._import(
        job_id,
        _client(mails),
        {"id": "mb", "email": "box@example.test", "owner_user_id": "u1"},
        "L1",
        None,
    )
    queries, messages, query_ids = _counts()
    assert queries == 1 and len(query_ids) == 1  # one query, our reply inside it
    assert messages == [("m1-theirs", 1), ("m2-ours", 0)]  # ours marked sent by us
    with db.connect() as conn:
        job = gmail_import_jobs.latest(conn, "mb")
    assert (
        job["imported"] == 1
        and job["skipped"] == {replies.ATTACHED: 1}
        and job["queries"] == 1
        and job["failed"] == 0
    )


def test_our_reply_with_no_query_of_its_thread_or_number_stores_nothing(
    monkeypatch, tq
):
    mails = [_mail("m9-ours", "box@example.test", "t9", "Invented note with no number")]
    monkeypatch.setattr(gmail_import_jobs, "_checked", lambda mailbox_id: None)
    job_id = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs._import(
        job_id,
        _client(mails),
        {"id": "mb", "email": "box@example.test", "owner_user_id": "u1"},
        "L1",
        None,
    )
    assert _counts()[:2] == (0, [])
    with db.connect() as conn:
        assert gmail_import_jobs.latest(conn, "mb")["skipped"] == {replies.NO_QUERY: 1}


def test_a_poll_keeps_our_reply_with_its_query_at_once(tq):
    from app import gmail_worker as W

    client = _client(
        [
            _mail("m1", "a@vendor.example", "t1"),
            _mail(
                "m2", "box@example.test", "t1", "RE: PRJ-INV-TQ-7 - Invented question"
            ),
        ]
    )
    out = W.process_history(
        client,
        "1",
        "u1",
        mailbox_id="mb",
        message_ids=["m1", "m2"],
        label_id="L1",
        mailbox_address="box@example.test",
    )
    assert out[-1]["own_reply"] == replies.ATTACHED
    assert _counts()[:2] == (1, [("m1", 1), ("m2", 0)])
    # importing the same reply again stores nothing new
    W.process_history(
        client,
        "1",
        "u1",
        mailbox_id="mb",
        message_ids=["m2"],
        label_id="L1",
        mailbox_address="box@example.test",
    )
    assert _counts()[:2] == (1, [("m1", 1), ("m2", 0)])


def test_an_import_from_before_the_reasons_were_counted_says_so_and_counts_what_is_stored(
    tq,
):
    from app import technical_queries

    job_id = gmail_import_jobs.enqueue("mb", "import", "L1")
    with (
        db.connect() as conn
    ):  # as the owner's first import was stored: done 3 of 3, no reasons column value
        conn.execute(
            "UPDATE gmail_import_jobs SET state='done', total=3, done=3, skipped_json=NULL WHERE id=?",
            (job_id,),
        )
    technical_queries.import_message(
        {"provider": "gmail", "mailbox_id": "mb", "provider_message_id": "m1", "provider_thread_id": "t1", "from_address": "a@vendor.example",
         "to_addresses": [], "cc_addresses": [], "subject": "PRJ-INV-TQ-7 - Invented question", "body": "Invented.", "attachments": []},
        "u1",
    )  # fmt: skip
    with db.connect() as conn:
        job = gmail_import_jobs.latest(conn, "mb")
    assert (
        job["reasons_recorded"] is False
        and job["messages"] == 1
        and job["queries"] == 1
    )


def test_a_new_import_records_its_reasons_from_the_start(monkeypatch):
    client = SimpleNamespace(
        list_message_ids=lambda label: [], message=lambda mid: None
    )
    monkeypatch.setattr(gmail_import_jobs, "_checked", lambda mailbox_id: None)
    job_id = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs._import(
        job_id,
        client,
        {"id": "mb", "email": "box@example.test", "owner_user_id": "u1"},
        "L1",
        None,
    )
    with db.connect() as conn:
        assert gmail_import_jobs.latest(conn, "mb")["reasons_recorded"] is True


def test_importing_the_label_again_adds_only_what_is_missing_and_never_a_second_query(
    monkeypatch, tq
):
    mails = [
        _mail("m1-theirs", "a@vendor.example", "t1"),
        _mail(
            "m2-ours", "box@example.test", "t1", "RE: PRJ-INV-TQ-7 - Invented question"
        ),
    ]
    monkeypatch.setattr(gmail_import_jobs, "_checked", lambda mailbox_id: None)
    box = {"id": "mb", "email": "box@example.test", "owner_user_id": "u1"}
    first = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs._import(
        first, _client(mails[:1]), box, "L1", None
    )  # the first import saw only the question
    with db.connect() as conn:
        conn.execute("UPDATE gmail_import_jobs SET state='done' WHERE id=?", (first,))
    again = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs._import(again, _client(mails), box, "L1", None)
    queries, messages, _ = _counts()
    assert queries == 1 and messages == [
        ("m1-theirs", 1),
        ("m2-ours", 0),
    ]  # the missing reply is in; nothing twice
    with db.connect() as conn:
        job = gmail_import_jobs.latest(conn, "mb")
    assert (
        job["skipped"] == {replies.ALREADY: 1, replies.ATTACHED: 1}
        and job["imported"] == 0
    )
    with db.connect() as conn:
        conn.execute("UPDATE gmail_import_jobs SET state='done' WHERE id=?", (again,))
    third = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs._import(
        third, _client(mails), box, "L1", None
    )  # a repeat adds nothing
    assert _counts()[:2] == (1, [("m1-theirs", 1), ("m2-ours", 0)])
    with db.connect() as conn:
        assert gmail_import_jobs.latest(conn, "mb")["skipped"] == {replies.ALREADY: 2}


def test_a_new_query_from_the_mailbox_is_queued_for_evidence_once_and_a_follow_up_is_not(
    monkeypatch, tq
):
    from app import gmail_worker as W
    from app import technical_query_jobs

    started = []
    monkeypatch.setattr(technical_query_jobs, "start", lambda: started.append(1))
    client = _client(
        [
            _mail("m1", "a@vendor.example", "t1"),
            _mail(
                "m2", "a@vendor.example", "t1", "RE: PRJ-INV-TQ-7 - Invented question"
            ),
        ]
    )
    W.process_history(
        client,
        "1",
        "u1",
        mailbox_id="mb",
        message_ids=["m1", "m2"],
        label_id="L1",
        mailbox_address="box@example.test",
    )
    with db.connect() as conn:
        jobs = conn.execute("SELECT state FROM query_evidence_jobs").fetchall()
    assert [j[0] for j in jobs] == [
        "queued"
    ]  # one query, one job, waiting for the app's one evidence thread
    assert started == []  # the import never starts a second thread of its own
