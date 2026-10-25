"""Fill a contractor datasheet's empty title and equipment type from its own heading (order 206.1).

WHY. A submittal's `title`, `equipment_type` and `discipline` were often empty
when the review started, so the part-scope step found nothing the sheet said
about itself and HELD every clause of a standard limited to one construction
(PF1: a centrifugal pump sheet compared nothing). Two causes, both here:
  * the two READY hooks (`classification.classify_*_for_submittal`) only run
    for a document whose role is CONTRACTOR_SUBMITTAL, and a sheet that reached
    a review without that role (or was read before the classifiers existed)
    kept empty fields for good: `for_review` runs them again when the review
    starts, for a submittal whose fields are still empty;
  * no step wrote `title` at all, and the classifier's vocabulary does not name
    every kind of equipment ("ATMOSPHERIC STORAGE TANK DATASHEET"): `fill` reads
    the sheet's own HEADING, the first page's line that calls itself a data
    sheet, as the title and, only when nothing else named the equipment, as the
    equipment type.

THE DISCIPLINE OF THE CLASSIFIERS, KEPT: a value is written only to an EMPTY
field of a CONTRACTOR_SUBMITTAL nobody has confirmed (never over a person's
record, never over another value); the exact line and page are stored as the
evidence; the confidence is capped well below "high"; nothing is confirmed -
the engineer corrects it through the existing confirm. Read from `pages`
(line-shaped, exact page), never from OCR text. No word list of equipment, no
layout and no document is named: the rule is "the line that says DATA SHEET".
"""

from __future__ import annotations

import json
import logging
import re

from . import classification
from .db import connect

_log = logging.getLogger(__name__)

VERSION = "heading-fill-v1"
#: A guess from a line of text: an ordinal rank, never "high" (rule 4).
CONFIDENCE = 0.6
#: How far down the first page the heading may sit (company, project and sheet
#: number lines come first on a real form).
SCAN_LINES = 15
_MAX_HEADING_WORDS = 12
_MAX_NAME_WORDS = 5

_DATA_SHEET = re.compile(r"\bdata[\s\-]*sheet\b", re.I)
_DATA_AT_END = re.compile(r"\bdata$", re.I)
_DOCUMENT_WORDS = re.compile(
    r"\b(?:data[\s\-]*sheets?|specifications?|spec|technical|engineering)\b", re.I
)
_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z\-/&]*")


def heading(pages: list[dict]) -> tuple[int, str] | None:
    """`(page, line)` of the first page's own heading, or None.

    The heading is the first of the first `SCAN_LINES` lines that calls itself a
    data sheet ("... DATASHEET", "... DATA SHEET", "DATA" with "SHEET" on the
    next line, or two or more words ending in "DATA"), with no label colon and
    at most 12 words, that is not a sentence. A line that ends in
    "FOR" ("DATA SHEET FOR") takes the next line as its object. Several equally
    good lines are not told apart: the first one wins, as the title block reads."""
    texts = sorted(
        (p for p in pages if (p.get("text") or "").strip()), key=lambda p: p["page_no"]
    )
    if not texts:
        return None
    page_no = texts[0]["page_no"]
    lines = [ln.strip() for ln in texts[0]["text"].splitlines() if ln.strip()][
        :SCAN_LINES
    ]
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        text = line
        if _DATA_AT_END.search(line) and nxt.lower().startswith("sheet"):
            text = f"{line} {nxt}"
        elif not (
            _DATA_SHEET.search(line)
            or (_DATA_AT_END.search(line) and len(line.split()) > 1)
        ):
            continue
        if text.rstrip().lower().endswith(" for") and nxt:
            text = f"{text} {nxt}"
        text = " ".join(text.split())
        if ":" in text or len(text.split()) > _MAX_HEADING_WORDS or _is_sentence(text):
            continue
        return page_no, text
    return None


def _is_sentence(text: str) -> bool:
    """Prose that mentions a data sheet ("This datasheet supports the piping
    package."), not a heading: it ends in sentence punctuation, or most of its
    words are lower-case."""
    if text.rstrip().endswith((".", ";", ",")):
        return True
    words = [w for w in text.split() if len(w) >= 3 and w.isalpha()]
    return bool(words) and sum(w.islower() for w in words) * 2 > len(words)


