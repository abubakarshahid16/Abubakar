"""Fill a reviewed datasheet's equipment type and title from its own heading
(order 196 / 206.1).

Found on the invented pump sheet: its stored equipment type, title and
discipline were empty, so nothing the part-scope step may trust named the
equipment and every clause was held. The readers (`classification`) already
name "Centrifugal Pump" from the heading, but they ran only for a document whose
role was already CONTRACTOR_SUBMITTAL, and nothing filled the title.

A review of a document says it is the submittal, so the readers now run for it
too when its role is still unset. Their own guards stand: a confirmed record, a
value a person put there, and "no evidence, no write" are untouched; the quote
and page are kept; an engineer corrects through `confirm`. Never fails a review.
"""

from __future__ import annotations

from collections.abc import Sequence

TITLE_WORDS = 8


def is_submittal(row, reviewed: bool) -> bool:
    """`row`: the document's classification row (or None). A CONTRACTOR_SUBMITTAL,
    or a document with NO role yet that a review is being run on. Any other role
    (a company standard) is never taken for one."""
    if row is None:
        return False
    role = row["document_role"]
    return role == "CONTRACTOR_SUBMITTAL" or (reviewed and not role)


def heading_lead(line: str, words: int = TITLE_WORDS) -> str:
    """A title-block line as the sheet's NAME: a short line whole; a longer one
    (a form prints its heading and first fields on one line) only up to its
    first field label ("Doc No.:"), dropping the label's own leading word when
    the heading is in capitals and the label is not. Long prose gives ''."""
    parts = line.split()
    if len(parts) > words:
        labels = [n for n, word in enumerate(parts) if word.endswith(":")]
        parts = parts[: labels[0]] if labels else []
        while len(parts) > 1 and not parts[-1].isupper() and parts[-2].isupper():
            parts.pop()
    return " ".join(parts) if 0 < len(parts) <= words else ""


def heading_title(pages: Sequence[dict]):
    """The sheet's title as evidence: the title-block line that NAMES its
    equipment (the line the equipment-type reader quotes), cut to its heading.
    Never a guess: a sheet whose heading names no equipment gets no title."""
    from . import classification as c

    lines = c.title_block_lines(pages)
    named = c.suggest_equipment_type_from_title(lines)
    if named is None:
        return None
    for page_no, line in lines:
        if page_no == named.page and named.quote.lower() in line.lower():
            if lead := heading_lead(line):
                return c.FieldEvidence(
                    field="title",
                    value=lead,
                    page=page_no,
                    quote=line.strip()[:160],
                    pages=[page_no],
                    method="title_block_heading",
                    confidence=c._CONFIDENCE["title"],
                    classifier_version=c.SUBMITTAL_METADATA_CLASSIFIER_VERSION,
                )
    return None


def add_title(suggestion, pages: Sequence[dict]):
    """`suggestion` with the heading title added when the sheet's heading names
    its equipment."""
    if (title := heading_title(pages)) is not None:
        suggestion.found["title"] = title
    return suggestion


def ensure(document_id: str) -> None:
    """Run both readers for a document a review is being run on."""
    from . import classification as c
    from . import errors

    for fill in (
        c.classify_equipment_type_for_submittal,
        c.classify_metadata_for_submittal,
    ):
        try:
            fill(document_id, reviewed=True)
        except Exception as exc:  # noqa: BLE001 - a review never fails on this
            errors.record_failure(exc, document_id=document_id, stage="classify_fill")
