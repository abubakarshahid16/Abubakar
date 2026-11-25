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
    assert down.value.status_code == 503 and "nothing was changed" in str(
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
            "reason": "the message could not be imported (ValueError)",
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


# ---------------------------------------------------------------- 5. the subject is the identity


def test_the_subject_is_read_by_code_type_number_discipline_title():
    got = S.parse("Re: PRJ-CON-CO-TQ-0042 - PIPING_rev A_Hydrotest of line L-1")
    assert got == {
        "reference": "PRJ-CON-CO-TQ-42",
        "type": "TQ",
        "number": "42",
        "discipline": "PIPING",
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