def equipment_name(heading_line: str) -> str | None:
    """The equipment a heading names: its words without the "data sheet" words
    and without anything after "for" ("PUMP DATA SHEET FOR RECYCLE WATER" is a
    pump). One to five plain words, else None."""
    text = _DATA_AT_END.sub(" ", heading_line)
    text = re.sub(r"\([^)]*\)", " ", _DOCUMENT_WORDS.sub(" ", text))
    parts = re.split(r"\bfor\b", text, maxsplit=1, flags=re.I)
    text = (
        parts[0]
        if re.search(r"[A-Za-z]", parts[0])
        else (parts[1] if len(parts) > 1 else "")
    )
    words = _NAME_WORD.findall(text)
    if not words or len(words) > _MAX_NAME_WORDS or any(len(w) < 3 for w in words):
        return None
    if all(w.upper() in classification._DISCIPLINE_LABELS for w in words):
        return None  # "MECHANICAL DATASHEET" names a discipline, not equipment
    return " ".join(words).title()


def _now() -> str:
    from .classification import _now as stamp

    return stamp()


def fill(document_id: str) -> dict:
    """Write the heading as the title, and as the equipment type when that is
    still empty. Returns `{field: value}` for what was written (empty when
    nothing was). See the module note for the guards."""
    conn = connect()
    row = conn.execute(
        "SELECT document_role, confirmed_by, title, equipment_type, field_evidence"
        " FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if (
        row is None
        or row["document_role"] != "CONTRACTOR_SUBMITTAL"
        or row["confirmed_by"] is not None
    ):
        return {}
    if row["title"] and row["equipment_type"]:
        return {}
    pages = [
        dict(r)
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    found = heading(pages)
    if found is None:
        return {}
    page, line = found
    now = _now()
    written: dict = {}
    evidence = classification._load_evidence(row["field_evidence"])
    sets: list[str] = []
    values: list[object] = []
    if not row["title"]:
        evidence["title"] = {
            "value": line,
            "page": page,
            "quote": line,
            "pages": [page],
            "method": "datasheet_heading",
            "confidence": CONFIDENCE,
            "classifier_version": VERSION,
            "classified_at": now,
        }
        sets += ["title = ?", "field_evidence = ?"]
        values += [line, json.dumps(evidence)]
        written["title"] = line
    name = None if row["equipment_type"] else equipment_name(line)
    if name:
        sets += ["equipment_type = ?", "equipment_type_evidence = ?"]
        values += [
            name,
            json.dumps(
                {
                    "page": page,
                    "quote": line,
                    "method": "heading_phrase",
                    "confidence": CONFIDENCE,
                    "classifier_version": VERSION,
                    "classified_at": now,
                }
            ),
        ]
        written["equipment_type"] = name
    if not written:
        return {}
    with conn:
        conn.execute(
            f"UPDATE document_classification SET {', '.join(sets)} WHERE document_id = ?",
            [*values, document_id],
        )
    return written


def classify(document_id: str) -> dict:
    """The READY / role-change hook: the metadata classifier, then the heading fill."""
    classification.classify_metadata_for_submittal(document_id)
    return fill(document_id)


def for_review(document_id: str) -> dict:
    """At the start of a review: a submittal whose title, equipment type or
    discipline is still empty gets the same classifiers again, then the heading
    fill. Never raises: a failure is logged by type and the review goes on."""
    try:
        row = (
            connect()
            .execute(
                "SELECT document_role, title, equipment_type, discipline FROM document_classification"
                " WHERE document_id = ?",
                (document_id,),
            )
            .fetchone()
        )
        if row is None or row["document_role"] != "CONTRACTOR_SUBMITTAL":
            return {}
        if row["title"] and row["equipment_type"] and row["discipline"]:
            return {}
        classification.classify_equipment_type_for_submittal(document_id)
        classification.classify_metadata_for_submittal(document_id)
        return fill(document_id)
    except Exception as exc:  # noqa: BLE001 - logged by type; a review never fails on this
        _log.warning(
            "the submittal fields were not filled at review start (%s)",
            type(exc).__name__,
        )
        return {}
