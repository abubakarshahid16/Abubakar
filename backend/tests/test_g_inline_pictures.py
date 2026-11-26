"""A picture shown inside the mail body (a signature logo, referenced by "cid:") is counted apart, never an attachment to read and never
uploaded (planner, 26 Nov 2026: 193 pictures of the first import were listed as unread attachments). Invented message parts only."""

from __future__ import annotations

from app import db
from app.gmail_client import inline_picture, normalize_message
from app.technical_queries import get, import_message

from .test_technical_queries import envelope, temp_storage  # noqa: F401 - the fixture is used by name


def part(filename, mime, headers):
    return {"filename": filename, "mimeType": mime, "headers": [{"name": k, "value": v} for k, v in headers.items()],
            "body": {"size": 10, "attachmentId": "a-" + filename}}  # fmt: skip


def test_an_image_with_a_content_id_and_no_attachment_disposition_is_an_inline_picture():
    assert (
        inline_picture(
            part(
                "logo.png",
                "image/png",
                {"Content-ID": "<logo@x>", "Content-Disposition": "inline"},
            )
        )
        is True
    )
    assert (
        inline_picture(part("logo.png", "image/png", {"Content-ID": "<logo@x>"}))
        is True
    )
    assert (
        inline_picture(
            part(
                "site.jpg",
                "image/jpeg",
                {
                    "Content-ID": "<p@x>",
                    "Content-Disposition": "attachment; filename=site.jpg",
                },
            )
        )
        is False
    )
    assert (
        inline_picture(part("photo.jpg", "image/jpeg", {})) is False
    )  # a picture sent as an attachment is an attachment
    assert (
        inline_picture(part("form.pdf", "application/pdf", {"Content-ID": "<f@x>"}))
        is False
    )


def test_the_mail_reader_marks_them_and_the_query_stores_the_mark():
    payload = {"id": "m1", "threadId": "t1", "payload": {"headers": [{"name": "Subject", "value": "Invented"}], "parts": [
        part("logo.png", "image/png", {"Content-ID": "<logo@x>"}), part("query.pdf", "application/pdf", {})]}}  # fmt: skip
    message = normalize_message(payload)
    marks = {a["filename"]: a["inline_picture"] for a in message.attachments}
    assert marks == {"logo.png": True, "query.pdf": False}
    data = envelope("inline-1")
    data["attachments"] = [{**a, "size_bytes": 10} for a in message.attachments]
    item, _ = import_message(data, "u1", False, False)
    stored = {
        a["filename"]: a["inline_picture"]
        for a in get(item["id"], "u1", False, False)["messages"][0]["attachments"]
    }
    assert stored == {"logo.png": 1, "query.pdf": 0}
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM query_attachments WHERE inline_picture=1"
            ).fetchone()[0]
            == 1
        )
