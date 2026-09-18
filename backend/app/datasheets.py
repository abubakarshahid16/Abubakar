"""Phase 4: reading a contractor datasheet into facts.

WHICH EXTRACTION PATH, AND WHY - DECIDED BY MEASURING, NOT BY HOPE

Step zero of this phase was to ingest the two real KOC datasheets and measure
what `tables.py` actually recovers from them. The answer was different for each,
and that is the whole design:

  EF1975-DAS-M-03 (centrifugal pump, 7 pages) - `find_tables()` recovers a real
  grid on 7 of 7 pages, and reading it shows genuine data:

      ['VAPOR PRESSURE:', 'bar a (psia)', '0.42 (6.09)']
      ['SPECIFIC GRAVITY:', '0.974 @ 170 OF']

  EF1975-DAS-I-06 (pressure safety valves, 5 pages) - `find_tables()` reports a
  table on 5 of 5 pages too, and the rate is MEANINGLESS: every one of them is
  the two-row title block. The actual PSV data is not in it at all.

That second result is the one that mattered. Counting "pages with a table" would
have reported 100% for a datasheet whose every value was missed - the same
mistake phase 3B made and recorded as honesty-audit entry 14. The content was
read before the rate was believed.

What I-06's data is actually in is TEXT BLOCKS with a numbered label-value
shape, which is what master plan section 10 asks to preserve:

    5 | Design/Operating pressure | 23.5 / 9 barg (Note - 3) | 46 | ...
    8 | Set pressure | 340 psig (By Contractor, as per Code) | 49 | ...

So this module runs BOTH paths and neither is a fallback for the other:
the grid path where a grid exists, and coordinate-ordered label-value pairing
over text blocks where it does not. A form is not a table and forcing it
through a table parser would have produced nothing while reporting success.

`tables.py` is not duplicated - it is imported and used as the grid path.
`claims.py` is not duplicated - it does every unit.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from . import claims, submittal_review, tables
from .db import connect

#: Where a datasheet says a value is not filled in yet.
#:
#: These are MISSING INFORMATION, NEVER NON-COMPLIANCE. A form that says "By
#: Contractor" is telling you whose job it is, not that the equipment fails
#: anything, and a blank recorded as 0 would become a spurious finding against
#: a vendor who has not been asked yet.
#:
#: Taken verbatim from the two real datasheets, which write it several ways -
#: "By Contractor /Vendor", "By Contractor / Vendor", "(By Contractor, as per
#: Code)" - so the pattern is deliberately loose about the separator.
_BLANK_MARKERS = re.compile(
    r"\b(?:by\s+(?:the\s+)?(?:contractor|vendor|supplier|manufacturer)"
    r"(?:\s*/\s*(?:vendor|contractor|supplier))?"
    r"|to\s+be\s+(?:advised|confirmed|determined)|tba|tbc|tbd)\b",
    re.IGNORECASE,
)

#: A cell holding nothing but placeholder rules - "_______", "****", "---".
#: A form draws them where a value goes, and they are blanks, not values.
_PLACEHOLDER = re.compile(r"^[\s_\-*.·–—]{2,}$")

#: A referenced standard named inside a datasheet. Both real KOC sheets name a
#: stack of them, and phase 5 needs to know which standards a submittal itself
#: invokes. Spellings vary by vendor, so each family is matched on its own
#: shape rather than by one loose pattern that would also match a tag number.
_REFERENCED_STANDARD = re.compile(
    r"\b("
    r"API\s*(?:RP\s*)?\d{3}(?:\s*Pt[-\s]?\d)?"
    r"|KOC-[A-Z]{2}-\d{3}(?:\s*Pt[-\s]?\d)?"
    r"|NACE\s*MR[-\s]?\d{4}"
    r"|ISO\s*\d{4,5}"
    r"|ASME\s*[IVXB]+(?:\.\d+)?"
    r"|ASTM\s*[A-Z]\d{1,4}"
    r"|IEC\s*\d{5}"
    r"|SAES-[A-Z]-\d{3}"
    r"|EN\s*\d{3,5}"
    r")\b",
    re.IGNORECASE,
)

#: A label-value row in a numbered form: "5 | Design pressure | 23.5 barg".
#: The leading number is the sheet's own line number, not data.
_NUMBERED_LABEL = re.compile(r"^\s*(?P<no>\d{1,3})\s*[|.\)]?\s*(?P<rest>\S.*)$")

#: A value with a unit at the end: "9970 Kg/hr", "23.5 barg", "0.42 (6.09)".
_VALUE_UNIT = re.compile(
    r"^(?P<value>[-+]?\d[\d.,]*)\s*(?P<unit>[A-Za-z%µμ°][A-Za-z0-9/%µμ°.\-]{0,12})?"
)

#: A cell that is nothing but a number - "340", "0.892". Used to decide
#: whether trailing letters were a unit or the start of prose.
_BARE_NUMBER = re.compile(r"[-+]?\d[\d.,]*")

def is_field_label(text: str) -> bool:
    """True when `text` can be a FIELD LABEL rather than a value.

    THIS EXISTS BECAUSE THE FIRST VERSION INVENTED 427 FACTS. Running the
    extractor over the real PSV sheet produced rows whose "label" was
    `0.01cP By Contractor` and `10-05-497 & 556-05-512` - values and drawing
    numbers promoted into labels by a pairing that walked off the end of a
    block - and whose value was empty, so every one of them was then recorded
    as a required field left blank. 439 facts from a five-page sheet, 427 of
    them blank, is not extraction; it is noise with a schema.

    A label names something. So it must contain real words, must not itself
    parse as a measurement, and must not be mostly digits.
    """
    candidate = (text or "").strip()
    if len(candidate) < 3 or len(candidate) > 80:
        return False
    letters = sum(1 for ch in candidate if ch.isalpha())
    if letters < 3:
        return False
    # A cell that reads as a quantity is a value, whatever position it landed
    # in. `measure_value` is the authority, so there is one definition of
    # "this is a number" in this module rather than two that can drift.
    if measure_value(candidate)[0] is not None:
        return False
    # "10-05-497 & 556-05-512" is a drawing reference: more digits than letters.
    digits = sum(1 for ch in candidate if ch.isdigit())
    if digits > letters:
        return False
    # A blank marker is what a value says, never what a field is called.
    return not _BLANK_MARKERS.search(candidate)


#: Label text that is a section heading rather than a field.
_HEADING_WORDS = frozenset({
    "process data", "spring and bonnet", "accessories", "general",
    "liquid characteristics", "materials", "notes", "remarks",
})


def normalise_field_name(label: str) -> str:
    """A field label reduced to a comparable name.

    Lowercased, punctuation dropped, whitespace collapsed, and the sheet's
    trailing clause references removed - "Design/Operating pressure (Note - 3)"
    and "DESIGN / OPERATING PRESSURE:" are the same field asked twice.

    THE ORIGINAL LABEL IS KEPT BESIDE THIS, always. A normalised name is for
    matching; the reader is shown what the document actually wrote.
    """
    text = re.sub(r"\((?:note|see|ref)[^)]*\)", " ", label or "", flags=re.IGNORECASE)
    text = re.sub(r"[^\w\s/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def is_blank_value(value: str | None) -> tuple[bool, str | None]:
    """`(is_blank, marker)`. A blank is recorded as blank, never as 0.

    Three ways a datasheet says "not filled in": an empty cell, a rule of
    underscores or asterisks where the value goes, and an explicit
    "By Contractor / Vendor". All three are MISSING INFORMATION.
    """
    text = (value or "").strip()
    if not text:
        return True, "empty"
    if _PLACEHOLDER.match(text):
        return True, "placeholder"
    marker = _BLANK_MARKERS.search(text)
    if marker:
        # "217C By Contractor /Vendor" carries a number AND the marker. It is
        # still blank: the number is a provisional process figure and the sheet
        # is saying the vendor has to confirm it. Treating it as a filled value
        # would compare a placeholder against a standard.
        return True, marker.group(0).strip()
    return False, None


def referenced_standards(text: str) -> list[str]:
    """Standards named in the datasheet text, de-duplicated, in order found.

    Spacing is normalised so "API RP 520" and "API  RP520" are one entry, but
    the document's own spelling of each family is kept - this is a citation,
    and a citation is quoted rather than canonicalised.
    """
    seen: dict[str, str] = {}
    for match in _REFERENCED_STANDARD.finditer(text or ""):
        raw = " ".join(match.group(1).split())
        key = raw.upper().replace(" ", "")
        seen.setdefault(key, raw)
    return list(seen.values())


def split_label_value(cells: list[str]) -> list[tuple[str, str]]:
    """Label-value pairs out of one row of a form.

    A KOC sheet is TWO FORMS SIDE BY SIDE - "5 | Design pressure | 23.5 barg |
    46 | Bonnet material | CS" - so a row yields more than one pair and the
    leading line numbers are dropped. Pairing is strictly left to right, which
    is the order the sheet is read in.
    """
    parts = [c.strip() for c in cells if c is not None]
    pairs: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        # A bare line number introduces the pair that follows it.
        if re.fullmatch(r"\d{1,3}", part):
            index += 1
            continue
        if not part:
            index += 1
            continue
        label = part
        value = parts[index + 1] if index + 1 < len(parts) else ""
        if re.fullmatch(r"\d{1,3}", value):
            # The next cell is the NEXT pair's line number, so this label has
            # no value on the sheet - which is a blank, not a missing row.
            value = ""
            index += 1
        else:
            index += 2
        if normalise_field_name(label) in _HEADING_WORDS:
            continue
        # THE LABEL MUST BE A LABEL. See is_field_label: without this the
        # pairing promotes values and drawing numbers into field names and
        # then records each one as a required field left blank.
        if not is_field_label(label):
            continue
        pairs.append((label, value))
    return pairs


def pairs_from_blocks(page_text_blocks: list[tuple[float, float, str]]) -> list[tuple[str, str]]:
    """Label-value pairs from a form's TEXT BLOCKS, in reading order.

    THE PATH FOR A FORM THAT HAS NO GRID. Sorted by y then x, which is reading
    order on a page whose structure is visual rather than ruled - master plan
    section 10's "preserve text blocks and coordinates".

    Each block on these sheets is one row with its cells separated by newlines,
    which is what `split_label_value` consumes.
    """
    out: list[tuple[str, str]] = []
    for _y, _x, text in sorted(page_text_blocks, key=lambda b: (round(b[0], 1), b[1])):
        cells = [c.strip() for c in (text or "").split("\n") if c.strip()]
        if len(cells) < 2:
            continue
        match = _NUMBERED_LABEL.match(cells[0])
        if match and re.fullmatch(r"\d{1,3}", cells[0].strip()):
            cells = cells[1:]
        out.extend(split_label_value(cells))
    return out


def measure_value(raw: str) -> tuple[str | None, str | None, claims.Measurement | None]:
    """`(value, unit, measurement)` out of a datasheet cell.

    The unit handling is `claims.normalise` and nothing else. An unknown unit
    leaves `normalized_value` None - never 0 - and the raw spelling is kept, so
    `340 psig` and `9970 Kg/hr` are both recorded exactly as written whether or
    not this system can convert them.
    """
    text = (raw or "").strip()
    if not text:
        return None, None, None
    match = _VALUE_UNIT.match(text)
    if not match:
        return None, None, None
    value = match.group("value")
    unit = (match.group("unit") or "").strip() or None

    # A MEASUREMENT ENDS WHERE IT ENDS. PROSE AFTER IT MEANS IT WAS NEVER ONE.
    #
    # Both defects this guards against were found by running this function over
    # the real sheet, not imagined:
    #
    #   "2nd Stage Desalter"      -> value 2, unit "nd"   - a location
    #   "10-05-498 & 556-05-513"  -> value 10             - a P&ID number
    #
    # The discriminator is NOT whether the unit is recognised. Using the unit
    # table for this dropped "9970 Kg/hr", which is a real value whose compound
    # unit simply is not in `claims` - and dropping it would break the rule
    # that an unknown unit yields None rather than losing the number.
    #
    # What actually separates them is what FOLLOWS. A measurement is the whole
    # cell, give or take a parenthetical alternate that datasheets use for
    # dual units - "0.42 (6.09)" is bar and psia. Words after the number mean
    # the cell was a sentence that happened to start with a digit.
    remainder = text[match.end():].strip()
    if remainder and not remainder.startswith("("):
        return None, None, None
    return value, unit, claims.normalise(value, unit or "")


# ------------------------------------------------------------ persistence


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _scope_clause(allowed_document_ids: frozenset[str], column: str) -> tuple[str, list[str]]:
    """`submittal_review._scope_clause`'s rule, restated for this module."""
    if not allowed_document_ids:
        return " WHERE 1 = 0", []
    marks = ",".join("?" for _ in allowed_document_ids)
    return f" WHERE {column} IN ({marks})", sorted(allowed_document_ids)


