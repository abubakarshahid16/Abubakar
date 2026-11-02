"""What "ready" means: every page and picture read, or listed as not read
(ONE_CHECKED_DEFINITION_ENABLED, off by default; plan change 6, one meaning).

ONE FUNCTION DECIDES, `assess`, for every kind of file, from the page ledger and the
file's own picture inventory. Vectors alone never made a document fully read.

  read        a text or picture reading came back, and search can see the page.
  listed      not read, with its place and reason, and the reason is final: a blank
              page, a failed recognition, an image the engine cannot open, a page
              excluded on purpose. Accounted for, and a gap: never "fully read".
  unaccounted nobody can say yet: no ledger row, recognition still pending, a picture
              with no answer from any reader, a file that could not be opened.

  ready             vectors complete and nothing unaccounted. It may still have listed
                    gaps, and its line says how many.
  partially_searchable, held   vectors complete, something unaccounted: `line` says what.
                    Search and the READY hooks work as they do today; only what asks
                    for a fully read document refuses. Re-reading the file releases it.

HEADERS AND FOOTERS. Pictures there are one listed line of their own, outside the
pictures denominator: one header picture repeats on every page, so a count per part is
not a number of pictures seen. They are still in the listed count, because nobody read
them and a stamp can sit there.

A FILE ERROR (OCR_FILE_ERROR_HOLD_ENABLED, #1568). A page recognition failed on because
the stored file could not be opened is unaccounted, not listed: the failure says nothing of
the page, and the cause can be fixed. With that switch alone, only a document with such a
page gets a decision; every other document is as with both off.

This module never widens what anyone may read (rule 5): it says what was read of a
document a caller already reads. Counts and places only, never page text.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import UTC, datetime

from pydantic import BaseModel

from . import errors, states, stored_paths
from .config import settings
from .db import connect
from .page_not_read import FILE_NOT_READ, file_error_row, is_file_error

log = logging.getLogger(__name__)

STATE_READ, STATE_LISTED, STATE_UNACCOUNTED = "read", "listed", "unaccounted"
UNIT_PAGE, UNIT_PART, UNIT_PICTURE = "page", "part", "picture"
WHY_NO_LEDGER_ROW = "no page ledger row"
WHY_NO_PAGES = "no page count and no page ledger row"
WHY_NOT_EXTRACTED = "not extracted"
WHY_RECOGNITION_PENDING = "recognition has not finished"
WHY_NOT_CHUNKED = "not chunked"
WHY_NOT_SEARCHABLE = "read, but search cannot see this page"
WHY_NO_ANSWER = "no reader has answered for this picture"
WHY_NO_INVENTORY = "the file could not be opened to count its pictures"
WHY_WORD_NOT_COUNTED = "a Word file's pictures are not read until WORD_PAGE_MARKERS_ENABLED is on and the file is re-read"
WHY_FURNITURE = "in a header or footer: kept beside the body and not sent to a reader"
WHY_PDF_NOT_RECOGNISED = (
    "on a page with a usable text layer, which was not sent to recognition"
)
WHY_SHEET = "in a workbook, which is read as cells"
#: Stored and shown at most this many of each list; the counts stay whole.
#: The way forward for a Word file held because a picture has no reader's answer.
WAY_FORWARD_REREAD = (
    "Reprocess the file so the local recogniser reads its pictures; until then, "
    "answers can use its text only"
)
_WHY_NEEDS_REREAD = frozenset({WHY_NO_ANSWER, WHY_WORD_NOT_COUNTED})
MAX_LISTED = 40
NOTE = "What was read of this document"
STILL_PROCESSING = (
    "A selected document is still processing or has no searchable content. "
    "Wait for every document to show Ready, then ask again."
)


class DocumentReading(BaseModel):
    """What `/api/document-reading` says of one document. A count not made is null, never 0."""

    pages_total: int | None
    pages_read: int | None
    page_unit: str
    page_source: str | None
    word_saved_pages: int | None
    pictures_total: int | None
    pictures_read: int | None
    picture_unit: str
    furniture_pictures: int
    not_read_listed: int
    body_gaps: int
    unaccounted: int
    ready: bool
    fully_read: bool
    line: str
    not_read: list[dict]
    unaccounted_list: list[dict]


class DocumentReadings(BaseModel):
    documents: dict[str, DocumentReading]


def _page_state(row: dict) -> tuple[str, str | None]:
    """One ledger row: read, listed with its reason, or unaccounted with why."""
    from .page_not_read import unread_page_words

    if row["native_status"] == "not_extracted":
        return STATE_UNACCOUNTED, WHY_NOT_EXTRACTED
    if row["ocr_status"] == "pending":
        return STATE_UNACCOUNTED, WHY_RECOGNITION_PENDING
    if file_error_row(row):
        return STATE_UNACCOUNTED, FILE_NOT_READ
    if row["index_status"] == "not_chunked":
        return STATE_UNACCOUNTED, WHY_NOT_CHUNKED
    # A recognition that came back with no box read nothing.
    recognised = row["ocr_status"] == "done" and row["ocr_mean_conf"] is not None
    if row["native_status"] == "text" or recognised:
        if row["index_status"] == "retrievable":
            return STATE_READ, None
        if str(row["index_reason"] or "").startswith("page_classified_"):
            return STATE_LISTED, unread_page_words(row)
        return STATE_LISTED, WHY_NOT_SEARCHABLE
    return STATE_LISTED, unread_page_words(row)


def _walk_pages(
    numbers: list[int], rows: list[dict]
) -> tuple[int, list[dict], list[dict]]:
    """(pages read, listed, unaccounted). No page known at all says nothing was read."""
    by_page = {r["page_no"]: r for r in rows}
    listed: list[dict] = []
    unaccounted: list[dict] = []
    read = 0
    for number in numbers:
        row = by_page.get(number)
        state, why = (
            (STATE_UNACCOUNTED, WHY_NO_LEDGER_ROW) if row is None else _page_state(row)
        )
        read += state == STATE_READ
        item = {"kind": "page", "page": number, "no": None, "reason": why}
        if state == STATE_LISTED:
            listed.append(item)
        elif state == STATE_UNACCOUNTED:
            unaccounted.append(item)
    if not numbers:
        unaccounted.append(
            {"kind": "page", "page": None, "no": None, "reason": WHY_NO_PAGES}
        )
    return read, listed, unaccounted


def _walk_pictures(
    pictures: list[dict] | None,
    furniture: int,
    listed: list[dict],
    unaccounted: list[dict],
) -> int:
    """Pictures read; the rest go on the two lists. Not counted at all is unaccounted."""
    done = 0
    for picture in pictures or []:
        count = picture.get("count", 1)
        item = {
            "kind": "picture",
            "page": picture.get("page"),
            "no": picture.get("no"),
            "count": count,
            "reason": picture.get("reason"),
        }
        if picture["state"] == STATE_READ:
            done += count
        elif picture["state"] == STATE_LISTED:
            listed.append(item)
        else:
            unaccounted.append(item)
    if pictures is None:
        unaccounted.append(
            {
                "kind": "picture",
                "page": None,
                "no": None,
                "count": None,
                "reason": WHY_NO_INVENTORY,
            }
        )
    if furniture:
        listed.append(
            {
                "kind": "picture",
                "page": None,
                "no": None,
                "count": furniture,
                "reason": WHY_FURNITURE,
            }
        )
    return done


def assess(
    page_count: int | None,
    rows: list[dict],
    pictures: list[dict] | None,
    furniture_pictures: int,
    vectors_complete: bool,
    *,
    picture_unit: str = "picture",
    page_unit: str = "page",
    page_source: str | None = None,
    word_saved_pages: int | None = None,
) -> dict:
    """THE decision. `pictures`: {"state", "page", "no", "count", "reason"}; None when
    they could not be counted at all, which is unaccounted, never zero."""
    numbers = sorted(
        set(range(1, (page_count or 0) + 1)) | {r["page_no"] for r in rows}
    )
    read, listed, unaccounted = _walk_pages(numbers, rows)
    pictures_read = _walk_pictures(pictures, furniture_pictures, listed, unaccounted)
    size = lambda items: sum(i.get("count") or 1 for i in items)  # noqa: E731
    out = {
        "pages_total": len(numbers) if numbers else None,
        "pages_read": read if numbers else None,
        "page_unit": page_unit,
        "page_source": page_source,
        "word_saved_pages": word_saved_pages,
        "picture_unit": picture_unit,
        "body_gaps": size([i for i in listed if i["reason"] != WHY_FURNITURE]),
        "pictures_total": None
        if pictures is None
        else sum(p.get("count", 1) for p in pictures),
        "pictures_read": None if pictures is None else pictures_read,
        "furniture_pictures": furniture_pictures,
        "not_read_listed": size(listed),
        "unaccounted": size(unaccounted),
        "not_read": listed,
        "unaccounted_list": unaccounted,
        "vectors_complete": vectors_complete,
        "ready": vectors_complete and not unaccounted,
        "fully_read": vectors_complete and not unaccounted and not listed,
    }
    out["line"] = _line(out)
    return out


def _places(items: list[dict], page_unit: str = "page") -> str:
    """A part number is not a page (a Word file with no page marks): no place is said."""
    if page_unit == UNIT_PART:
        return ""
    pages = sorted({i["page"] for i in items if i.get("page")})
    shown = ", ".join(str(p) for p in pages[:5]) + (
        " and more" if len(pages) > 5 else ""
    )
    return f" (page {shown})" if shown else ""


def _line(out: dict) -> str:
    """The count in its true unit, with its denominator. Not counted prints as not counted."""
    total = out["pages_total"]
    if total is None:
        pages = "pages not counted"
    elif out["page_unit"] == UNIT_PART:
        why = (
            "no page numbers: this Word file was read before its page marks were used"
            if out["page_source"] == "stale"
            else "no page numbers: this Word file gives none"
        )
        pages = f"Read {out['pages_read']} of {total} reading parts ({why})"
    elif out["page_source"] == "partial":
        pages = (
            f"Read {out['pages_read']} of the {total} pages its page marks reach "
            f"(Word saved {out['word_saved_pages'] if out['word_saved_pages'] is not None else 'no count'})"
        )
    else:
        pages = f"Read {out['pages_read']} of {total} pages"
    if out["pictures_total"] is None:
        pictures = "pictures not counted"
    elif out["picture_unit"] == UNIT_PAGE:
        pictures = f"{out['pictures_read']} of {out['pictures_total']} pages holding pictures recognised"
    else:
        pictures = f"{out['pictures_read']} of {out['pictures_total']} pictures"
    said = f"{pages}, {pictures}; {out['not_read_listed']} not read, listed"
    if out["unaccounted"]:
        why = list(dict.fromkeys(str(i["reason"]) for i in out["unaccounted_list"]))
        said += (
            f"; not ready: {out['unaccounted']} not accounted for"
            + _places(out["unaccounted_list"], out["page_unit"])
            + ": "
            + "; ".join(why[:3])
        )
        if set(why) & _WHY_NEEDS_REREAD:
            said += f". {WAY_FORWARD_REREAD}"
    return said


# ------------------------------------------------------------- the file's pictures


def _on_page(row: dict | None, page: int) -> dict:
    """A page holding pictures, in a file with no per-picture reader: the engine reads
    the page, so one box says nothing of each picture. Counted as a page, never as pictures."""
    item = {"page": page, "no": None, "count": 1, "reason": None}
    if row is None or row["ocr_status"] == "pending":
        return {**item, "state": STATE_UNACCOUNTED, "reason": WHY_RECOGNITION_PENDING}
    if file_error_row(row):
        return {**item, "state": STATE_UNACCOUNTED, "reason": FILE_NOT_READ}
    if row["ocr_status"] == "done" and row["ocr_mean_conf"] is not None:
        return {**item, "state": STATE_READ}
    reason = (
        row["ocr_reason"] if row["ocr_status"] == "failed" else WHY_PDF_NOT_RECOGNISED
    )
    return {**item, "state": STATE_LISTED, "reason": reason}


def _word_pictures(path: str, document_id: str) -> dict:
    from . import docx_pages, word_pages

    proof = word_pages.read_proof(document_id)
    if (
        proof is None
    ):  # the Word switch is off: counted from the file, and none answered for
        total, furniture = docx_pages.picture_counts(path)
        items = (
            [
                {
                    "state": STATE_UNACCOUNTED,
                    "page": None,
                    "no": None,
                    "count": total,
                    "reason": WHY_WORD_NOT_COUNTED,
                }
            ]
            if total
            else []
        )
        return {"items": items, "furniture": furniture, "page_unit": UNIT_PART}
    items = (
        [
            {
                "state": STATE_READ,
                "page": None,
                "no": None,
                "count": proof["pictures_read"],
                "reason": None,
            }
        ]
        if proof["pictures_read"]
        else []
    )
    for item in proof["not_read"]:
        if item["kind"] != "picture":
            continue
        final = item["reason"] != docx_pages.WHY_NOT_SENT
        items.append(
            {
                "state": STATE_LISTED if final else STATE_UNACCOUNTED,
                "page": item["page"],
                "no": item["no"],
                "count": 1,
                "reason": item["reason"] if final else WHY_NO_ANSWER,
            }
        )
    return {
        "items": items,
        "furniture": proof["furniture_pictures"],
        "page_unit": UNIT_PART
        if proof["page_source"] in word_pages.NO_REAL_PAGE
        else UNIT_PAGE,
        "page_source": proof["page_source"],
        "word_saved_pages": proof["word_saved_pages"],
    }


def _pdf_pictures(path: str, rows: dict[int, dict]) -> dict:
    from .pdf_guard import open_pdf

    items = []
    with open_pdf(path) as doc:
        for index in range(doc.page_count):
            if doc.load_page(index).get_images(full=False):
                items.append(_on_page(rows.get(index + 1), index + 1))
    return {"items": items, "picture_unit": UNIT_PAGE}


def _sheet_pictures(path: str) -> dict:
    with zipfile.ZipFile(path) as zf:
        total = sum(
            zf.read(name).count(b"<xdr:pic>")
            for name in zf.namelist()
            if name.startswith("xl/drawings/") and name.endswith(".xml")
        )
    return {
        "items": [
            {
                "state": STATE_LISTED,
                "page": None,
                "no": None,
                "count": total,
                "reason": WHY_SHEET,
            }
        ]
        if total
        else []
    }


def _pictures(document_id: str, stored_path: str | None, rows: list[dict]) -> dict:
    """What the file holds, per kind. `items` None: the pictures could not be counted."""
    from . import intake

    path = stored_paths.local(stored_path) if stored_path else None
    by_page = {r["page_no"]: r for r in rows}
    try:
        kind = intake.detect(path)
        if kind == intake.KIND_WORD:
            return _word_pictures(path, document_id)
        if kind == intake.KIND_SHEET:
            return _sheet_pictures(path)
        if kind == intake.KIND_IMAGE:  # one file, one picture, one page: the same thing
            return {"items": [_on_page(by_page.get(1), 1)]}
        return _pdf_pictures(path, by_page)
    except Exception as exc:  # noqa: BLE001 - logged; not counted is unaccounted, and said
        return errors.fell_back(
            "reading_state: pictures not counted", exc, {"items": None}
        )


def _any_switch() -> bool:
    return (
        settings.one_checked_definition_enabled or settings.ocr_file_error_hold_enabled
    )


def file_error_pages(document_id: str) -> list[int]:
    """Pages recognition failed on because of the file. Empty with the switch off."""
    if not settings.ocr_file_error_hold_enabled:
        return []
    rows = (
        connect()
        .execute(
            "SELECT page_no, error FROM page_ocr WHERE document_id = ? AND error IS NOT NULL",
            (document_id,),
        )
        .fetchall()
    )
    return [r["page_no"] for r in rows if is_file_error(r["error"])]


def recognised_nothing_words(document_id: str, pages: int, tried: int) -> str:
    """Why a document of only scans has nothing searchable, after recognition ran."""
    unopened = file_error_pages(document_id)
    if unopened:
        return (
            f"all {pages} pages are scanned images; recognition could not "
            f"open the stored file for {len(unopened)} of them"
        )
    return (
        f"all {pages} pages are scanned images; recognition ran on "
        f"{tried} of them and found no usable text"
    )


def _decides(document_id: str) -> bool:
    return settings.one_checked_definition_enabled or bool(
        file_error_pages(document_id)
    )


def decide(document_id: str) -> dict | None:
    """The decision for a document, from its ledger as it stands now. None when off."""
    if not _decides(document_id):
        return None
    from . import page_ledger

    conn = connect()
    doc = conn.execute(
        "SELECT page_count, stored_path, chunk_count, embedded_count FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if doc is None:
        return None
    rows = page_ledger.rows(document_id)
    file = _pictures(document_id, doc["stored_path"], rows)
    return assess(
        doc["page_count"],
        rows,
        file["items"],
        file.get("furniture", 0),
        (doc["embedded_count"] or 0) >= (doc["chunk_count"] or 0),
        picture_unit=file.get("picture_unit", UNIT_PICTURE),
        page_unit=file.get("page_unit", UNIT_PAGE),
        page_source=file.get("page_source"),
        word_saved_pages=file.get("word_saved_pages"),
    )


# ------------------------------------------------------------------- the status


def _ensure_table(conn) -> None:
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS document_reading (
                   document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                   summary     TEXT NOT NULL,
                   decided_at  TEXT NOT NULL
               )"""
        )


