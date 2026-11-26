"""Signature pictures counted as attachments (lead-4, 26 Nov 2026: "N of M attachments read" counted 193 signature pictures). The rule
that marks a picture INSIDE a mail's body existed, but its backfill over stored mails ran only inside an import, so a server where no
import had run since kept counting them. Now the import thread marks them once at every server start, for every mailbox and for mails
stored with none, before it does anything else. Invented mails only."""

from __future__ import annotations

from app import db, gmail_import_jobs
from app.config import settings
from app.technical_queries import import_message

from .test_g_tq_email_question import _stored_mail
from .test_technical_queries import (
    temp_storage,  # noqa: F401 - the fixture is used by name
)


def _import(mailbox_id, ref):
    import_message(
        {
            "provider": "gmail", "mailbox_id": mailbox_id, "provider_message_id": f"m-{mailbox_id}", "from_address": "a@invented.example",
            "to_addresses": [], "cc_addresses": [], "subject": f"TQ-{mailbox_id} invented", "body": "Please confirm?", "raw_storage_ref": ref,
            "attachments": [{"filename": "logo1.gif", "media_type": "image/gif", "size_bytes": 15},
                            {"filename": "site-photo.gif", "media_type": "image/gif", "size_bytes": 12}],
        },
        "u1", False, True,
    )  # fmt: skip


def _marked() -> dict:
    with db.connect() as conn:
        return {
            (r[0], r[1]): r[2]
            for r in conn.execute(
                "SELECT m.subject, a.filename, a.inline_picture FROM query_attachments a JOIN query_messages m ON m.id = a.message_id"
            )
        }


def test_at_start_every_mailbox_and_mails_with_none_get_their_body_pictures_marked():
    folder = settings.data_dir / "technical_query_mail"
    folder.mkdir()
    _stored_mail(folder / "a.eml")
    _stored_mail(folder / "b.eml")
    _import("mb", str(folder / "a.eml"))
    _import(None, str(folder / "b.eml"))
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes (id, owner_user_id, email, last_history_id, connection_state, connected_at, updated_at)"
            " VALUES ('mb', 'u1', 'box@invented.example', '1', 'needs_label', 'x', 'x')"
        )
    assert gmail_import_jobs.mark_inline_pictures_everywhere() == 2
    got = _marked()
    assert got[("TQ-mb invented", "logo1.gif")] == 1 and got[("TQ-None invented", "logo1.gif")] == 1
    assert got[("TQ-mb invented", "site-photo.gif")] == 0  # a picture sent as an attachment stays an attachment
    assert gmail_import_jobs.mark_inline_pictures_everywhere() == 0  # idempotent


def test_the_import_thread_marks_them_first_and_a_fault_never_stops_it(monkeypatch):
    calls = []
    monkeypatch.setattr(gmail_import_jobs, "mark_inline_pictures_everywhere", lambda: calls.append("mark") or 3)
    monkeypatch.setattr(gmail_import_jobs, "_loop", lambda: calls.append("loop"))
    gmail_import_jobs._run()
    assert calls == ["mark", "loop"]

    def broken(_box):
        raise OSError("invented")

    monkeypatch.undo()
    monkeypatch.setattr(gmail_import_jobs, "mark_stored_inline_pictures", broken)
    assert gmail_import_jobs.mark_inline_pictures_everywhere() == 0
