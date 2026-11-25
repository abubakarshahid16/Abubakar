"""Picture reading as an UPLOAD-WORKER STAGE (order 14, #1905; lead 4, 26 Nov 2026): never inside a review.

A page of a document that has no text after the app's own local recognition (a scan the engine cannot make out, a drawing sheet that is
only a picture) is rendered and TRANSCRIBED by Claude, once, while the document is being ingested. The words that come back are stored where
local recognition stores its words (`page_ocr`, engine `claude-picture`), so the chunks, the search, the page ledger and every later review
follow exactly as for a recognised scan: the page then counts as read because text came back, nowhere else. The ingest loop re-chunks after
the stage (`intake_blocks.refresh`, back through CHUNKING), like after an OCR round.

ONE LANE, ONE FILE. Only the ingest worker's own pass for that document calls this, after local recognition has no page left pending, so
no second lane works on the same file at the same time, and a review never reads a picture (it only names the pages that are not read).

PRIVACY AND MONEY. Claude only through `reasoning_provider.ClaudeProvider` -> `reader_transport` under the `claude_spend` caps, behind the
page-image reader's own engine setting (`VISION_READER_ENGINE`: `vision_reader.provider()`; local, off or no key means nothing is asked,
and the pages stay "not read", said plainly). The gate asks before every call whether this document may go (`claude_approved`: the approved
list, the block list, contracts); a refusal stops the rest and every page it stopped says so. Only this document's page images are sent.
The local engine reads no images (`OllamaProvider` refuses them), so the local lane of a picture page is the app's own recognition, which has
already had its turn.

HONEST. Every page the stage looked at gets a record (`page_picture_reads`: read / no_text / failed / refused / capped) with a plain reason,
so a failed reading is said ("its picture reading failed") and is never counted as read, and the same page is not asked twice.
"""

from __future__ import annotations

import logging

from .config import settings
from .db import connect

log = logging.getLogger(__name__)

TABLE = "page_picture_reads"
ENGINE = "claude-picture"
#: At most this many pages of one document are read as pictures in one pass; the rest are recorded as capped and said so.
MAX_PAGES = 25
MIN_PAGE_CHARS = 20
PROMPT_VERSION = "aim-picture-v1"
MAX_OUTPUT_TOKENS = 4000
TIMEOUT_S = 300.0
EMPTY = "[no text]"
READ, NO_TEXT, FAILED, REFUSED, CAPPED = (
    "read",
    "no_text",
    "failed",
    "refused",
    "capped",
)
SYSTEM = (
    "You transcribe ONE page image. Return the text exactly as printed, in reading order, one line per printed line; write a table row as "
    "one line with its cells separated by two spaces. Do not interpret, summarise, correct, translate or add anything. Write [illegible] "
    f"for a part you cannot read. If the page holds no text at all, answer exactly: {EMPTY}"
)


def create_table(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} (document_id TEXT NOT NULL, page_no INTEGER NOT NULL, state TEXT NOT NULL, "
        "reason TEXT, at TEXT NOT NULL, PRIMARY KEY (document_id, page_no))"
    )


def recorded(conn, document_id: str) -> dict[int, str]:
    """page -> state for the pages the stage has looked at. Reads only (a missing table is nothing recorded)."""
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
        ).fetchone()
        is None
    ):
        return {}
    return {
        int(r["page_no"]): r["state"]
        for r in conn.execute(
            f"SELECT page_no, state FROM {TABLE} WHERE document_id = ?", (document_id,)
        )
    }


def targets(conn, document_id: str) -> list[int]:
    """Pages with no usable text that local recognition has had its turn for (it failed, or came back with no text, or the page is not a
    scan it would take) and that the stage has not looked at yet. A page still waiting for recognition is not a target."""
    done = recorded(conn, document_id)
    rows = conn.execute(
        "SELECT page_no, char_count, needs_ocr FROM pages WHERE document_id = ? ORDER BY page_no",
        (document_id,),
    ).fetchall()
    ocr = {
        int(r["page_no"]): (r["error"], int(r["char_count"] or 0))
        for r in conn.execute(
            "SELECT page_no, error, char_count FROM page_ocr WHERE document_id = ?",
            (document_id,),
        )
    }
    out = []
    for r in rows:
        n = int(r["page_no"])
        if n in done or int(r["char_count"] or 0) >= MIN_PAGE_CHARS:
            continue
        if n in ocr:
            if ocr[n][0] or ocr[n][1] < MIN_PAGE_CHARS:
                out.append(n)
        elif not r["needs_ocr"]:
            out.append(n)
    return out