def _summary(decided: dict) -> dict:
    keep = (
        "pages_total",
        "pages_read",
        "page_unit",
        "page_source",
        "word_saved_pages",
        "pictures_total",
        "pictures_read",
        "picture_unit",
        "furniture_pictures",
        "not_read_listed",
        "body_gaps",
        "unaccounted",
        "ready",
        "fully_read",
        "line",
    )
    return {
        **{k: decided[k] for k in keep},
        "not_read": decided["not_read"][:MAX_LISTED],
        "unaccounted_list": decided["unaccounted_list"][:MAX_LISTED],
    }


def _forget(document_id: str) -> None:
    conn = connect()
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_reading'"
    ).fetchone():
        with conn:
            conn.execute(
                "DELETE FROM document_reading WHERE document_id = ?", (document_id,)
            )


def finish_status(document_id: str) -> str:
    """The status a document with complete vectors finishes at. Refreshes the ledger
    first, since a page missing from it decides. Off: `ready`, exactly as before."""
    ready, held = states.READY, states.PARTIALLY_SEARCHABLE
    if not _any_switch():
        return ready
    if not _decides(document_id):  # read again after its file error was put right
        _forget(document_id)
        return ready
    from . import page_ledger

    try:
        page_ledger.refresh(document_id)
    except Exception as exc:  # noqa: BLE001 - logged; the ledger then shows what is missing
        errors.fell_back("reading_state: ledger not refreshed", exc, None)
    decided = decide(document_id)
    if decided is None:
        return ready
    conn = connect()
    _ensure_table(conn)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_reading (document_id, summary, decided_at) VALUES (?,?,?)",
            (
                document_id,
                json.dumps(_summary(decided)),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
    return ready if decided["ready"] else held


def stored(document_id: str) -> dict | None:
    """What was last decided, or None: switch off, or never decided (an older document)."""
    if not _any_switch():
        return None
    conn = connect()
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_reading'"
    ).fetchone():
        return None
    row = conn.execute(
        "SELECT summary FROM document_reading WHERE document_id = ?", (document_id,)
    ).fetchone()
    return json.loads(row["summary"]) if row else None


