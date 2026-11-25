"""Pages that local recognition cannot read are read as PICTURES by Claude (order 14, #1905; lead's order of 25 Nov 2026).

A page of the paper under review that has no text and none came back from the app's own local recognition (a scan the engine cannot
make out, a drawing sheet that is only a picture) is rendered and sent to Claude to be TRANSCRIBED, through the one approved path
(`reasoning_provider.ClaudeProvider` -> `reader_transport`, its caps, `claude_spend`), behind the page-image reader's own engine setting
(`VISION_READER_ENGINE`: `vision_reader.provider()`; a run on Local only, a closed lane, a missing key or a switch off means nothing is
asked and the page stays "not read", said plainly). No new switch, no new outbound path. Only the paper under review is sent: the run's
stored list of documents decides whether it may go at all (the gate asks before every call, `claude_approved`), and a contract goes
only where the run's consent covers it.

HONEST. The words that come back are a transcription, read against the PAGE as nothing but a picture: the page is marked as read by
picture (`paper.FROM_PICTURE`, in the run record and on the file) and a page whose transcription holds no text stays not read. A page
counts as read only if text came back. At most `MAX_PAGES` pages per review; the plan says how many and what they can cost before the
start (`plan_note`).
"""

from __future__ import annotations

import logging

from .paper import FROM_PICTURE
from .unread import CAPPED, FAILED, MIN_PAGE_CHARS, NO_TEXT, NO_TEXT_AFTER, REFUSED

log = logging.getLogger(__name__)

#: At most this many pages of one review are read as pictures (the rest stay "not read").
MAX_PAGES = 10
#: The unread reasons local recognition has already had its turn for: a page still "waiting" is not sent, local recognition may read it.
READABLE = (NO_TEXT, NO_TEXT_AFTER, FAILED)
PROMPT_VERSION = "aim-picture-v1"
MAX_OUTPUT_TOKENS = 4000
TIMEOUT_S = 300.0
EMPTY = "[no text]"
SYSTEM = (
    "You transcribe ONE page image. Return the text exactly as printed, in reading order, one line per printed line; write a table row as "
    "one line with its cells separated by two spaces. Do not interpret, summarise, correct, translate or add anything. Write [illegible] "
    f"for a part you cannot read. If the page holds no text at all, answer exactly: {EMPTY}"
)


def _todo(paper) -> list[int]:
    return [
        int(i["where"].split()[1])
        for i in paper.unread
        if i["where"].startswith("page ") and i["why"] in READABLE
    ]


def _page_of(item: dict) -> int:
    where = str(item.get("where") or "")
    return int(where.split()[1]) if where.startswith("page ") else -1


def read(paper_id: str, paper, path, provider=None):
    """The paper with the pages Claude could transcribe added to `paper.pages` (source `FROM_PICTURE`) and taken off `paper.unread`.
    Never raises; a refusal (caps, lane, approval) leaves the pages unread and says why in their reason."""
    todo = _todo(paper)
    if not todo or path is None:
        return paper
    if provider is None:
        from app import vision_reader

        provider, _why = vision_reader.provider()
    if provider is None:
        return paper  # the page-image reader is not switched to Claude for this run: nothing is asked
    from app import claude_approved

    picked = todo[:MAX_PAGES]
    results: dict[int, str] = {}
    stopped = False
    with claude_approved.carrying([paper_id]):
        for n in picked:
            try:
                text = _transcribe(path, n, provider)
            except Exception as exc:  # noqa: BLE001 - a refusal (cap, lane, approval, transport) leaves this page and the rest unread
                log.info(
                    "general review: picture reading stopped (%s)", type(exc).__name__
                )
                stopped = True
                break
            if text is not None:
                results[n] = text
    for n, text in results.items():
        paper.pages[n] = text
        paper.sources[n] = FROM_PICTURE
    why = dict.fromkeys(todo[MAX_PAGES:], CAPPED)
    if stopped:
        why.update({n: REFUSED for n in picked if n not in results})
    paper.unread = [
        {**i, "why": why.get(_page_of(i), i["why"])}
        for i in paper.unread
        if _page_of(i) not in results
    ]
    return paper


def _transcribe(path, page_no: int, provider) -> str | None:
    """The text Claude read from page `page_no`, or None when the page holds none. The model call is never inside the PDF lock."""
    from app import pdf_guard, vision_reader
    from app.reasoning_provider import Packet

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


# ------------------------------------------------------------------ the plan's sentence (before the start)


def plan_note(conn, paper_id: str) -> str | None:
    """ "N pages of this paper will be read as pictures by Claude, up to USD X." from the stored page records, or None. Counts only pages
    local recognition has had its turn for and found nothing in (or that are no scan and hold no text); a page still waiting for local
    recognition is not counted (it may be read for free). Only when the page-image reader is switched to Claude."""
    from app import claude_image_tokens, claude_spend, vision_reader
    from app.config import settings

    pages = _stored_unreadable(conn, paper_id)
    if not pages:
        return None
    provider, _why = vision_reader.provider()
    if provider is None:
        return None
    n = min(len(pages), MAX_PAGES)
    tokens = claude_image_tokens.image_tokens(
        vision_reader.MAX_EDGE_PX, int(vision_reader.MAX_EDGE_PX * 0.75)
    )
    each = claude_spend.worst_case_usd(
        getattr(provider, "requested_model", None) or settings.claude_reasoning_model,
        len(SYSTEM) + 40, MAX_OUTPUT_TOKENS, image_tokens=tokens,
    )  # fmt: skip
    more = (
        f" ({len(pages) - n} more stay not read: at most {MAX_PAGES} pages per review)"
        if len(pages) > n
        else ""
    )
    return f"{n} page{'s' if n != 1 else ''} of this paper will be read as pictures by Claude, up to USD {each * n:.2f}{more}."


def _stored_unreadable(conn, paper_id: str) -> list[int]:
    try:
        rows = conn.execute(
            "SELECT page_no, char_count, needs_ocr FROM pages WHERE document_id = ? ORDER BY page_no",
            (paper_id,),
        ).fetchall()
        ocr = {
            int(r["page_no"]): (r["error"], int(r["char_count"] or 0))
            for r in conn.execute(
                "SELECT page_no, error, char_count FROM page_ocr WHERE document_id = ?",
                (paper_id,),
            )
        }
    except Exception as exc:  # noqa: BLE001 - an old database without the tables: nothing is counted
        log.debug("picture pages not counted (%s)", type(exc).__name__)
        return []
    out = []
    for r in rows:
        n = int(r["page_no"])
        if int(r["char_count"] or 0) >= MIN_PAGE_CHARS:
            continue
        if n in ocr:
            if ocr[n][0] or ocr[n][1] < MIN_PAGE_CHARS:
                out.append(
                    n
                )  # local recognition ran: failed, or came back with no text
        elif not r["needs_ocr"]:
            out.append(n)  # no text and not a scan local recognition would take
    return out
