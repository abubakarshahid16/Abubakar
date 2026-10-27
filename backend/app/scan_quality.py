"""How well a scanned page was read, shown beside the citation that rests on it (#505).

A citation to a scanned page rests on recognised text, not on a text layer. The
engineer could not see how good that recognition was, so a smudged page looked as
sure as a clean one. The page's stored recognition record (`page_ocr`) already
holds the engine's own score per page; this turns it into a closed tier.

WHAT THE TIER IS. The recogniser's OWN confidence for the page, grouped by cut-offs
this module states. It is not a measured accuracy and is never called "high"
(CLAUDE.md rule 4): the words are "clear", "mixed" and "poor". Every tier carries
its denominator: `low_conf_boxes` out of `box_count`.

NAMED STATES, NEVER A SILENT PASS.
- no `scan` at all: the page has a text layer and was not recognised; nothing to say;
- `not_yet_read`: the page needs recognition and has none yet;
- `could_not_read`: recognition failed on the page;
- `not_checked`: recognised, but the engine gave no confidence (no boxes);
- `clear` / `mixed` / `poor`: the tiers above.

Display only: nothing here changes a verdict, a score or a stored row. Ids, numbers
and closed words; never page text.
"""

from __future__ import annotations

from pydantic import BaseModel

from . import schemas
from .db import connect

CLEAR = "clear"
MIXED = "mixed"
POOR = "poor"
NOT_CHECKED = "not_checked"
NOT_YET_READ = "not_yet_read"
COULD_NOT_READ = "could_not_read"

#: A page is "clear" at or above this mean confidence AND with at most
#: `CLEAR_MAX_LOW_SHARE` of its boxes below the stored low-confidence threshold.
CLEAR_MIN_MEAN = 0.85
CLEAR_MAX_LOW_SHARE = 0.05
#: A page is "poor" below this mean confidence, or with more than
#: `POOR_MIN_LOW_SHARE` of its boxes below the low-confidence threshold.
POOR_MAX_MEAN = 0.70
POOR_MIN_LOW_SHARE = 0.20

WORDS = {
    CLEAR: "scanned page, read clearly",
    MIXED: "scanned page, some words read with low confidence",
    POOR: "scanned page, read poorly: check the words by eye",
    NOT_CHECKED: "scanned page: the reader gave no confidence",
    NOT_YET_READ: "scanned page: not read yet",
    COULD_NOT_READ: "scanned page: reading failed",
}


class ScanQuality(BaseModel):
    """`GET /api/reviews/findings/{id}/evidence`, one side: the page's reading record."""

    tier: str
    #: the tier in words for the screen
    words: str
    #: the recogniser's mean confidence for the page, 0 to 1; null when it gave none
    mean_conf: float | None = None
    #: boxes below the low-confidence threshold, out of `box_count`
    low_conf_boxes: int | None = None
    box_count: int | None = None


class EvidenceSideScanned(schemas.EvidenceSide):
    #: null for a page with a text layer (nothing was recognised)
    scan: ScanQuality | None = None


class FindingEvidenceScanned(schemas.FindingEvidence):
    submittal: EvidenceSideScanned
    standard: EvidenceSideScanned


def tier_of(mean_conf, low_boxes, box_count) -> str:
    """The tier for one recognised page; `not_checked` when the engine gave no figure."""
    if mean_conf is None or not box_count:
        return NOT_CHECKED
    share = (low_boxes or 0) / box_count
    if mean_conf < POOR_MAX_MEAN or share > POOR_MIN_LOW_SHARE:
        return POOR
    if mean_conf >= CLEAR_MIN_MEAN and share <= CLEAR_MAX_LOW_SHARE:
        return CLEAR
    return MIXED


def _quality(tier: str, mean_conf=None, low=None, boxes=None) -> dict:
    return {
        "tier": tier,
        "words": WORDS[tier],
        "mean_conf": mean_conf,
        "low_conf_boxes": low,
        "box_count": boxes,
    }


def for_page(document_id: str | None, page_no: int | None, conn=None) -> dict | None:
    """The page's reading record as a `ScanQuality` dict, or None when the page is not a scan."""
    if not document_id or not page_no:
        return None
    conn = conn or connect()
    ocr = conn.execute(
        "SELECT mean_conf, low_conf_boxes, box_count, error FROM page_ocr"
        " WHERE document_id = ? AND page_no = ?",
        (document_id, page_no),
    ).fetchone()
    if ocr is not None:
        if ocr["error"]:
            return _quality(COULD_NOT_READ)
        tier = tier_of(ocr["mean_conf"], ocr["low_conf_boxes"], ocr["box_count"])
        if tier == NOT_CHECKED:
            return _quality(NOT_CHECKED, ocr["mean_conf"], None, ocr["box_count"])
        return _quality(
            tier,
            round(float(ocr["mean_conf"]), 2),
            int(ocr["low_conf_boxes"] or 0),
            int(ocr["box_count"]),
        )
    page = conn.execute(
        "SELECT needs_ocr FROM pages WHERE document_id = ? AND page_no = ?",
        (document_id, page_no),
    ).fetchone()
    return _quality(NOT_YET_READ) if page is not None and page["needs_ocr"] else None


def evidence_response(finding_id: str, current: dict, scope, side_of) -> dict:
    """The `/evidence` answer: each side as `side_of(current, side, scope)` resolved it, plus its scan record."""
    out: dict = {"finding_id": finding_id}
    for side in ("submittal", "standard"):
        found = side_of(current, side, scope)
        doc = found["document"]
        out[side] = {
            "document_id": doc["id"] if doc else None,
            "filename": doc.get("filename") if doc else None,
            "page": found["page"],
            "box": found["box"],
            "reason": found["reason"],
            "scan": for_page(doc["id"] if doc else None, found["page"]),
        }
    return out
