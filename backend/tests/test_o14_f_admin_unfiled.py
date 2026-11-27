# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""Administration's "visible to nobody" (F, 27 Nov 2026): all 55 such warnings on live were technical-query attachments nobody had filed,
kept out of the library ON PURPOSE (seen on their own query, filed from there), which hid the real count of orphans (0). Such a document
is now marked apart; a real orphan keeps the warning. Invented documents only."""

from __future__ import annotations

from app import db
from tests.test_admin import (  # noqa: F401 - fixtures used by name
    auth_headers,
    call,
    client,
    make_document,
    temp_storage,
    world,
)


def _attachment(document_id: str, filed: bool) -> None:
    conn = db.connect()
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS query_attachments (id TEXT PRIMARY KEY, document_id TEXT, filed_at TEXT, filed_by TEXT)")
        conn.execute(
            "INSERT INTO query_attachments (id, document_id, filed_at) VALUES (?, ?, ?)",
            (f"qa-{document_id}", document_id, "2026-11-27T00:00:00Z" if filed else None),
        )


def test_an_unfiled_query_attachment_is_marked_apart_and_a_real_orphan_keeps_the_warning(client, world):
    make_document("doc_inv_attached", "invented-attachment.pdf")
    make_document("doc_inv_filed", "invented-filed.pdf")
    make_document("doc_inv_orphan", "invented-orphan.pdf")
    _attachment("doc_inv_attached", filed=False)
    _attachment("doc_inv_filed", filed=True)  # filed into the library but granted to nobody yet: a real orphan
    r = call(client, "GET", "/api/admin/grants", None, auth_headers(world["admin"]))
    assert r.status_code == 200
    warning = {d["document_id"]: d["warning"] for d in r.json()["documents"]}
    assert warning["doc_inv_attached"] == "query_attachment_unfiled"
    assert warning["doc_inv_filed"] == "no_discipline_can_see_this"
    assert warning["doc_inv_orphan"] == "no_discipline_can_see_this"
    assert warning[world["document"]] is None  # granted: no warning, as before