class FactError(ValueError):
    """A fact could not be recorded. Carries a reason, never a row."""


def create_fact(
    *, submittal_document_id: str, chunk_id: str, field_label: str,
    raw_value: str | None, page: int | None, section: str | None = None,
    source_text: str | None = None, review_run_id: str | None = None,
    confidence: float | None = None, extraction_method: str = "extracted",
) -> dict:
    """Record one fact. REFUSES a fact whose citation does not resolve.

    The same three checks `standards.create_requirement` makes, for the same
    reasons: a fact without a resolving chunk is an assertion, a chunk from
    another document is a citation that opens the wrong page, and a page
    outside the chunk is a citation that opens the right document in the wrong
    place.

    A BLANK IS RECORDED AS A FACT, not skipped. "Set pressure: By Contractor"
    is information - it says the field exists, is required, and is not filled
    in - and skipping it would make a missing value indistinguishable from a
    field the sheet never asked for.
    """
    submittal_review.ensure_schema()
    chunk = connect().execute(
        "SELECT id, document_id, page_start, page_end FROM chunks WHERE id = ?",
        (chunk_id,)).fetchone()
    if chunk is None:
        raise FactError(f"no chunk {chunk_id!r}: the citation does not resolve")
    if chunk["document_id"] != submittal_document_id:
        raise FactError("the cited chunk belongs to a different document")
    if page is not None and not (chunk["page_start"] <= page <= chunk["page_end"]):
        raise FactError(f"page {page} is outside the cited chunk")

    blank, marker = is_blank_value(raw_value)
    value, unit, measurement = (None, None, None) if blank else measure_value(raw_value or "")
    now = _now()
    row = {
        "id": str(uuid.uuid4()),
        "review_run_id": review_run_id,
        "submittal_document_id": submittal_document_id,
        "chunk_id": chunk_id,
        "field_name": normalise_field_name(field_label),
        "field_label": field_label,
        "field_value": (raw_value or "").strip() or None,
        "raw_value": value,
        "raw_unit": unit,
        "normalized_value": measurement.normalized_value if measurement else None,
        "normalized_unit": measurement.normalized_unit if measurement else None,
        "unit": unit,
        "is_blank": 1 if blank else 0,
        "blank_marker": marker,
        "page": page if page is not None else chunk["page_start"],
        "section": section,
        "source_text": source_text or (raw_value or ""),
        "extraction_method": extraction_method,
        "confidence": confidence,
        "created_at": now,
        "updated_at": now,
    }
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO submittal_facts
               (id, review_run_id, submittal_document_id, chunk_id, field_name,
                field_label, field_value, raw_value, raw_unit,
                normalized_value, normalized_unit, unit, is_blank,
                blank_marker, page, section, source_text, extraction_method,
                confidence, created_at, updated_at)
               VALUES (:id, :review_run_id, :submittal_document_id, :chunk_id,
                       :field_name, :field_label, :field_value, :raw_value,
                       :raw_unit, :normalized_value, :normalized_unit, :unit,
                       :is_blank, :blank_marker, :page, :section, :source_text,
                       :extraction_method, :confidence, :created_at,
                       :updated_at)""", row)
    return row


def _pairs_from_pdf_page(stored_path: str, page_no: int) -> list[tuple[str, str]]:
    """Text-block label-value pairs for one page, in reading order."""
    try:
        import fitz
    except ImportError:  # pragma: no cover
        return []
    try:
        with fitz.open(stored_path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return []
            blocks = [(b[1], b[0], b[4]) for b in doc[page_no - 1].get_text("blocks")]
            return pairs_from_blocks(blocks)
    except Exception:  # noqa: BLE001 - an unreadable page yields no pairs
        return []


def extract_facts(
    document_id: str, *, allowed_document_ids: frozenset[str],
    review_run_id: str | None = None, replace: bool = True,
) -> dict:
    """Read one datasheet into facts, by whichever path its pages support.

    BOTH PATHS RUN, and neither is a fallback for the other: the grid path for
    pages `tables.py` can parse, and the text-block path for pages it cannot -
    which on the real PSV sheet is every page that matters.

    FACTS ARE PER DOCUMENT AND REUSED ACROSS RUNS (master plan section 24,
    "reuse cached extraction"). `review_run_id` records which run first
    produced them and is nullable, so a second review of the same datasheet
    does not re-read the PDF.

    A page that yields nothing is reported as unparsed WITH A REASON and lowers
    completeness. Nothing is invented from a page that could not be read.
    """
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "document_id")
    chunks = connect().execute(
        "SELECT c.id, c.page_start, c.page_end, c.section, c.kind, c.text,"
        "       d.stored_path"
        " FROM chunks c JOIN documents d ON d.id = c.document_id" + where +
        " AND c.document_id = ? AND c.retrievable = 1 ORDER BY c.ordinal",
        [*args, document_id],
    ).fetchall()
    empty = {"document_id": document_id, "facts": 0, "blanks": 0,
             "pages_read": 0, "pages_unparsed": 0, "parsed_fraction": None,
             "referenced_standards": [], "unparsed": []}
    if not chunks:
        return empty

    if replace:
        conn = connect()
        with conn:
            conn.execute(
                "DELETE FROM submittal_facts"
                " WHERE submittal_document_id = ? AND confirmed_by IS NULL",
                (document_id,))

    stored_path = chunks[0]["stored_path"]
    by_page: dict[int, list] = {}
    for chunk in chunks:
        by_page.setdefault(chunk["page_start"], []).append(chunk)

    written = blanks = 0
    unparsed: list[dict] = []
    corpus_text: list[str] = []

    for page, page_chunks in sorted(by_page.items()):
        pairs: list[tuple[str, str]] = []
        for shape in tables.parse_page_tables(stored_path, page):
            for row in shape:
                pairs.extend(split_label_value(list(row)))
        pairs.extend(_pairs_from_pdf_page(stored_path, page))

        chunk = page_chunks[0]
        corpus_text.extend(c["text"] or "" for c in page_chunks)
        page_written = 0
        seen: set[str] = set()
        for label, value in pairs:
            key = f"{normalise_field_name(label)}|{(value or '').strip()}"
            if not label.strip() or key in seen:
                continue
            seen.add(key)
            blank, marker = is_blank_value(value)
            parsed_value, _unit, _measure = measure_value(value or "")
            # WHAT COUNTS AS A FACT. This is the line that stops the
            # extractor inventing them.
            #
            # A fact is recorded only where the sheet actually says
            # something: a value that parses as a quantity, or a value the
            # sheet EXPLICITLY marks as the contractor's to fill - "By
            # Contractor", "TBA", a drawn rule of underscores.
            #
            # AN EMPTY ADJACENT CELL IS NOT EVIDENCE OF ANYTHING. Measured
            # on the real PSV sheet, treating it as a blank required field
            # produced 375 phantom blanks out of 387 rows: every stray text
            # block became a field somebody had failed to fill in. An empty
            # cell beside a label is a pairing artefact of a two-column
            # form, not a statement by the document, and recording it
            # manufactures findings against a vendor who was never asked.
            if parsed_value is None and marker in (None, "empty"):
                continue
            try:
                create_fact(
                    submittal_document_id=document_id, chunk_id=chunk["id"],
                    field_label=label.strip(), raw_value=value, page=page,
                    section=chunk["section"], review_run_id=review_run_id,
                    confidence=0.6,
                )
            except FactError:
                continue
            page_written += 1
            written += 1
            if blank:
                blanks += 1
        if page_written == 0:
            unparsed.append({
                "page": page,
                "reason": "no label-value pairs recovered from this page",
            })

    pages_read = len(by_page)
    return {
        "document_id": document_id,
        "facts": written,
        "blanks": blanks,
        "pages_read": pages_read,
        "pages_unparsed": len(unparsed),
        "parsed_fraction": (round((pages_read - len(unparsed)) / pages_read, 3)
                            if pages_read else None),
        "unparsed": unparsed,
        "referenced_standards": referenced_standards(" ".join(corpus_text)),
    }


def list_facts(document_id: str, *, allowed_document_ids: frozenset[str],
               blanks_only: bool = False) -> list[dict]:
    """One datasheet's facts, under the caller's grants, joined to their chunk."""
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "f.submittal_document_id")
    sql = ("SELECT f.*, c.page_start AS chunk_page FROM submittal_facts f"
           " LEFT JOIN chunks c ON c.id = f.chunk_id" + where +
           " AND f.submittal_document_id = ?")
    params = [*args, document_id]
    if blanks_only:
        sql += " AND f.is_blank = 1"
    sql += " ORDER BY f.page, f.field_name"
    return [{**dict(r), "citation_resolves": r["chunk_page"] is not None}
            for r in connect().execute(sql, params).fetchall()]
