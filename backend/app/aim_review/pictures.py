"""PAGE PICTURES IN A REVIEW (owner, 26 Nov 2026 14:59 PKT, #1584 comment 7188761254: "Yes, allow it"; job J3).

Behind its own switch, AIM_PAGE_PICTURES_ENABLED, OFF by default (on only after a scored run of a planted copy whose mistake shows only
on a drawing or sketch page, and the five scored kinds not down). With the switch off nothing here runs and a review is byte-for-byte
the review it was.

With the switch on, a general review on Claude reads, at its start and inside its own run, the pages of the PAPER UNDER REVIEW that hold
no text and have no picture reading yet (`picture_stage.targets`): each page picture is transcribed once by the upload stage's own reader
(`picture_stage.run`), and the words come back where recognised text is stored, so the review then reads that page like any other and
the unread-pages list names only what is still not read. This is the one place the review runs a picture reading (the review of 7a,
M2, kept it to the upload worker; the owner's answer is about a review).

  * ONLY the paper under review: no other document's picture. The calls carry the paper (`claude_approved.carrying`) inside the run's
    own gate (`faults.during_run` -> `claude_approved.reviewing`), so the run's stored list, the refusals, the consent records and the
    register block decide exactly as for its text.
  * ROUTE AND MONEY: Claude only through `reasoning_provider.ClaudeProvider` -> `reader_transport`, under the `claude_spend` caps and the
    run's ledger (`for_run`). Each picture call is also a row of the run's own meter (step `aim_page_pictures`), and a page starts only
    when the run's spent + held + that page's worst case stays within the run's cap; a page that would not fit, and every page after it,
    is "refused" and named as such (`unread.REFUSED`). At most `picture_stage.MAX_PAGES` pages a pass.
  * NOT on Local only (the local engine reads no images), and not when the AI reviewer's own engine line does not give Claude
    (`AGENT_REVIEW_ENGINE`; `reasoning_provider.claude_unavailable_for_task`): then nothing is sent and the pages stay "not read".
  * The plan lists the pages whose pictures will leave (`plan_block`), with the documents.
The readings are written by `picture_stage` (`page_ocr`, `page_picture_reads`): ids, page numbers and the transcribed words, as the
upload stage writes them. Nothing here logs document text.
"""

from __future__ import annotations

import logging
import sqlite3

from app.config import settings

from .budget import is_local

log = logging.getLogger(__name__)

STEP = "aim_page_pictures"


def on() -> bool:
    return bool(settings.aim_page_pictures_enabled)


def _worst_usd(model: str) -> float:
    """The most one page picture can cost: the largest image + the prompt in, the stage's answer limit out, at list price."""
    from app import claude_image_tokens, claude_spend, picture_stage

    tokens_in = claude_image_tokens.IMAGE_MAX_TOKENS + 1_000
    p_in, p_out = claude_spend.price_for(model, tokens_in)[:2]
    return (tokens_in * p_in + picture_stage.MAX_OUTPUT_TOKENS * p_out) / 1e6


class OverCap(Exception):
    """A page picture that would pass the run's own money cap: the stage marks it, and every page after it, refused."""


class _Metered:
    """The page-picture reader for one run: Claude, each call checked against and charged to the run's meter."""

    def __init__(self, meter, provider, model: str) -> None:
        self.meter, self.provider, self.requested_model = meter, provider, model
        self.worst = _worst_usd(model)

    def reason(self, packet):
        from .engine import CallRecord

        if self.meter.spent + self.meter.held + self.worst > self.meter.cap + 1e-9:
            raise OverCap("the review's money cap")
        response = self.provider.reason(packet)
        self.meter.charge(CallRecord(step=STEP, model=str(response.model_tag or self.requested_model),
                                     prompt_chars=len(packet.prompt), usd=float(response.cost_usd or 0.0),
                                     input_tokens=int(response.tokens_in or 0), output_tokens=int(response.tokens_out or 0),
                                     seconds=float(response.wall_time_s or 0.0)))  # fmt: skip
        return response


def _provider():
    """(Claude for page pictures, None) or (None, why): the AI reviewer's own engine line decides, as for its text."""
    from app import vision_reader
    from app.reasoning_provider import ClaudeProvider, claude_unavailable_for_task

    code, why = claude_unavailable_for_task(settings.agent_review_engine)
    if code is not None:
        return None, why
    return ClaudeProvider(
        settings.claude_reasoning_model, step=vision_reader.VISION_STEP
    ), None


def todo(conn, paper_id: str) -> list[int]:
    """The paper's pages to read as pictures in this review: the stage's targets, and the pages an earlier pass refused or capped
    (a cap, the lane or the approval of THAT pass) that still hold no text; never a page read, or read with no text, or failed."""
    from app import picture_stage

    again = [
        p
        for p, s in picture_stage.recorded(conn, paper_id).items()
        if s in (picture_stage.REFUSED, picture_stage.CAPPED)
    ]
    still = {int(r["page_no"]) for r in conn.execute(
        "SELECT page_no FROM pages WHERE document_id = ? AND COALESCE(char_count, 0) < ?", (paper_id, picture_stage.MIN_PAGE_CHARS))}  # fmt: skip
    return sorted(set(picture_stage.targets(conn, paper_id)) | (set(again) & still))


def read(conn, paper_id: str, meter) -> dict | None:
    """Switch on, on Claude: the paper's pages with no text read as pictures, inside the run. The stage's counts, or None when nothing
    ran (switch off, Local only, no page to read, Claude not available: then the pages stay "not read" and are named so)."""
    if not on() or is_local():
        return None
    from app import picture_stage

    # the upload is reading this file now: never twice at once; the unread list names the pages
    if picture_stage.reading_now(paper_id):
        log.info("page pictures: the upload is reading this paper; not in this review")
        return None
    try:
        pages = todo(conn, paper_id)
        if not pages:
            return None
    except sqlite3.Error as exc:  # a check that cannot run reads nothing; the unread list still names the pages
        log.info("page pictures: not checked (%s)", type(exc).__name__)
        return None
    provider, why = _provider()
    if provider is None:
        log.info("page pictures: Claude not available for the AI reviewer (%s)", why)
        return None
    counts = picture_stage.run(
        paper_id,
        provider=_Metered(meter, provider, settings.claude_reasoning_model),
        pages=pages,
    )
    log.info("page pictures: %s", counts)
    return counts


def plan_block(conn, paper_id: str) -> dict | None:
    """{"pages", "sentence"} for the plan when the switch is on and the paper has pages whose pictures will be sent; else None."""
    if not on():
        return None
    from app import picture_stage

    try:
        pages = todo(conn, paper_id)[: picture_stage.MAX_PAGES]
    except sqlite3.Error:  # the plan never fails on this list
        return None
    if not pages:
        return None
    named = ", ".join(str(p) for p in pages)
    return {"pages": pages, "sentence": f"Page pictures that will be sent to Claude: page{'s' if len(pages) > 1 else ''} {named} of "
            "the paper under review (these pages hold no text, so Claude reads their pictures)."}  # fmt: skip
