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


def test_the_job_counts_skipped_messages_by_reason_and_says_imported_apart(monkeypatch):
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
    imported = []
    monkeypatch.setattr(
        gmail_worker, "_process_message", lambda client, mid, **kw: imported.append(mid)
    )
    job_id = gmail_import_jobs.enqueue("mb", "import", "L1")
    monkeypatch.setattr(gmail_import_jobs, "_checked", lambda mailbox_id: None)
    gmail_import_jobs._import(
        job_id,
        client,
        {"id": "mb", "email": "box@example.test", "owner_user_id": "u1"},
        "L1",
        None,
    )
    assert imported == ["m1", "m4"]  # own mail is never handed to the importer
    with db.connect() as conn:
        job = gmail_import_jobs.latest(conn, "mb")
    assert job["total"] == 4 and job["done"] == 4 and job["failed"] == 0
    assert job["imported"] == 2 and job["skipped"] == {gmail_worker.OWN_MAIL: 2}
    with db.connect() as conn:
        assert json.loads(
            conn.execute(
                "SELECT skipped_json FROM gmail_import_jobs WHERE id=?", (job_id,)
            ).fetchone()[0]
        ) == {gmail_worker.OWN_MAIL: 2}
