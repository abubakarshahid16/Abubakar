"""Technical queries by counts only, per mailbox id: no subject, name, address, file name or body text (planner, 26 Nov 2026). Invented
mail only."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app import db
from app.access import AccessScope
from app.api.technical_queries import technical_query_status_counts
from app.technical_queries import import_message

from .test_technical_queries import envelope, temp_storage  # noqa: F401 - the fixture is used by name

SECRET_WORDS = (
    "Invented Secret Subject",
    "secret-sender@vendor.example",
    "Invented secret body",
    "secret-file",
)


def _mail(mid, subject, sender, attachments):
    data = envelope(mid)
    data.update(subject=subject, from_address=sender, body="Invented secret body.", provider_thread_id=mid, mailbox_id="mb-1",
                attachments=attachments)  # fmt: skip
    return import_message(data, "u1", False, False)[0]


def test_the_counts_say_numbers_by_kind_and_no_text():
    _mail("m1", "Invented Secret Subject PRJ-ABC-OWN-TQ-1 - PRO_x", "secret-sender@vendor.example", [
        {"filename": "secret-file.pdf", "media_type": "application/pdf", "size_bytes": 1},
        {"filename": "secret-file-logo.png", "media_type": "image/png", "size_bytes": 1, "inline_picture": True},
        {"filename": "secret-file.docx", "media_type": "application/vnd.openxmlformats", "size_bytes": 1},
        {"filename": "secret-file.xlsm", "media_type": "application/vnd.ms-excel.sheet.macroEnabled.12", "size_bytes": 1}])  # fmt: skip
    _mail(
        "m2",
        "Invented Secret Subject with no number",
        "secret-sender@vendor.example",
        [],
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET ref_type='CFC' WHERE ref_type IS NULL AND needs_person=0"
        )
    got = technical_query_status_counts(
        AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    )
    box = got["mailboxes"][0]
    assert box["mailbox"] == "mb-1" and box["messages"] == 2 and box["queries"] == 2
    assert (box["tq"], box["needs_a_person"]) == (1, 1)
    assert box["signature_pictures"] == 1 and box["attachments_read"] == 0
    assert box["attachments_not_read"] == {"PDF": 1, "Word": 1, "macro file": 1}
    said = json.dumps(got)
    assert not any(w.lower() in said.lower() for w in SECRET_WORDS)  # counts only


def test_only_an_administrator_may_read_them():
    with pytest.raises(HTTPException) as refused:
        technical_query_status_counts(AccessScope("u1", frozenset()))
    assert refused.value.status_code == 403
