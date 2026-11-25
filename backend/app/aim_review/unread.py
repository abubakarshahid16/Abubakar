"""Which pages of the paper were NOT read, said plainly (order 14, #1905 picture pages).

A page counts as read only when text came back for it: the PDF's text layer, or a picture reading (the app's local recognition,
`ocr`, of a scan or of a page that is a picture). A page with neither is NOT read, and the review says so on the results page and
on the team file; it is never silently left out. A page whose picture reading has not run yet is only NAMED as waiting (the upload's
own recognition reads it; the review never runs recognition itself). A Word file's pictures count the same way: a picture with no
stored reading is a picture not read.

The record is ids and codes only ("page 7: no_text"), never document text. No model, no network.
"""

from __future__ import annotations

import contextlib
import logging
import re

log = logging.getLogger(__name__)

#: A page with fewer characters than this has no text for a reader to use (a bare page number is not a page read).
MIN_PAGE_CHARS = 20

NO_TEXT, WAITING, FAILED, NO_TEXT_AFTER = (
    "no_text",
    "waiting_for_picture_reading",
    "picture_reading_failed",
    "picture_reading_no_text",
)
PICTURE_NOT_READ, PICTURE_FAILED = "picture_not_read", "picture_reading_failed"

#: The plain words of each code (the same on the page and in the file).
WHY_WORDS = {
    NO_TEXT: "it has no text, or almost none (fewer than 20 characters), and no picture reading came back",
    WAITING: "its picture reading has not run yet",
    FAILED: "its picture reading failed",
    NO_TEXT_AFTER: "its picture reading came back with no text",
    PICTURE_NOT_READ: "no picture reading came back",
    PICTURE_FAILED: "its picture reading failed",
}

STEP = "aim_unread_pages"
#: The run's calls row when the check itself failed (`faults`); its own step, so `record_state` still reads "not checked".
CHECK_STEP, PICTURES_STEP = "aim_unread_check", "aim_picture_readings"
#: The record's code when every page had text or a picture reading, and when the check did not run (an older review, a failed check, a missing file).
NONE, NOT_CHECKED = "none", "not_checked"
LISTED, ALL_READ, NOT_RECORDED = "listed", "all_read", "not_recorded"


def with_unread(
    conn, paper_id: str, paper, _reload
):  # kept for the caller's signature; unused since the review stopped reading pages
    """The paper with its `unread` list filled: a PDF's pages with no usable text (waiting pages are named, not read here), or a Word
    file's pictures with no reading. `_reload` is kept for the caller's signature (unused: the review no longer reads waiting pages). Never raises."""
    try:
        ref = _ref(conn, paper_id)
        if ref is None:
            return paper
        if ref["word"]:
            paper.unread = _word_unread(conn, ref["path"])
            paper.unread_checked = (
                ref["path"] is not None
            )  # a Word file that was not found was not checked
            return paper
        # 7a: a page waiting for the upload's own picture reading is only NAMED (WAITING); the review never runs recognition itself
        paper.unread = _pdf_unread(conn, paper_id, paper, ref["pages"])
        paper.unread_checked = True
    except Exception as exc:  # noqa: BLE001 - never a failed review: the pages are not claimed, and the run says the check failed
        from . import faults

        faults.record(CHECK_STEP, "the unread-pages check", exc)
    return paper


