"""The reader comes FIRST (lead A, owner's "the goal decides"; `redesign/TABLE-VALUE.md`): the calculator never runs on values that do not belong to the paper's
current text, and a page with no usable value is read by the one AI reader before it runs.

  * `split_current`: a stored fact is CURRENT while its page's stored text still has the checksum the fact was read from (`submittal_facts.page_text_sha`); a fact
    stored before that column existed has none, and is current only while its own quote is found in the page's text. A stale fact is not compared: the run counts
    them (`stale_values`) and says "N stored values belong to an earlier text of this paper and were not used". A blank fact (nothing read) is kept: it says "not given".
  * `read_missing` (setting `AI_REVIEW_READER_FIRST_ENABLED`, off): for each page that has text and no current value, the existing datasheet reader (`datasheet_ai`: its
    engine setting, its gates, its spend caps, its code-verified page quote: no new path out of the machine) reads the page. Its accepted values come back as IN-MEMORY
    facts of this run (nothing is written to the facts table), each with the quote the code verified on the page. The engine is `DATASHEET_AI_READER`; off says so.
Words and counts only; no document text is logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence

from .config import settings
from .reader_api import _fold

log = logging.getLogger(__name__)

STALE_WORDS = "stored values belong to an earlier text of this paper and were not used"


def page_sha(text: object) -> str | None:
    t = str(text or "")
    return hashlib.sha256(t.encode("utf-8")).hexdigest() if t.strip() else None


def is_current(fact: Mapping, pages: Mapping[int, str]) -> bool:
    """The fact still belongs to its page's text."""
    if fact.get("is_blank"):
        return True
    text = pages.get(fact.get("page"))
    if not str(text or "").strip():
        return False
    sha = fact.get("page_text_sha")
    if sha:
        return sha == page_sha(text)
    quote = _fold(str(fact.get("source_text") or fact.get("raw_value") or ""))
    return bool(quote) and quote in _fold(str(text))


def split_current(
    facts: Sequence[Mapping], pages: Mapping[int, str]
) -> tuple[list[dict], int]:
    """(the current facts, how many were stale)."""
    keep = [dict(f) for f in facts if is_current(f, pages)]
    return keep, len(facts) - len(keep)


def pages_to_read(current: Sequence[Mapping], pages: Mapping[int, str]) -> list[int]:
    """Pages with text and no current value (a blank counts as none)."""
    have = {f.get("page") for f in current if not f.get("is_blank")}
    return sorted(
        p
        for p, t in pages.items()
        if isinstance(p, int) and str(t or "").strip() and p not in have
    )


def enabled() -> bool:
    return bool(settings.ai_review_reader_first_enabled)


def _fact_of(page: int, i: int, f: Mapping, engine: str) -> dict:
    """An accepted AI reading as a fact of this run: the page quote the reader's own code verified rides in `bbox`, as the stored AI facts carry it."""
    value, unit = str(f.get("value") or "").strip(), str(f.get("unit") or "").strip()
    return {
        "id": f"ai:{page}:{i}",
        "page": page,
        "field_label": f.get("field"),
        "field_name": str(f.get("field") or "").lower(),
        "raw_value": value or None,
        "raw_unit": unit or None,
        "unit": unit or None,
        "source_text": f.get("quote"),
        "equipment_tag": None,
        "is_blank": 0 if value else 1,
        "validation_state": "needs_engineer_review"
        if f.get("kind_unconfirmed")
        else None,
        "extraction_method": "model",
        "confidence": 0.5,
        "bbox": json.dumps(
            {
                "reader": "datasheet_ai",
                "engine": engine,
                "quote": f.get("quote"),
                "quote_on_page": True,
            }
        ),
        "page_text_sha": None,
        "ai_read": True,
    }


def read_missing(
    submittal: str, pages: Mapping[int, str], current: Sequence[Mapping]
) -> tuple[list[dict], dict]:
    """(the in-memory facts the reader returned for the pages that had no current value, what was done in words and counts). Off, or no engine: no facts and a reason."""
    wanted = pages_to_read(current, pages)
    note: dict = {"pages_wanted": len(wanted)}
    if not enabled():
        return [], {**note, "ran": False, "reason": "reading first is off"}
    if not wanted:
        return [], {**note, "ran": False, "reason": "every page has a current value"}
    from . import claude_approved, datasheet_ai

    engine = datasheet_ai.engine_setting()
    if engine == datasheet_ai.OFF:
        return [], {
            **note,
            "ran": False,
            "reason": "the datasheet reader (DATASHEET_AI_READER) is off, so no page was read first",
        }
    try:
        with claude_approved.carrying([submittal]):
            run = datasheet_ai.read_pages({p: pages[p] for p in wanted}, engine)
    except Exception as exc:  # noqa: BLE001 - the reader never fails the review; the run says it did not read
        log.warning("reader first: did not run (%s)", type(exc).__name__)
        return [], {
            **note,
            "ran": False,
            "reason": f"the reader did not run: an error ({type(exc).__name__})",
        }
    out: list[dict] = []
    for page in wanted:
        for i, f in enumerate(
            (run.get("pages", {}).get(page) or {}).get("facts") or []
        ):
            out.append(_fact_of(page, i, f, str(run.get("engine") or engine)))
    return out, {
        **note,
        "ran": True,
        "engine": run.get("engine"),
        "pages_read": len(run.get("pages") or {}),
        "pages_not_read": len(run.get("reasons") or {}),
        "facts": len(out),
        "reason": None if out else "the reader returned no value for these pages",
    }