def hooks_may_run(document_id: str, status: str) -> bool:
    """The READY hooks keep working for a held document: it is searchable, its text is
    complete, and only the word "ready" is withheld. Off: `status == ready`."""
    if status == states.READY:
        return True
    decided = stored(document_id)
    return decided is not None and not decided["ready"] and decided["unaccounted"] > 0


def readable(scope) -> dict[str, dict]:
    """What was decided, for the documents this caller may already read: an intersection
    (rule 5), and it never adds one. Empty when off or never decided."""
    if not _any_switch():
        return {}
    conn = connect()
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_reading'"
    ).fetchone():
        return {}
    rows = conn.execute(
        "SELECT document_id, summary FROM document_reading"
        " WHERE document_id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(scope.allowed_document_ids)),),
    ).fetchall()
    return {r["document_id"]: json.loads(r["summary"]) for r in rows}


def _documents_with_file_errors(conn) -> list[str]:
    rows = conn.execute(
        "SELECT document_id, error FROM page_ocr WHERE error IS NOT NULL"
    ).fetchall()
    return sorted({r["document_id"] for r in rows if is_file_error(r["error"])})


def _redecide_file_holds(conn) -> int:
    """The hold switch went off with the one-meaning switch on: what it held now reads as
    listed, so decide those documents again. One held for another reason stays held."""
    done = 0
    for document_id in _documents_with_file_errors(conn):
        held = conn.execute(
            "SELECT 1 FROM documents d JOIN document_reading r ON r.document_id = d.id"
            " WHERE d.id = ? AND d.status = ? AND d.chunk_count > 0"
            " AND d.embedded_count >= d.chunk_count AND d.indexed_at IS NOT NULL"
            " AND json_extract(r.summary, '$.unaccounted') > 0",
            (document_id, states.PARTIALLY_SEARCHABLE),
        ).fetchone()
        if held and finish_status(document_id) == states.READY:
            with conn:
                done += conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ? AND status = ?",
                    (states.READY, document_id, states.PARTIALLY_SEARCHABLE),
                ).rowcount
    return done


