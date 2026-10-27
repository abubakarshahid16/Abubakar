"""Order 261.2: a failed AI reading must never make a verdict more confident.

The datasheet reader asks the AI for each page and keeps only what the code gates accept. When
a page's answer was unusable (an engine error), a page timed out, or the reader was stopped or
unavailable, the reading is DEGRADED: the conflicts the AI would have raised never appear, so the
rule reader's values stand unchallenged and the checklist can report MORE passes than a clean
read (s2, 27 Oct: two 35B models on one Mac, AI facts 68 -> 39, conflicts 16 -> 4, meets 81 -> 88,
the run summary saying nothing). This module says so, in counts only, and holds every checklist
pass for the engineer while the read is degraded. It never turns a failure into a pass, and never
lifts a hold.

NOT a trigger: "more answers refused by the code gates than agreed". s2's real runs show a CLEAN
read of the PSV sheet refuses 117 and agrees 58 (the AI always proposes more than it can prove),
so that count says nothing about a broken engine. The refusal COUNTS are still recorded.
"""

from __future__ import annotations

from . import datasheets

NO_TEXT = "no text on this page"
HELD = (
    "Engineer to check: the rule reader found this stated, but the AI reader's reading of this "
    "datasheet was degraded ({why}), so the pass is not trusted."
)


def assess(summary: dict | None) -> dict | None:
    """The degraded-read record for a reader summary, or None when the AI reader was not asked
    or read cleanly. Counts and reasons only."""
    if not summary or summary.get("engine") in (None, "off"):
        return None
    refused = int(summary.get("refused_by_gate") or 0)
    agreed = int(summary.get("agreed") or 0)
    timed_out = len(summary.get("timed_out") or [])
    # a page left to the code readers because the engine's answer was unusable, ran out of
    # time or was unavailable ("no text on this page" is a fact about the page, not a failure)
    failed = sum(
        1 for why in (summary.get("code_only") or {}).values() if why != NO_TEXT
    )
    why = []
    if failed:
        why.append("failed_pages")
    if timed_out:
        why.append("timed_out")
    if summary.get("stopped"):
        why.append("stopped")
    if summary.get("unavailable"):
        why.append("unavailable")
    if not why:
        return None
    return {
        "refused": refused,
        "agreed": agreed,
        "timed_out_pages": timed_out,
        "failed_pages": failed,
        "why": why,
    }


def line(record: dict) -> str:
    """The sentence for the CRS banner and the review notes."""
    return (
        "The AI reader's reading of this datasheet was degraded ("
        + _words(record)
        + "); checklist passes were held for the engineer and the values read by the rule "
        "reader alone were not challenged."
    )


def _words(record: dict) -> str:
    said = {
        "failed_pages": f"{record['failed_pages']} page(s) had an unusable or missing AI answer",
        "timed_out": f"{record['timed_out_pages']} page(s) timed out",
        "stopped": "the reader was stopped before it finished",
        "unavailable": "the AI reader was unavailable",
    }
    return "; ".join(said[w] for w in record["why"])


def with_reader(split: dict, document_id: str) -> dict:
    """The run's split with the reader summary and, when the read was degraded, its record."""
    reader = datasheets.latest_reader_summary(document_id)
    if reader:
        split = {**split, "reader": reader}
    record = assess(reader)
    return {**split, "degraded_read": record} if record else split


def hold(results: list[dict], document_id: str) -> list[dict]:
    """The checklist results with every pass held for the engineer while the read is degraded."""
    record = assess(datasheets.latest_reader_summary(document_id))
    if not record:
        return results
    held = []
    for r in results:
        if r["status"] == "COMPLIANT" and r.get("checklist"):
            r = {
                **r,
                "status": "NEEDS_ENGINEER_REVIEW",
                "detail": HELD.format(why=_words(record)),
            }
        held.append(r)
    return held