def wanted(document_id: str) -> bool:
    """True when the stage has something to do and may do it: the page-image reader is switched to Claude, no page waits for local
    recognition, and some page has no text. Never raises."""
    try:
        from . import ocr, vision_reader
        from .aim_review.updates import u7b

        if not u7b():  # 7b switched off: no page is sent at upload, as main
            return False
        provider, _why = vision_reader.provider()
        if provider is None:
            return False
        conn = connect()
        return not ocr.pending_pages(document_id) and bool(targets(conn, document_id))
    except Exception as exc:  # noqa: BLE001 - a stage that cannot decide does nothing (logged); the document goes on
        log.info("picture stage: not decided (%s)", type(exc).__name__)
        return False


def _transcribe(path, page_no: int, provider) -> str | None:
    """The text Claude read from page `page_no`, or None when the page holds none. The model call is never inside the PDF lock."""
    from . import pdf_guard, vision_reader
    from .reasoning_provider import Packet

    with pdf_guard.opened(str(path)) as pdf, pdf_guard.held():
        image = vision_reader.render(pdf.load_page(page_no - 1))
    packet = Packet(
        prompt=f"Page {page_no}. Transcribe it.", num_ctx=32768, num_predict=MAX_OUTPUT_TOKENS, system=SYSTEM,
        step=vision_reader.VISION_STEP, prompt_version=PROMPT_VERSION, images=(image,), timeout_s=TIMEOUT_S, effort=vision_reader.EFFORT,
    )  # fmt: skip
    response = provider.reason(packet)
    text = str(response.text or "").strip()
    if response.truncated or not text or text == EMPTY or len(text) < MIN_PAGE_CHARS:
        return None
    return text


def _store(conn, document_id: str, page_no: int, text: str, model: str) -> None:
    from .ocr import _now

    conn.execute(
        """INSERT OR REPLACE INTO page_ocr (document_id, page_no, text, char_count, engine, model, dpi, mean_conf, min_conf, box_count,
               low_conf_boxes, alphabet_violations, alphabet_sample, seconds, recognised_at, batch_no, error)
           VALUES (?,?,?,?,?,?,?,NULL,NULL,0,0,0,'',0,?,0,NULL)""",
        (
            document_id,
            page_no,
            text,
            len(text.strip()),
            ENGINE,
            model,
            settings.ocr_dpi,
            _now(),
        ),
    )


def _mark(conn, document_id: str, page_no: int, state: str, reason: str) -> None:
    from .ocr import _now

    conn.execute(
        f"INSERT OR REPLACE INTO {TABLE}(document_id,page_no,state,reason,at) VALUES (?,?,?,?,?)",
        (document_id, page_no, state, reason[:300], _now()),
    )


def run(document_id: str, provider=None) -> dict:
    """Read the document's unread pages as pictures. Returns the counts `{read, no_text, failed, refused, capped}`. Never raises: a break
    is recorded per page ("failed") and logged by type."""
    from . import agent_review_pages, claude_approved, vision_reader

    counts = dict.fromkeys((READ, NO_TEXT, FAILED, REFUSED, CAPPED), 0)
    conn = connect()
    if provider is None:
        provider, _why = vision_reader.provider()
    todo = targets(conn, document_id)
    if provider is None or not todo:
        return counts
    row = conn.execute(
        "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    try:
        path = agent_review_pages.pdf_path(
            {"stored_path": row["stored_path"] if row else None}, settings.data_dir
        )
    except agent_review_pages.PageImageUnavailable:
        path = None
    with conn:
        create_table(conn)
    picked, model = (
        todo[:MAX_PAGES],
        str(
            getattr(provider, "requested_model", "") or settings.claude_reasoning_model
        ),
    )
    stopped_why = None
    with claude_approved.carrying([document_id]):
        for n in picked:
            if stopped_why is not None:
                state, reason = REFUSED, stopped_why
            elif path is None:
                state, reason = FAILED, "the stored file was not found"
            else:
                try:
                    text = _transcribe(path, n, provider)
                except Exception as exc:  # noqa: BLE001 - a refusal (cap, lane, approval) or a failure: this page and, for a refusal, the rest say so
                    log.info("picture stage: stopped (%s)", type(exc).__name__)
                    stopped_why = "refused: a spending cap, the lane or the approval"
                    state, reason = REFUSED, stopped_why
                else:
                    state, reason = (
                        (READ, "")
                        if text
                        else (NO_TEXT, "the picture reading came back with no text")
                    )
                    if text:
                        with conn:
                            _store(conn, document_id, n, text, model)
            with conn:
                _mark(conn, document_id, n, state, reason)
            counts[state] += 1
    for n in todo[MAX_PAGES:]:
        with conn:
            _mark(
                conn,
                document_id,
                n,
                CAPPED,
                f"past the limit of {MAX_PAGES} pages read as pictures in one pass",
            )
        counts[CAPPED] += 1
    if counts[READ]:
        with conn:
            total = conn.execute(
                "SELECT COUNT(*) c FROM page_ocr WHERE document_id = ? AND char_count > 0",
                (document_id,),
            ).fetchone()["c"]
            conn.execute(
                "UPDATE documents SET recognised_pages = ? WHERE id = ?",
                (total, document_id),
            )
    return counts