def release_held() -> int:
    """ROLLBACK. Only this module holds a document back from READY, so with the switch off
    (seen at server start: a switch only changes on a restart) a document it HELD goes where
    the old rule puts it, and what it stored goes too. Held means its stored decision says
    something is unaccounted and it has chunks, all with vectors: an older document with no
    decision, or one whose decision says ready, stays as it is. Nothing is re-read, and the
    hooks ran when it was held. Off with nothing ever held: one read, nothing written. A
    failure here never stops the worker starting; it is logged, with the count only.

    OCR_FILE_ERROR_HOLD_ENABLED has its own rollback. Staying on, it keeps its holds while
    the rest go. Off with the one-meaning switch on, a document it held is decided again."""
    checked = settings.one_checked_definition_enabled
    hold = settings.ocr_file_error_hold_enabled
    if checked and hold:
        return 0
    try:
        conn = connect()
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_reading'"
        ).fetchone():
            return 0
        if checked:
            done = _redecide_file_holds(conn)
            log.info("reading_state: %d held document(s) released", done)
            return done
        keep = json.dumps(_documents_with_file_errors(conn) if hold else [])
        with conn:
            done = conn.execute(
                "UPDATE documents SET status = ? WHERE status = ? AND chunk_count > 0"
                " AND embedded_count >= chunk_count AND indexed_at IS NOT NULL AND id IN ("
                "SELECT document_id FROM document_reading"
                " WHERE json_extract(summary, '$.unaccounted') > 0)"
                " AND id NOT IN (SELECT value FROM json_each(?))",
                (states.READY, states.PARTIALLY_SEARCHABLE, keep),
            ).rowcount
            conn.execute(
                "DELETE FROM document_reading"
                " WHERE document_id NOT IN (SELECT value FROM json_each(?))",
                (keep,),
            )
    except Exception as exc:  # noqa: BLE001 - logged; the release is tried at the next start
        return errors.fell_back("reading_state: held documents not released", exc, 0)
    log.info("reading_state: %d held document(s) released", done)
    return done


