"""Technical queries by COUNTS ONLY (lead-4 and the planner, 26 Nov 2026: the planner may read the queries by counts and shape only).

Per mailbox (by its id, never its address): messages stored, ours apart; queries, TQ / CFC / needs a person; attachments read, not read
by reason, signature pictures apart; queries with evidence prepared. Every number names its boundary (this mailbox's stored rows). No
subject, name, address, file name or body text is read out. Reads only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

#: Why an attachment was not read, by its kind (the page's own words say the same in full).
PICTURE = "picture"
MACRO = "macro file"
WORD = "Word"
OLD_WORD = "older Word format"
PDF = "PDF"
OTHER = "other kind"
_MACRO_EXT = {"xlsm", "xltm", "docm", "dotm", "pptm", "potm", "ppsm", "xlam", "ppam"}
_PICTURE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp", "heic"}


def _kind(filename: str, media_type: str | None) -> str:
    name = (filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in _MACRO_EXT or "macroenabled" in (media_type or "").lower():
        return MACRO
    if (media_type or "").lower().startswith("image/") or ext in _PICTURE_EXT:
        return PICTURE
    if ext == "docx":
        return WORD
    if ext in {"doc", "dotx", "rtf", "odt"}:
        return OLD_WORD
    return PDF if ext == "pdf" else OTHER


def _table(conn, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def counts(conn) -> dict[str, Any]:
    """{"mailboxes": [{per mailbox counts}], "boundary": ...}: counts only."""
    if not _table(conn, "query_messages"):
        return {"mailboxes": [], "boundary": "no technical query is stored"}
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(query_attachments)")}
    inline = "a.inline_picture" if "inline_picture" in columns else "0"
    out = []
    boxes = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT COALESCE(mailbox_id,'') FROM query_messages ORDER BY 1"
        )
    ]
    for box in boxes:
        m = conn.execute(
            "SELECT COUNT(*), SUM(is_inbound=0), COUNT(DISTINCT query_id) FROM query_messages WHERE COALESCE(mailbox_id,'')=?",
            (box,),
        ).fetchone()
        q = conn.execute(
            "SELECT SUM(ref_type='TQ'), SUM(ref_type='CFC'), SUM(needs_person=1) FROM technical_queries WHERE id IN "
            "(SELECT query_id FROM query_messages WHERE COALESCE(mailbox_id,'')=?)",
            (box,),
        ).fetchone()
        prepared = conn.execute(
            "SELECT COUNT(DISTINCT e.query_id) FROM query_evidence e WHERE e.query_id IN "
            "(SELECT query_id FROM query_messages WHERE COALESCE(mailbox_id,'')=?)",
            (box,),
        ).fetchone()[0] if _table(conn, "query_evidence") else 0  # fmt: skip
        read, not_read, pictures = 0, Counter(), 0
        for a in conn.execute(
            f"SELECT a.filename, a.media_type, a.scan_status, {inline} AS inline_picture, d.status AS document_status "
            "FROM query_attachments a JOIN query_messages m ON m.id=a.message_id LEFT JOIN documents d ON d.id=a.document_id "
            "WHERE COALESCE(m.mailbox_id,'')=?",
            (box,),
        ):
            if a["inline_picture"]:
                pictures += 1
            elif a["document_status"] == "ready":
                read += 1
            elif a["scan_status"] == "static_check_flagged":
                not_read["active content found"] += 1
            else:
                not_read[_kind(a["filename"], a["media_type"])] += 1
        out.append({
            "mailbox": box or "(by hand)", "messages": m[0] or 0, "messages_sent_by_us": m[1] or 0, "queries": m[2] or 0,
            "tq": q[0] or 0, "cfc": q[1] or 0, "needs_a_person": q[2] or 0, "queries_with_evidence_prepared": prepared,
            "attachments_read": read, "attachments_not_read": dict(sorted(not_read.items())), "signature_pictures": pictures,
        })  # fmt: skip
    return {
        "mailboxes": out,
        "boundary": "the rows this app stores per mailbox (by mailbox id); counts only, no text",
    }