def _ref(conn, paper_id: str) -> dict | None:
    from app import agent_review_pages
    from app.config import settings

    row = conn.execute(
        "SELECT page_count, stored_path, pagination, filename FROM documents WHERE id = ?",
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    word = (
        str(row["filename"] or "").lower().endswith((".docx", ".dotx"))
        or (row["pagination"] or "") == "flow"
    )
    path = None
    if word:
        try:
            path = agent_review_pages.pdf_path(
                {"stored_path": row["stored_path"]}, settings.data_dir
            )
        except agent_review_pages.PageImageUnavailable:
            path = None
    return {"word": word, "path": path, "pages": int(row["page_count"] or 0)}


def _pdf_unread(conn, paper_id: str, paper, total: int) -> list[dict]:
    last = max([total, *paper.pages])
    state = {
        int(r["page_no"]): (int(r["needs_ocr"] or 0), None)
        for r in conn.execute(
            "SELECT page_no, needs_ocr FROM pages WHERE document_id = ?", (paper_id,)
        )
    }
    recognised: dict[int, object] = {}
    with contextlib.suppress(
        Exception
    ):  # an old database without the table: nothing was recognised
        recognised = {
            int(r["page_no"]): r["error"]
            for r in conn.execute(
                "SELECT page_no, error FROM page_ocr WHERE document_id = ?", (paper_id,)
            )
        }
    out = []
    for n in range(1, last + 1):
        if len(str(paper.pages.get(n) or "").strip()) >= MIN_PAGE_CHARS:
            continue
        if n in recognised:
            why = FAILED if recognised[n] else NO_TEXT_AFTER
        elif state.get(n, (0, None))[0]:
            why = WAITING
        else:
            why = NO_TEXT
        out.append({"where": f"page {n}", "why": why})
    return out


def _word_unread(conn, path) -> list[dict]:
    """A Word file's pictures that have no stored reading (a picture holds no text for the document reader)."""
    if path is None:
        return []
    from app import docx_reader
    from app.docx_pages import PICTURE_IMAGE

    pictures = [
        p
        for p in docx_reader.read_structure(path, picture_readings={}).pictures
        if p.kind == PICTURE_IMAGE
    ]
    if not pictures:
        return []
    from app import word_pictures
    from app.config import settings

    sha = word_pictures._sha256(path)
    status = {}
    if (
        settings.word_page_markers_enabled
    ):  # readings reach the text only while the switch merges them at upload
        try:
            status = {
                int(r["picture_no"]): r["status"]
                for r in conn.execute(
                    "SELECT picture_no, status FROM word_picture_readings WHERE file_sha256 = ?",
                    (sha,),
                )
            }
        except Exception as exc:  # noqa: BLE001 - no reading: every picture is named as not read
            if "no such table" in str(
                exc
            ):  # an older database: no picture was ever read
                log.debug(
                    "general review: no stored picture readings (%s)",
                    type(exc).__name__,
                )
            else:  # a store that holds readings but cannot be read: the run says so
                from . import faults

                faults.record(PICTURES_STEP, "reading the stored picture readings", exc)
            status = {}
    out = []
    for p in pictures:
        got = status.get(p.no)
        if got == word_pictures.STATUS_READ:
            continue
        out.append(
            {
                "where": f"picture {p.no}",
                "why": PICTURE_FAILED
                if got == word_pictures.STATUS_FAILED
                else PICTURE_NOT_READ,
            }
        )
    return out


# ------------------------------------------------------------------ the record and its words


def note(items: list[dict]) -> str:
    """The run record's code note: "page 7: no_text; page 9: waiting_for_picture_reading" (codes only)."""
    return "; ".join(f"{i['where']}: {i['why']}" for i in items)


_ITEM = re.compile(r"^(?P<where>(?:page|picture) \d+): (?P<why>[a-z_]+)$")


def from_calls(calls) -> list[dict]:
    """[{where, why, sentence}] read back from the run's calls (`STEP`), in order; nothing for a run that read every page."""
    out: list[dict] = []
    for c in calls if isinstance(calls, list) else []:
        if not isinstance(c, dict) or c.get("step") != STEP:
            continue
        for part in str(c.get("code") or "").split("; "):
            m = _ITEM.match(part.strip())
            if m:
                out.append(
                    {**m.groupdict(), "sentence": sentence(m["where"], m["why"])}
                )
    return out


def record_state(calls) -> str:
    """What the run's record says about unread pages: LISTED (some were not read), ALL_READ (the check ran: none), NOT_RECORDED (an older
    review, or the check did not run). Never "all read" for a review that was not checked."""
    code = None
    for c in calls if isinstance(calls, list) else []:
        if isinstance(c, dict) and c.get("step") == STEP:
            code = str(c.get("code") or "")
    if code is None or code == NOT_CHECKED:
        return NOT_RECORDED
    return ALL_READ if code == NONE else LISTED


def sentence(where: str, why: str) -> str:
    return f"{where[0].upper()}{where[1:]} was not read: {WHY_WORDS.get(why, 'no reading came back')}."


def summary(items: list[dict]) -> str:
    """One line for the page and the file: how many were not read and which ("Not read: pages 7, 9; picture 3")."""
    if not items:
        return ""
    pages = [i["where"].split()[1] for i in items if i["where"].startswith("page")]
    pics = [i["where"].split()[1] for i in items if i["where"].startswith("picture")]
    parts = (
        [f"page{'s' if len(pages) > 1 else ''} " + ", ".join(pages)] if pages else []
    ) + ([f"picture{'s' if len(pics) > 1 else ''} " + ", ".join(pics)] if pics else [])
    return (
        "Not read (no text and no picture reading came back, or it has not run): "
        + "; ".join(parts)
        + "."
    )


def read_calls(paper):
    """The run-record entries for the paper: where each page's text came from, and (only when some were not read) which were not."""
    from .engine import CallRecord

    calls = [
        CallRecord(
            step="aim_read_pages",
            model="code",
            prompt_chars=0,
            code=paper.source_note(),
        )
    ]
    # ALWAYS written: "none" only when the check really ran and found every page read; "not_checked" when it did not run or failed
    code = (
        note(paper.unread)
        if getattr(paper, "unread", None)
        else (NONE if getattr(paper, "unread_checked", False) else NOT_CHECKED)
    )
    calls.append(CallRecord(step=STEP, model="code", prompt_chars=0, code=code))
    return calls