def not_found_words(document_id: str, reason: str) -> str:
    """ "Not found" with body gaps listed may be wrong: the section can sit in an unread
    picture. So it is said as a guess, with the count (rule 4). Off: the words as they were."""
    if not _any_switch():
        return reason
    decided = stored(document_id) or decide(document_id)
    gaps = ((decided or {}).get("body_gaps") or 0) + len(file_error_pages(document_id))
    if not gaps:
        return reason
    return (
        f"{reason} (a guess: {gaps} page{'' if gaps == 1 else 's'} or pictures of the body "
        "are listed as not read, and it may be in one of them)"
    )


def coverage_part(document_id: str) -> dict:
    """What `page_ledger.coverage` adds: the decision as it stands, in full."""
    decided = decide(document_id)
    return {} if decided is None else {"reading": decided}


def text_only_answer(document_id: str, status: str) -> str | None:
    """What a full-document answer must say about a held Word file whose text is all
    searchable and whose only gap is pictures with no answer: the answer goes ahead on
    its text, and says so. None for anything else, and with the switches off."""
    from . import datasheet_inputs, states

    if status != states.PARTIALLY_SEARCHABLE or not _any_switch():
        return None
    saved = stored(document_id)
    if not saved or not saved["unaccounted"] or not saved["unaccounted_list"]:
        return None
    if any(i.get("kind") != "picture" for i in saved["unaccounted_list"]):
        return None
    row = (
        connect()
        .execute("SELECT stored_path FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    path = row["stored_path"] if row else None
    if not path or datasheet_inputs.office_kind(path) != datasheet_inputs.KIND_DOCX:
        return None
    return saved["line"]


def not_ready_words(documents: list[dict]) -> str:
    """Why a full-document answer is refused: a held document is not still processing."""
    lines = [
        s["line"]
        for s in (stored(d["document_id"]) for d in documents)
        if s and s["unaccounted"]
    ]
    if lines:
        return f"A selected document is not fully accounted for. {lines[0]}"
    return STILL_PROCESSING


def review_notes(findings: list[dict]) -> list[dict]:
    """One line per document behind the findings: what was read, with its denominator."""
    if not _any_switch():
        return []
    notes = []
    for document_id in sorted(
        {f.get("document_id") for f in findings if f.get("document_id")}
    ):
        decided = decide(document_id)
        if decided is not None:
            notes.append(
                {
                    "note": NOTE,
                    "standard": "",
                    "count": decided["not_read_listed"],
                    "detail": decided["line"] + ".",
                }
            )
    return notes


def picture_counts(document_id: str) -> tuple[int | None, int | None] | None:
    """(pictures read, pictures in the body), one definition: a reader's answer per picture.
    None when nothing here counts per picture (a PDF counts pages holding pictures)."""
    from . import word_pages

    decided = decide(document_id)
    if decided is not None:
        if decided["picture_unit"] != UNIT_PICTURE:
            return None
        return decided["pictures_read"], decided["pictures_total"]
    proof = word_pages.read_proof(document_id)
    return (
        None if proof is None else (proof["pictures_read"], proof["pictures_in_file"])
    )


def report(document_id: str) -> dict | None:
    """Counts only, for `scripts/ready_report.py`."""
    decided = decide(document_id)
    return None if decided is None else _summary(decided)
