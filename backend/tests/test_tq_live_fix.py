"""The owner's own test of 26 Nov 2026: "Activate label" must save and survive a reload, the import is a background job with progress, a failed message
never stops the rest, "Check now", and the subject's TQ/CFC number is the query's identity. Fake Gmail client; INVENTED subjects only."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

import app as app_pkg
from app import db, gmail_import_jobs, gmail_sync
from app import technical_queries as tq
from app import technical_query_subject as S
from app.access import AccessScope
from app.api import technical_queries as api
from app.config import settings
from app.gmail_client import GmailMessage
from tests.test_tq_g_feature_off import on, storage  # noqa: F401 - helpers, fixture

REVIEWER = frozenset({"admin", tq.REVIEWER_CAPABILITY})
OWNER = AccessScope("u1", frozenset(), capabilities=REVIEWER)


class FakeClient:
    """A fake Gmail: `subjects` are the labelled messages; a subject in `broken` fails when its raw message is read."""

    def __init__(self, subjects, broken=(), labels=("L1",)):
        self.subjects, self.broken, self._labels, self.calls = (
            list(subjects),
            set(broken),
            labels,
            [],
        )

    def labels(self):
        self.calls.append("labels")
        return [{"id": i, "name": i, "type": "user"} for i in self._labels]

    def list_message_ids(self, label):
        self.calls.append("list")
        return [f"m{i}" for i in range(len(self.subjects))]

    def message(self, message_id):
        self.calls.append(f"message {message_id}")
        n = int(message_id[1:])
        return GmailMessage(
            provider_message_id=message_id, thread_id=f"t{n}", from_address=f"person{n}@contractor.example", to_addresses=[], cc_addresses=[],
            subject=self.subjects[n], body=f"Question body {n}", received_at="2026-01-01T00:00:00Z", attachments=[], label_ids=("L1",),
        )  # fmt: skip

    def raw_message(self, message_id):
        if self.subjects[int(message_id[1:])] in self.broken:
            raise ValueError("the original could not be read")
        return b"From: a@b.example\n\nbody " + message_id.encode()

    def history_delta(self, cursor, label):
        return [], cursor


def mailbox(state="needs_label", label=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) "
            "VALUES ('mb','u1','box@example.test','h1',?,?,'x','x')",
            (label, state),
        )
    return "mb"


def state_of(mb="mb"):
    with db.connect() as conn:
        return dict(
            conn.execute(
                "SELECT label_id, connection_state, last_checked_at FROM gmail_mailboxes WHERE id=?",
                (mb,),
            ).fetchone()
        )


# ---------------------------------------------------------------- 1. activation saves first, in one short request


def test_activation_saves_the_label_and_sets_active_in_one_short_request_and_imports_nothing_inline(
    monkeypatch,
):
    on(monkeypatch)
    mailbox()
    fake = FakeClient(["a", "b", "c"])
    monkeypatch.setattr("app.api.technical_queries.GmailApiClient", lambda _t: fake)
    monkeypatch.setattr(
        "app.api.technical_queries.gmail_auth.access_token", lambda _id: "t"
    )
    monkeypatch.setattr("app.api.technical_queries.gmail_sync.start", lambda: None)
    out = api.activate_gmail_mailbox("mb", api.GmailLabelIn(label_id="L1"), OWNER)
    assert out["connection_state"] == "active" and out["import_job"]
    assert state_of() == {
        "label_id": "L1",
        "connection_state": "active",
        "last_checked_at": None,
    }  # survives a reload: it is stored
    assert fake.calls == ["labels"]  # no message was read inside the request
    with db.connect() as conn:
        assert (
            tq.list_queries("u1", True, False) == []
            and gmail_import_jobs.latest(conn, "mb")["state"] == "queued"
        )
    items = api.gmail_mailboxes(OWNER)["items"]
    assert (
        items[0]["connection_state"] == "active"
        and items[0]["import_job"]["state"] == "queued"
    )  # what the reloaded page reads


def test_a_failed_activation_says_one_plain_sentence_and_changes_nothing(monkeypatch):
    on(monkeypatch)
    mailbox()

    class Down(FakeClient):
        def labels(self):
            raise httpx.ConnectError(
                "down", request=httpx.Request("GET", "https://gmail.googleapis.com/x")
            )

    monkeypatch.setattr("app.api.technical_queries.GmailApiClient", lambda _t: Down([]))
    monkeypatch.setattr(
        "app.api.technical_queries.gmail_auth.access_token", lambda _id: "t"
    )
    with pytest.raises(HTTPException) as down:
        api.activate_gmail_mailbox("mb", api.GmailLabelIn(label_id="L1"), OWNER)
    assert down.value.status_code == 424 and "nothing was changed" in str(
        down.value.detail
    )
    monkeypatch.setattr(
        "app.api.technical_queries.GmailApiClient", lambda _t: FakeClient([])
    )
    with pytest.raises(HTTPException) as unknown:
        api.activate_gmail_mailbox("mb", api.GmailLabelIn(label_id="NOPE"), OWNER)
    assert unknown.value.status_code == 422 and "Choose a label you created" in str(
        unknown.value.detail
    )
    assert (
        state_of()["connection_state"] == "needs_label"
        and state_of()["label_id"] is None
    )


def test_the_label_list_failure_is_a_sentence_the_screen_can_show(monkeypatch):
    on(monkeypatch)
    mailbox()

    class Down(FakeClient):
        def labels(self):
            raise httpx.ConnectError(
                "down", request=httpx.Request("GET", "https://gmail.googleapis.com/x")
            )

    monkeypatch.setattr("app.api.technical_queries.GmailApiClient", lambda _t: Down([]))
    monkeypatch.setattr(
        "app.api.technical_queries.gmail_auth.access_token", lambda _id: "t"
    )
    with pytest.raises(HTTPException) as down:
        api.gmail_mailbox_labels("mb", OWNER)
    detail = down.value.detail
    assert down.value.status_code == 424 and isinstance(detail, dict)  # {code, message}; never 502/503/504: the screen reads those as "the backend is down"
    assert "Gmail could not be reached" in detail["message"]


# ---------------------------------------------------------------- 2. the import is a background job


def test_the_import_job_imports_one_message_at_a_time_names_a_failure_by_subject_and_never_stops_the_rest(
    monkeypatch,
):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    fake = FakeClient(
        ["Alpha - first", "Beta - broken one", "Gamma - third", "Delta - fourth"],
        broken={"Beta - broken one"},
    )
    gmail_import_jobs.run_job(job, client=fake)
    with db.connect() as conn:
        done = gmail_import_jobs.latest(conn, "mb")
    assert (done["state"], done["total"], done["done"], done["failed"]) == (
        "done",
        4,
        3,
        1,
    )  # "imported 3 of 4", one failed
    assert done["failures"] == [
        {
            "subject": "Beta - broken one",
            "reason": "this message could not be read, so it was skipped",
        }
    ]
    subjects = {q["subject"] for q in tq.list_queries("u1", True, False)}
    assert subjects == {
        "Alpha - first",
        "Gamma - third",
        "Delta - fourth",
    }  # the ones after the failure were imported
    assert state_of()["last_checked_at"]  # "last checked at"


def test_each_message_is_its_own_transaction_a_crash_in_the_middle_keeps_what_was_imported(
    monkeypatch,
):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")

    class Dies(FakeClient):
        def raw_message(self, message_id):
            if message_id == "m2":
                raise KeyboardInterrupt  # not an Exception: the job itself is cut off (a restart)
            return super().raw_message(message_id)

    with pytest.raises(KeyboardInterrupt):
        gmail_import_jobs.run_job(job, client=Dies(["one", "two", "three"]))
    assert {q["subject"] for q in tq.list_queries("u1", True, False)} == {
        "one",
        "two",
    }  # m0 and m1 were saved; m2 was where it stopped
    assert (
        gmail_import_jobs.recover_interrupted() == 1
    )  # the job goes back to the queue
    gmail_import_jobs.run_job(
        job, client=FakeClient(["one", "two", "three"])
    )  # run again: the two imported are duplicates, the third is new
    assert {q["subject"] for q in tq.list_queries("u1", True, False)} == {
        "one",
        "two",
        "three",
    }


def test_the_poller_leaves_a_mailbox_alone_while_its_import_runs(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    polled = []
    monkeypatch.setattr(
        gmail_sync, "poll_mailbox", lambda *a, **k: polled.append(1) or []
    )
    monkeypatch.setattr(gmail_sync.gmail_auth, "access_token", lambda _id: "t")
    gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_sync.run_once()
    assert polled == []  # a job is queued: the poller does not touch it
    with db.connect() as conn:
        conn.execute("UPDATE gmail_import_jobs SET state='done'")
    gmail_sync.run_once()
    assert polled == [1] and state_of()["last_checked_at"]


def test_nothing_is_written_into_the_code_folder_during_an_import(
    monkeypatch, tmp_path
):
    """A development server that reloads on file changes must not be triggered: raw mail and everything else go under the data folder."""
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    code = Path(app_pkg.__file__).resolve().parent
    before = {p for p in code.rglob("*") if p.is_file() and p.suffix != ".pyc"}
    gmail_import_jobs.run_job(job, client=FakeClient(["x1", "x2"]))
    after = {p for p in code.rglob("*") if p.is_file() and p.suffix != ".pyc"}
    assert after == before
    mail = settings.data_dir / "technical_query_mail"
    assert (
        mail.is_dir()
        and len(list(mail.glob("*.eml"))) == 2
        and not str(mail.resolve()).startswith(str(code))
    )


# ---------------------------------------------------------------- 4. check now


def test_check_now_queues_one_poll_that_retries_the_failed_messages_and_then_polls(
    monkeypatch,
):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs.run_job(
        job, client=FakeClient(["good one", "bad one"], broken={"bad one"})
    )
    polled = []
    monkeypatch.setattr(
        "app.gmail_worker.poll_mailbox",
        lambda client, mb, owner: polled.append(mb) or [],
    )
    out = api.check_gmail_mailbox_now("mb", OWNER)
    poll = out["import_job"]
    gmail_import_jobs.run_job(
        poll, client=FakeClient(["good one", "bad one"])
    )  # the broken one reads fine now
    with db.connect() as conn:
        assert gmail_import_jobs.latest(conn, "mb")["kind"] == "poll"
        assert (
            conn.execute("SELECT COUNT(*) c FROM gmail_import_failures").fetchone()["c"]
            == 0
        )
    assert polled == ["mb"] and {
        q["subject"] for q in tq.list_queries("u1", True, False)
    } == {"good one", "bad one"}
    with pytest.raises(HTTPException) as inactive:
        mailbox(state="needs_label")
        api.check_gmail_mailbox_now("mb", OWNER)
    assert inactive.value.status_code == 404


def test_a_retry_that_fails_again_still_names_the_message_by_its_first_subject(
    monkeypatch,
):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs.run_job(
        job, client=FakeClient(["good one", "bad one"], broken={"bad one"})
    )
    monkeypatch.setattr("app.gmail_worker.poll_mailbox", lambda *a, **k: [])

    class Down(FakeClient):
        def message(self, message_id):
            raise OSError("down")

    poll = api.check_gmail_mailbox_now("mb", OWNER)["import_job"]
    gmail_import_jobs.run_job(poll, client=Down(["good one", "bad one"]))
    with db.connect() as conn:
        latest = gmail_import_jobs.latest(conn, "mb")
    assert [f["subject"] for f in latest["failures"]] == ["bad one"]  # never "(no subject)"


# ---------------------------------------------------------------- 5. the subject is the identity


def test_the_subject_is_read_by_code_type_number_discipline_title():
    got = S.parse("Re: PRJ-CON-CO-TQ-0042 - PIPING_rev A_Hydrotest of line L-1")
    assert got == {
        "reference": "PRJ-CON-CO-TQ-42",
        "prefixed": True,
        "type": "TQ",
        "number": "42",
        "discipline": "PIPING",
        "contractor_code": "CON",  # the contractor's code in the number (lead-4, 26 Nov 2026: routing by code)
        "title": "Hydrotest of line L-1",
    }
    cfc = S.parse("FW: PRJ-CON-CO-CFC-7 - CIVIL_Conflict between two drawings")
    assert (cfc["type"], cfc["number"], cfc["discipline"], cfc["title"]) == (
        "CFC",
        "7",
        "CIVIL",
        "Conflict between two drawings",
    )
    assert (
        S.parse("PRJ-CON-CO-TQ-007 - MECH_x")["reference"]
        == S.parse("Fwd: PRJ-CON-CO-TQ-7 - MECH_y")["reference"]
    )  # zeros and Fwd are ignored
    assert (
        S.parse("Meeting minutes for Tuesday") is None
        and S.parse("") is None
        and S.parse(None) is None
    )
    assert (
        S.parse("Weekly TQ summary") is None
    )  # a type word without a number is no reference


def test_a_forward_or_reply_with_the_same_number_joins_the_same_query_and_a_different_number_does_not(
    monkeypatch,
):
    on(monkeypatch)
    envelope = lambda n, subject, sender, thread: {  # noqa: E731
        "provider": "synthetic", "mailbox_id": "m", "provider_message_id": f"id-{n}", "provider_thread_id": thread, "from_address": sender,
        "to_addresses": [], "cc_addresses": [], "subject": subject, "body": f"body {n}", "attachments": [],
    }  # fmt: skip
    first, _ = tq.import_message(
        envelope(
            1,
            "PRJ-CON-CO-TQ-12 - PIPING_a_Coating question",
            "a@contractor.example",
            "t1",
        ),
        "u1",
        True,
        False,
    )
    again, dup = tq.import_message(
        envelope(
            2,
            "FW: PRJ-CON-CO-TQ-012 - PIPING_a_Coating question",
            "someone.else@contractor.example",
            "t2",
        ),
        "u1",
        True,
        False,
    )
    other, _ = tq.import_message(
        envelope(
            3, "PRJ-CON-CO-TQ-13 - PIPING_b_Another", "a@contractor.example", "t3"
        ),
        "u1",
        True,
        False,
    )
    assert (
        again["id"] == first["id"]
        and dup is False
        and len(again["messages"]) == 2
        and other["id"] != first["id"]
    )
    assert [
        first["ref_type"],
        first["ref_number"],
        first["discipline_code"],
        first["title_short"],
        first["needs_person"],
    ] == ["TQ", "12", "PIPING", "Coating question", 0]


def test_a_subject_with_no_number_is_kept_and_flagged_for_a_person_and_the_list_filters_work(
    monkeypatch,
):
    on(monkeypatch)
    base = {
        "provider": "synthetic",
        "mailbox_id": "m",
        "to_addresses": [],
        "cc_addresses": [],
        "attachments": [],
        "body": "b",
    }
    tq.import_message(
        {
            **base,
            "provider_message_id": "1",
            "from_address": "a@x.example",
            "subject": "PRJ-CON-CO-TQ-1 - PIPING_a_One",
        },
        "u1",
        True,
        False,
    )
    tq.import_message(
        {
            **base,
            "provider_message_id": "2",
            "from_address": "b@x.example",
            "subject": "PRJ-CON-CO-CFC-2 - CIVIL_b_Two",
        },
        "u1",
        True,
        False,
    )
    tq.import_message(
        {
            **base,
            "provider_message_id": "3",
            "from_address": "c@x.example",
            "subject": "Please advise on the coating",
        },
        "u1",
        True,
        False,
    )

    def subjects(**kw):
        return sorted(q["subject"] for q in tq.list_queries("u1", True, False, **kw))

    assert len(subjects()) == 3  # nothing dropped
    assert subjects(needs_person=True) == ["Please advise on the coating"]
    assert subjects(ref_type="cfc") == ["PRJ-CON-CO-CFC-2 - CIVIL_b_Two"] and subjects(
        discipline="piping"
    ) == ["PRJ-CON-CO-TQ-1 - PIPING_a_One"]
    assert subjects(number="2") == ["PRJ-CON-CO-CFC-2 - CIVIL_b_Two"]
    rows = api.list_technical_queries(needs_person=True, scope=OWNER)["items"]
    assert (
        rows[0]["needs_person"] == 1
        and "ref_type" in rows[0]
        and "discipline_code" in rows[0]
        and "title_short" in rows[0]
    )


# ---------------------------------------------------------------- 6. a job is never lost (review L1)


def _job(job_id):
    with db.connect() as conn:
        return dict(conn.execute("SELECT * FROM gmail_import_jobs WHERE id=?", (job_id,)).fetchone())


def _down():
    return httpx.ConnectError("down", request=httpx.Request("GET", "https://gmail.googleapis.com/x"))


def test_a_server_stop_in_the_middle_of_an_import_leaves_the_job_queued_and_the_rest_is_imported_after_(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    client = FakeClient(["one", "two", "three"])
    real = client.message

    def message(message_id):
        if message_id == "m1":  # the stop arrives after the first message
            gmail_import_jobs._stop.set()
        return real(message_id)

    client.message = message
    try:
        gmail_import_jobs.run_job(job, client=client)
    finally:
        gmail_import_jobs._stop.clear()
    row = _job(job)
    assert row["state"] == "queued" and row["attempts"] == 0 and row["retry_at"] is None  # not failed, no try counted
    assert {q["subject"] for q in tq.list_queries("u1", True, False)} == {"one", "two"}  # what was imported is kept
    gmail_import_jobs.run_job(job, client=FakeClient(["one", "two", "three"]))  # the server is back: the job goes on
    assert _job(job)["state"] == "done"
    assert {q["subject"] for q in tq.list_queries("u1", True, False)} == {"one", "two", "three"}


def test_gmail_down_at_the_start_puts_the_job_back_to_the_queue_with_a_wait_then_fails_it_after_the_last_try(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")

    class Down(FakeClient):
        def list_message_ids(self, label):
            raise _down()

    gmail_import_jobs.run_job(job, client=Down([]))
    row = _job(job)
    assert row["state"] == "queued" and row["attempts"] == 1 and row["retry_at"] and "try again by itself" in row["error"]
    with db.connect() as conn:  # the job thread does not pick it before its time
        ready = conn.execute(
            "SELECT id FROM gmail_import_jobs WHERE state='queued' AND (retry_at IS NULL OR retry_at<=?)", (gmail_import_jobs._later_than(0),)
        ).fetchall()
        assert ready == []
        conn.execute("UPDATE gmail_import_jobs SET attempts=? WHERE id=?", (gmail_import_jobs.MAX_ATTEMPTS - 1, job))
    gmail_import_jobs.run_job(job, client=Down([]))
    row = _job(job)
    assert row["state"] == "failed" and row["error"] == gmail_import_jobs.GIVEN_UP_SENTENCE and row["retry_at"] is None


def test_an_outage_in_the_middle_makes_the_rest_wait_and_none_of_them_is_marked_failed(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    client = FakeClient(["one", "two", "three", "four"])
    real = client.message

    def message(message_id):
        if message_id == "m1":
            raise _down()
        return real(message_id)

    client.message = message
    gmail_import_jobs.run_job(job, client=client)
    row = _job(job)
    assert row["state"] == "queued" and row["retry_at"]
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM gmail_import_failures").fetchone()["c"] == 0  # waiting, not failed
    assert {q["subject"] for q in tq.list_queries("u1", True, False)} == {"one"}
    gmail_import_jobs.run_job(job, client=FakeClient(["one", "two", "three", "four"]))
    assert _job(job)["state"] == "done"
    assert len(tq.list_queries("u1", True, False)) == 4


def test_a_message_that_cannot_be_read_is_still_a_named_failure_not_an_outage(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs.run_job(job, client=FakeClient(["good", "bad"], broken={"bad"}))
    row = _job(job)
    assert row["state"] == "done" and row["failed"] == 1 and row["retry_at"] is None


def test_check_now_runs_a_waiting_job_at_once_and_queues_the_import_again_when_the_last_import_failed(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")

    class Down(FakeClient):
        def list_message_ids(self, label):
            raise _down()

    gmail_import_jobs.run_job(job, client=Down([]))
    assert _job(job)["retry_at"]
    same = api.check_gmail_mailbox_now("mb", OWNER)["import_job"]
    assert same == job and _job(job)["retry_at"] is None and _job(job)["state"] == "queued"  # the waiting job is ready now
    with db.connect() as conn:  # the job ended failed (every try used): Check now starts the IMPORT again, not a poll
        conn.execute("UPDATE gmail_import_jobs SET state='failed', error=? WHERE id=?", ("x", job))
    again = api.check_gmail_mailbox_now("mb", OWNER)["import_job"]
    row = _job(again)
    assert again != job and row["kind"] == "import" and row["label_id"] == "L1" and row["state"] == "queued"
    gmail_import_jobs.run_job(again, client=FakeClient(["one", "two"]))
    assert {q["subject"] for q in tq.list_queries("u1", True, False)} == {"one", "two"}  # the label mail is imported after all


def test_the_poller_queues_a_failed_import_and_retries_failed_messages_every_fifteen_minutes_on_its_own(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    with db.connect() as conn:
        conn.execute("UPDATE gmail_import_jobs SET state='failed' WHERE id=?", (job,))
    assert gmail_import_jobs.resume_due("mb") is True
    with db.connect() as conn:
        queued = conn.execute("SELECT kind FROM gmail_import_jobs WHERE state='queued'").fetchall()
    assert [r["kind"] for r in queued] == ["import"]
    # a failed message: tried again by the poller, but not more often than every 15 minutes
    with db.connect() as conn:
        conn.execute("DELETE FROM gmail_import_jobs")
        conn.execute("DELETE FROM gmail_import_failures")
    first = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs.run_job(first, client=FakeClient(["good", "bad"], broken={"bad"}))
    assert gmail_import_jobs.resume_due("mb") is False  # the job ended a moment ago
    with db.connect() as conn:
        conn.execute("UPDATE gmail_import_jobs SET updated_at='2000-01-01T00:00:00Z'")
    assert gmail_import_jobs.resume_due("mb") is True
    with db.connect() as conn:
        assert [r["kind"] for r in conn.execute("SELECT kind FROM gmail_import_jobs WHERE state='queued'")] == ["poll"]


# ---------------------------------------------------------------- 7. one reference, one mailbox, with its prefix (review L2)


def _msg(mailbox_id, subject, sender, n):
    return {
        "provider": "gmail", "mailbox_id": mailbox_id, "provider_message_id": f"{mailbox_id}-{n}", "provider_thread_id": f"t-{mailbox_id}-{n}",
        "from_address": sender, "subject": subject, "body": "body", "to_addresses": [], "cc_addresses": [],
    }  # fmt: skip


def test_a_bare_number_never_joins_and_is_flagged_for_a_person(monkeypatch):
    on(monkeypatch)
    one, _ = tq.import_message(_msg("mb", "TQ-12 - PIPING_Gasket type", "a@one.example", 1), "u1", True, True)
    two, dup = tq.import_message(_msg("mb", "Re: TQ-12 - PIPING_Other thing", "b@two.example", 2), "u1", True, True)
    assert dup is False and one["id"] != two["id"]  # two senders' "TQ-12" are two queries
    rows = {q["id"]: q for q in tq.list_queries("u1", True, False)}
    assert rows[one["id"]]["needs_person"] and rows[two["id"]]["needs_person"]
    assert rows[one["id"]]["ref_type"] == "TQ" and rows[one["id"]]["ref_number"] == "12"  # still shown as TQ-12


def test_a_full_reference_joins_only_inside_the_same_mailbox(monkeypatch):
    on(monkeypatch)
    full = "PRJ-CON-CO-TQ-0012 - PIPING_Rev A_Gasket type"
    first, _ = tq.import_message(_msg("mb1", full, "a@one.example", 1), "u1", True, True)
    reply, _ = tq.import_message(_msg("mb1", "Re: " + full, "other@two.example", 2), "u1", True, True)
    assert reply["id"] == first["id"]  # same mailbox, same full reference: one query, whoever sends it
    other_box, _ = tq.import_message(_msg("mb2", full, "a@one.example", 3), "u1", True, True)
    assert other_box["id"] != first["id"]  # another mailbox: its own query, not a refusal and not a join
    rows = {q["id"]: q for q in tq.list_queries("u1", True, False)}
    assert not rows[first["id"]]["needs_person"] and not rows[other_box["id"]]["needs_person"]


# ---------------------------------------------------------------- 8. a fault that never clears is not retried for ever (follow-up P1, P2)


def _box_state(mb="mb"):
    with db.connect() as conn:
        return dict(conn.execute("SELECT connection_state, status_note, label_id FROM gmail_mailboxes WHERE id=?", (mb,)).fetchone())


def test_a_job_whose_mailbox_row_is_gone_is_failed_with_a_reason_and_is_not_picked_again(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    with db.connect() as conn:
        conn.execute("DELETE FROM gmail_mailboxes WHERE id='mb'")
    gmail_import_jobs.run_job(job, client=FakeClient([]))
    row = _job(job)
    assert row["state"] == "failed" and row["error"] == gmail_import_jobs.GONE_SENTENCE
    with db.connect() as conn:  # the thread has nothing left to pick
        assert conn.execute("SELECT COUNT(*) c FROM gmail_import_jobs WHERE state='queued'").fetchone()["c"] == 0


def test_an_owner_who_lost_the_administrator_role_marks_the_mailbox_in_error_and_nothing_is_retried(monkeypatch):
    from app import access
    from app.config import settings

    on(monkeypatch)
    mailbox(state="active", label="L1")
    monkeypatch.setattr(settings, "auth_mode", "demo_required")
    monkeypatch.setattr(access, "upload_admin_role", lambda user_id: (None, False))
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    gmail_import_jobs.run_job(job, client=FakeClient(["one"]))
    assert _job(job)["state"] == "failed" and _job(job)["error"] == gmail_import_jobs.ADMIN_SENTENCE
    box = _box_state()
    assert box["connection_state"] == "error" and box["status_note"] == gmail_import_jobs.ADMIN_SENTENCE
    polled = []
    monkeypatch.setattr("app.gmail_sync.poll_mailbox", lambda *a, **k: polled.append(1) or [])
    from app import gmail_sync

    assert gmail_sync.run_once() == 0 and polled == []  # the poller leaves a mailbox in error alone
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM gmail_import_jobs WHERE state='queued'").fetchone()["c"] == 0
    assert tq.list_queries("u1", True, False) == []


def test_a_refused_token_marks_the_mailbox_revoked_with_one_sentence(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")

    class Refused(FakeClient):
        def list_message_ids(self, label):
            request = httpx.Request("GET", "https://gmail.googleapis.com/x")
            raise httpx.HTTPStatusError("no", request=request, response=httpx.Response(401, request=request))

    gmail_import_jobs.run_job(job, client=Refused([]))
    assert _job(job)["state"] == "failed"
    box = _box_state()
    assert box["connection_state"] == "revoked" and box["status_note"] == gmail_import_jobs.REVOKED_SENTENCE


def test_the_last_try_marks_the_mailbox_in_error_and_check_now_starts_it_again(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")

    class Down(FakeClient):
        def list_message_ids(self, label):
            raise _down()

    with db.connect() as conn:
        conn.execute("UPDATE gmail_import_jobs SET attempts=? WHERE id=?", (gmail_import_jobs.MAX_ATTEMPTS - 1, job))
    gmail_import_jobs.run_job(job, client=Down([]))
    assert _job(job)["state"] == "failed"
    box = _box_state()
    assert box["connection_state"] == "error" and box["status_note"] == gmail_import_jobs.GIVEN_UP_SENTENCE
    again = api.check_gmail_mailbox_now("mb", OWNER)["import_job"]  # a person asks: the mailbox is active again and the import is queued again
    assert _box_state()["connection_state"] == "active" and _box_state()["status_note"] is None
    assert _job(again)["kind"] == "import" and _job(again)["state"] == "queued"


def test_the_poller_stops_queueing_after_three_failed_jobs_and_marks_the_mailbox(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    for _ in range(gmail_import_jobs.MAX_AUTO_REQUEUES):
        job = gmail_import_jobs.enqueue("mb", "import", "L1")
        with db.connect() as conn:
            conn.execute("UPDATE gmail_import_jobs SET state='failed' WHERE id=?", (job,))
    assert gmail_import_jobs.resume_due("mb") is False
    box = _box_state()
    assert box["connection_state"] == "error" and box["status_note"] == gmail_import_jobs.GIVEN_UP_SENTENCE
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM gmail_import_jobs WHERE state='queued'").fetchone()["c"] == 0
    # one failed job is still retried by the poller, as before
    mailbox(state="active", label="L1")
    with db.connect() as conn:
        conn.execute("DELETE FROM gmail_import_jobs")
    job = gmail_import_jobs.enqueue("mb", "import", "L1")
    with db.connect() as conn:
        conn.execute("UPDATE gmail_import_jobs SET state='failed' WHERE id=?", (job,))
    assert gmail_import_jobs.resume_due("mb") is True


def test_a_queued_job_of_a_stopped_mailbox_is_failed_with_the_sentence(monkeypatch):
    on(monkeypatch)
    mailbox(state="active", label="L1")
    job = gmail_import_jobs.enqueue("mb", "poll")
    gmail_import_jobs.stop_mailbox("mb", "error", gmail_import_jobs.GIVEN_UP_SENTENCE)
    assert _job(job)["state"] == "failed" and _job(job)["error"] == gmail_import_jobs.GIVEN_UP_SENTENCE
    gmail_import_jobs.run_job(job, client=FakeClient([]))  # even if it is run by hand, nothing is read from Gmail
    assert _job(job)["state"] == "failed"


def test_connecting_a_revoked_mailbox_again_reuses_its_row_and_asks_for_the_label_again(monkeypatch):
    from app import gmail_auth

    on(monkeypatch)
    monkeypatch.setenv("GMAIL_CLIENT_ID", "invented-client")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "invented-secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "http://127.0.0.1:5173/technicalQueries/gmail-return")
    mailbox(state="revoked", label="L1")
    with db.connect() as conn:
        conn.execute("UPDATE gmail_mailboxes SET email='box@example.test', status_note='x' WHERE id='mb'")
    state = gmail_auth.start("u1").split("state=")[1].split("&")[0]
    saved = []

    class Store:
        def save_refresh_token(self, mailbox_id, token):
            saved.append(mailbox_id)

        def delete_refresh_token(self, mailbox_id):
            pass

    got = gmail_auth.complete(
        "code", state, exchange=lambda body: {"refresh_token": "r", "access_token": "a"},
        profile=lambda token: {"emailAddress": "Box@Example.test", "historyId": "77"}, store=Store(),
    )  # fmt: skip
    assert got["mailbox_id"] == "mb" and saved == ["mb"] and got["connection_state"] == "needs_label"
    box = _box_state()
    assert box["connection_state"] == "needs_label" and box["label_id"] is None and box["status_note"] is None
