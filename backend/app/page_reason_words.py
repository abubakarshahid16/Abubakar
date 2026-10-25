"""Plain words for why a datasheet page gave no value (order 124 item 9).

The page ledger stores one sentence per page that produced no fact
(`facts_reason`), and engineers read it on "How this was reviewed" and the
readiness strip. It used to be an engine note - "33 label-value pairs were
recovered and none became a fact (12 by noise: revision table, ...)". This
module turns the same counts into a sentence an engineer understands, and
keeps the engine note as a separate DETAIL the screen does not show: it is
in the extraction result's `unparsed` entry and in the server log (counts and
rule names only, never page text), so the numbers stay findable.

ONE TABLE (`PLAIN`) maps every drop reason the readers count - the
`row_noise` rules and the extractor's own gates - to the words for what the
page holds. A reason the table does not know is said as "other text that is
not a value", never guessed at.

THE TWO FAILURES STAY APART (see `datasheets._unparsed_reason`): a page with
nothing recovered and a page whose every pair was filtered want opposite
responses, so they get different sentences.
"""

from __future__ import annotations

import logging

from . import row_noise

_log = logging.getLogger("uvicorn.error")

#: Nothing on the page read as a label with a value beside it. The code does
#: not know why, so the cause is offered as a possibility only.
NO_PAIRS = "No labelled values were found on this page (it may be a drawing or a scan)."

#: The engine's note for the same case, kept as the detail.
NO_PAIRS_DETAIL = "no label-value pairs recovered from this page"

#: Said for a drop reason `PLAIN` does not name.
OTHER = "other text that is not a value"

#: Every drop reason, in plain words: what the page holds instead of a value.
PLAIN = {
    row_noise.RULER: "a row-number ruler",
    row_noise.REVISION: "a revision table",
    row_noise.DOCUMENT_ID: "a title block",
    row_noise.HEADER_AS_VALUE: "table column headings",
    row_noise.REFERENCE_ONLY: "references to notes or clauses instead of values",
    row_noise.FRAGMENT_LABEL: "pieces of labels split across lines",
    row_noise.MERGED_BLOCK: "blocks of text that run several fields together",
    row_noise.IDENTIFIER_NUMBER: "reference numbers (such as job or order numbers)",
    row_noise.LABEL_AS_VALUE: "form labels with no answer beside them",
    "value gate": "text the reader could not take as a value",
    "duplicate": "repeats of text already read on this page",
    "furniture": "a header or footer repeated on other pages",
    "furniture, tag, date or blank": "a header, footer, tag, date or blank",
    "tag row": "the equipment tag",
    "date": "dates",
    "empty label": "values with no label",
    "read as a tag-column row": "rows already read under the tag columns",
    "read as a grid row": "rows already read as part of a table",
    "checkbox on quantity": "yes/no answers where a measured value belongs",
    "refused by create_fact": "readings that could not be stored",
    "geometry: unit column": "unit columns",
    "geometry: furniture, tag or date": "a header, footer, tag or date",
    "geometry: same as rule reader": "values already read another way",
}


def _by_size(dropped: dict[str, int]) -> list[tuple[str, int]]:
    """The non-zero drop counts, biggest first, so the cause reads first."""
    return sorted(
        ((reason, n) for reason, n in dropped.items() if n),
        key=lambda kv: (-kv[1], kv[0]),
    )


def _joined(phrases: list[str]) -> str:
    if len(phrases) < 2:
        return "".join(phrases)
    return f"{', '.join(phrases[:-1])} and {phrases[-1]}"


def unparsed_reason(n_pairs: int, dropped: dict[str, int]) -> str:
    """The plain sentence stored as the page's reason for having no fact."""
    if not n_pairs:
        return NO_PAIRS
    phrases: list[str] = []
    for reason, _n in _by_size(dropped):
        words = PLAIN.get(reason, OTHER)
        if words not in phrases:
            phrases.append(words)
    if not phrases:
        return (
            "Nothing on this page was read as a datasheet value, "
            "and the reader did not record why."
        )
    # WHAT THE READER SAW, NOT WHAT THE PAGE IS (review of #1155): the code
    # knows nothing was READ as a value, never that the page holds none.
    return (
        "Nothing on this page was read as a datasheet value. "
        f"What the reader found: {_joined(phrases)}."
    )


def no_field_found(dropped: dict[str, int]) -> str:
    """Order 165: the plain sentence for a page both readers read and found no
    datasheet field on. What the code reader saw is said as before; the claim
    is only that two readers found no field, never that the page holds none."""
    said = (
        "Read, no checklist field found: the code readers and the AI reader "
        "both read this page and found no datasheet field on it."
    )
    if not dropped:
        return said
    seen = unparsed_reason(1, dropped)
    return f"{said} {seen.split('. ', 1)[1] if '. ' in seen else seen}"


def unparsed_detail(
    n_pairs: int, dropped: dict[str, int], page: int | None = None
) -> str:
    """The engine's note for the same page: counts per drop rule. Logged
    when the page is named, so the counts outlive the extraction result."""
    if not n_pairs:
        detail = NO_PAIRS_DETAIL
    else:
        counts = ", ".join(f"{n} by {reason}" for reason, n in _by_size(dropped))
        detail = (
            f"{n_pairs} label-value pairs were recovered and none became a "
            f"fact ({counts or 'no reason recorded'})"
        )
    if page is not None:
        _log.info("datasheet page %s gave no fact: %s", page, detail)
    return detail


def _clause(text: str) -> str:
    return (text or "").strip().rstrip(".")


def ai_note(why: str | None) -> str:
    """What the AI reader did on a page that ended with no value."""
    if not why:
        return (
            "The AI reader read the page, but none of its readings "
            "could be confirmed on the page."
        )
    return f"The AI reader added nothing here: {_clause(why)}."


def vision_route_note(why: str | None) -> str:
    """Why the picture reader was not asked about this page."""
    from . import datasheets

    plain = {
        datasheets.VISION_NOT_NEEDED: "a text reader had found labelled text on this page",
        datasheets.VISION_NO_TEXT_LAYER: (
            "the page has no text layer to check a reading against"
        ),
        datasheets.VISION_BUDGET: "its page limit for this document was reached",
    }
    if why is None:
        return "The picture reader was not used on this page."
    return f"The picture reader was not used: {plain.get(why, _clause(why))}."


def vision_note(reading, kept_here: int, unavailable: str | None) -> str:
    """What the picture (vision) reader did on a page it was asked about."""
    if reading is None:
        return f"The picture reader did not run ({unavailable or 'the page could not be rendered'})."
    if reading.refused and not reading.asked:
        return f"The picture reader was not used ({_clause(reading.refused)})."
    kind = (
        f" It called the page a '{reading.page_kind}' (its own word, not checked)."
        if reading.page_kind
        else ""
    )
    return (
        f"The picture reader suggested {reading.proposed} value(s); "
        f"{len(reading.kept)} matched the page text and {kept_here} recorded.{kind}"
    )
