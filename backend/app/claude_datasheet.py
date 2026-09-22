"""Reading a datasheet PAGE with the model as a proposer, Python as the gate.

WHY A MODEL AT ALL, when `datasheets.extract_facts` reads label/value pairs
deterministically. Because that extractor reads SHAPES - a ruled grid, or a
text block with a numbered label beside a value - and a contractor's datasheet
does not hold still. A value printed two cells to the right of its label, a
"Required / Offered" column pair, a test result written as a sentence under a
table: each is a field the deterministic path cannot pair and reports as
unparsed. The model is better at reading a page. It is not trusted to be
right, which is what `accept()` is for.

THE DIVISION OF LABOUR, AND IT IS NOT NEGOTIABLE. `reader_api.py` set the
rule for standards: the model PROPOSES, Python VERIFIES, and a proposal that
survives is one every field of which can be re-derived from the page by
something that cannot imagine. This module applies the same rule to the other
side of the comparison. The model reads ONE PAGE and proposes facts. Each
proposal carries a verbatim quote; the quote must be on the page, the value
must be inside the quote, the field must be inside the quote, and two runs of
the same page must agree. Anything else is thrown away WITH A NAMED REASON.

WHY A PAGE, when `reader_api` insists on one sentence. A datasheet is not
prose. Its unit of meaning is a row - a label and a value that are adjacent
on the page and nowhere near each other in the extracted text stream - and a
sentence splitter would separate exactly the two things a fact is made of.
The page-sized quote check is weaker than the sentence-sized one (a value can
appear on the page beside the wrong label), which is why the field-in-quote
rule exists here and not there: the quote must contain BOTH the label and the
value, so the model has to point at the row it read them from.

WHAT IS STORED IS MARKED AS THE MODEL'S. `store_facts` writes through
`datasheets.create_fact` with `extraction_method="model"` and `confidence=0.5`
(below the deterministic path's 0.6, and above nothing), and never overwrites
a fact the extractor already found for the same field on the same page. A
reader looking at a fact can always tell which path produced it, and the
deterministic one wins where the two disagree.

THE MODEL IS INJECTED AS A CALLABLE (prompt -> raw text), exactly as
`reader_api` and `extraction_llm` do. This module imports no HTTP client and
opens no socket - `tests/test_socket_containment.py` globs the package - and
every test in `test_claude_datasheet.py` runs against a fake model.
"""

from __future__ import annotations

import json
import re
from enum import Enum

from . import claims, datasheets, submittal_review
from .db import connect

# --------------------------------------------------------------- vocabulary

#: What a datasheet value IS. Three words, no more. A datasheet column pair
#: "Required / Offered" is the commonest place the deterministic extractor
#: loses a value, and the two numbers in it mean opposite things to a
#: reviewer: one is what the purchaser asked for, the other is what the vendor
#: says they will supply. A third kind, `measured`, is a test or inspection
#: result - a number about what was built, not what was asked for or offered.
KINDS = ("required", "offered", "measured")


class Reason(Enum):
    """Why a proposal was thrown away. A NAMED REASON, ALWAYS.

    `reader_api.Reason`'s rule, kept: a plain `Enum` whose members carry the
    stored string, and every caller uses `.value`. Silent discarding is the
    failure this enum exists to prevent - "the model found nothing" and "the
    model invented four things and we dropped them" are different facts about
    a datasheet.
    """

    #: The model's answer was not the JSON that was asked for. Call-level.
    MODEL_MALFORMED = "model_malformed"
    #: Rule 1. The quote does not appear on the page, whitespace-folded. The
    #: fabrication catch: an imagined row has no true quote.
    QUOTE_NOT_ON_PAGE = "quote_not_on_page"
    #: Rule 2. The value is not inside the words the model says it read it
    #: from.
    VALUE_NOT_IN_QUOTE = "value_not_in_quote"
    #: Rule 3. The field's label is not inside the quote either, so the model
    #: has not pointed at the row that pairs the two.
    FIELD_NOT_IN_QUOTE = "field_not_in_quote"
    FIELD_MISSING = "field_missing"
    VALUE_MISSING = "value_missing"
    KIND_UNKNOWN = "kind_unknown"
    #: A unit was given and `claims` has never heard of it. A null unit is
    #: fine - a categorical value has none - but a spelling no table knows is
    #: as likely a mis-read as a real unit, and cannot be compared either way.
    UNIT_UNRECOGNISED = "unit_unrecognised"
    #: The deterministic extractor already found this field on this page. The
    #: model was told to skip it; a proposal for it is not new evidence.
    ALREADY_EXTRACTED = "already_extracted"
    #: Rule 5. Two runs of the same page did not agree.
    MODEL_UNSTABLE = "model_unstable"


# ------------------------------------------------------------------- prompt

PROMPT = """You are reading ONE PAGE of an equipment datasheet submitted by a
contractor or vendor. A datasheet is a form: field labels with values beside
them, sometimes in "Required" and "Offered" columns, sometimes with test
results.

List the facts this page states, as JSON only:
{"facts": [{"field": ..., "value": ..., "unit": ..., "quote": ..., "kind": ...}]}

field is the label of the row, copied from the page - "Design pressure",
"Set pressure", "Casing material".

value is what is written beside that label: a number, a range, or a short
categorical answer ("Yes", "Carbon steel"). Copy it as printed. If the cell is
blank or says "By Vendor", do not report it.

unit is the unit printed with the value, or null when there is none.

kind is exactly one of:
  required - the value the purchaser or the specification DEMANDS: a
             "Required" column, a "Spec." column, a stated minimum.
  offered  - what the contractor or vendor PROPOSES to supply: an "Offered",
             "Vendor" or "Proposed" column, or the only value on a form the
             vendor filled in.
  measured - a TEST or INSPECTION result: a "Measured", "Test", "Actual" or
             "As built" column.
When a page has no such columns, the value is offered.

quote is the EXACT words on the page you read the field AND the value from,
copied character for character, in one span. Both the label and the value
must be inside the quote. Never write a quote that is not on the page.

"""

_KNOWN_FIELDS_PREFIX = """SKIP THESE FIELDS - they have already been read from this page:
"""


def build_prompt(page_text: str, page_no: int, known_fields: list[str]) -> str:
    """The prompt for one page. A function, not a format string at the call
    site, so the page text and the skip-list are appended in exactly one
    place.

    `known_fields` are the labels the deterministic extractor already paired
    on this page. The model is told to skip them because a second reading of
    a field the grid path found is not new evidence, and `accept()` refuses
    them anyway (`already_extracted`) - the prompt is the request, the gate is
    the enforcement.
    """
    parts = [PROMPT]
    if known_fields:
        parts.append(_KNOWN_FIELDS_PREFIX)
        parts.extend(f"  - {f}\n" for f in known_fields)
        parts.append("\n")
    parts.append("Answer with JSON and nothing else.\n\n")
    parts.append(f"PAGE {page_no}:\n")
    parts.append(page_text.strip())
    return "".join(parts)


# -------------------------------------------------------- text, folded

def _fold(text: str) -> str:
    """Whitespace-insensitive, case-insensitive form. `reader_api._fold`."""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _fold_numbers(text: str) -> str:
    return _THOUSANDS.sub("", _fold(text))


def _contains(haystack: str, needle: str) -> bool:
    """Whole-word containment on already-folded text. `reader_api._contains`,
    with the same lookarounds, for the same reason: "design pressure" must
    not be found inside "redesign pressure", and a unit can end in a bracket
    where `\\b` asks about the wrong character."""
    if not needle:
        return False
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def _value_in_quote(value, quote: str) -> bool:
    """Rule 2, tolerant of printing and of nothing else. "8,300" and "8300"
    are the same number; "23.55" and "99.9" are not."""
    quote_folded = _fold_numbers(quote)
    value_folded = _fold_numbers(value)
    if _contains(quote_folded, value_folded):
        return True
    try:
        wanted = float(value_folded)
    except ValueError:
        return False
    return any(float(found) == wanted for found in _NUMBER.findall(quote_folded))


#: Words in a field label that carry its meaning. Four letters or more, so
#: "of", "at", "the" and a unit abbreviation never satisfy the check alone.
_FIELD_WORD = re.compile(r"[a-z][a-z0-9]{3,}")


def _field_in_quote(field: str, quote: str) -> bool:
    """Rule 3, deliberately LENIENT.

    The label is checked by its NOUN, not by its spelling: the sheet writes
    "Design/Operating pressure (Note - 3)" and the model answers "Design
    pressure", and refusing that pair would throw away a true reading over
    punctuation. At least one word of four letters or more from the field must
    appear, whole, in the quote. A field with no such word - "Q", "dP" - is
    checked exactly instead, because there is nothing lenient to check.
    """
    quote_folded = _fold(quote)
    field_folded = _fold(field)
    words = _FIELD_WORD.findall(field_folded)
    if not words:
        return _contains(quote_folded, field_folded)
    return any(_contains(quote_folded, w) for w in words)


def _unit_recognised(unit: str) -> bool:
    """Either table in `claims` will do: a dimension, or a spelling the
    unconverted set knows. `ppm` has no dimension and is still a unit."""
    if claims.unit_dimension(unit) is not None:
        return True
    return claims.is_unit(unit)


# -------------------------------------------------------------------- parse

def parse_response(raw: str) -> tuple[list[dict], str | None]:
    """Strict parse. Anything malformed yields no proposals AND A REASON.

    Repairing half-JSON would be the module inventing content and calling it
    the model's. A bare object with a `field` key is accepted as one fact,
    because a page with one unread row gets answered that way often enough
    to be worth not losing.
    """
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [], Reason.MODEL_MALFORMED.value
    if isinstance(body, dict) and "facts" not in body and "field" in body:
        body = {"facts": [body]}
    facts = body.get("facts") if isinstance(body, dict) else None
    if not isinstance(facts, list):
        return [], Reason.MODEL_MALFORMED.value
    out = []
    for p in facts:
        if not isinstance(p, dict) or not p.get("quote"):
            # No quote names no words on the page: nothing to keep or count.
            continue
        out.append({
            "field": (str(p["field"]).strip()
                      if p.get("field") not in (None, "") else None),
            "value": (str(p["value"]).strip()
                      if p.get("value") not in (None, "") else None),
            "unit": (str(p["unit"]).strip()
                     if p.get("unit") not in (None, "") else None),
            "quote": str(p["quote"]),
            "kind": str(p.get("kind") or "").strip().lower(),
        })
    return out, None


# --------------------------------------------------------------- the gate

def _known_names(known_fields) -> set[str]:
    return {datasheets.normalise_field_name(f) for f in (known_fields or [])
            if datasheets.normalise_field_name(f)}


def accept(proposals: list[dict], page_text: str, known_fields: list[str] | None = None) -> dict:
    """THE GATE. A proposal is kept only when ALL of these hold:

      1. the quote appears on the page, whitespace-folded
      2. the value appears inside the quote
      3. the field's main word appears inside the quote
      4. the unit, when given, is one `claims` recognises
      5. the field is not one the deterministic extractor already found
      6. (in `read_page`) two runs of the page agreed

    Rules 1-3 are one idea in three places: EVERY FIELD MUST BE RE-DERIVABLE
    FROM THE PAGE BY SOMETHING THAT CANNOT IMAGINE. The order of the checks is
    the order of cheapness and of certainty: a missing field or value is
    known before any text is compared.

    Returns `{"accepted": [...], "rejected": [...], "counts": {reason: n}}`.
    Every rejected proposal carries `reason`. Every accepted one carries
    `field_name`, the normalised name `store_facts` and the duplicate check
    use, beside the label the model wrote.
    """
    folded_page = _fold(page_text)
    known = _known_names(known_fields)
    accepted: list[dict] = []
    rejected: list[dict] = []

    def drop(proposal: dict, reason: Reason) -> None:
        rejected.append({**proposal, "reason": reason.value})

    for p in proposals:
        if not p.get("field"):
            drop(p, Reason.FIELD_MISSING)
            continue
        if not p.get("value"):
            drop(p, Reason.VALUE_MISSING)
            continue
        if p.get("kind") not in KINDS:
            drop(p, Reason.KIND_UNKNOWN)
            continue
        quote = _fold(p["quote"])
        if not quote or not _contains(folded_page, quote):
            drop(p, Reason.QUOTE_NOT_ON_PAGE)
            continue
        if not _value_in_quote(p["value"], quote):
            drop(p, Reason.VALUE_NOT_IN_QUOTE)
            continue
        if not _field_in_quote(p["field"], quote):
            drop(p, Reason.FIELD_NOT_IN_QUOTE)
            continue
        if p.get("unit") and not _unit_recognised(p["unit"]):
            drop(p, Reason.UNIT_UNRECOGNISED)
            continue
        field_name = datasheets.normalise_field_name(p["field"])
        if field_name in known:
            drop(p, Reason.ALREADY_EXTRACTED)
            continue
        accepted.append({**p, "field_name": field_name})
    return {"accepted": accepted, "rejected": rejected,
            "counts": rejection_counts(rejected)}


def rejection_counts(rejected: list[dict]) -> dict:
    """`{reason: n}`, so a caller can write "12 proposals rejected: 3
    quote-not-on-page, 1 value-not-in-quote"."""
    counts: dict = {}
    for r in rejected:
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    return counts


# ------------------------------------------------------------ the two runs

def _identity(p: dict) -> tuple:
    """What two runs must agree ON: the normalised field, the number as
    printed, the unit. Not the quote - two runs quoting the same row with
    different amounts of surrounding text agree about the sheet - and not the
    kind, which the second run may name differently for a column it read
    identically; a kind disagreement is a labelling question, not evidence
    the row is imagined."""
    return (
        datasheets.normalise_field_name(p.get("field") or ""),
        _fold_numbers(p.get("value") or ""),
        _fold(p.get("unit") or ""),
    )


def read_page(page_text: str, page_no: int, known_fields: list[str] | None,
              model_call, second_call=None) -> dict:
    """One page through the model TWICE and then through the gate.

    RULE 6, AND IT IS NOT OPTIONAL. `second_call` defaults to calling the
    same model again rather than to skipping the check: a fact only one run
    produced is a fact the page does not compel. An unstable proposal is
    REPORTED with `model_unstable`, never dropped quietly.

    Returns the `accept()` shape plus `page`, and `error` when a run's answer
    was not JSON.
    """
    known_fields = list(known_fields or [])
    prompt = build_prompt(page_text, page_no, known_fields)
    first, err = parse_response(model_call(prompt))
    if err:
        return {"page": page_no, "accepted": [], "rejected": [], "counts": {}, "error": err}
    again = second_call if second_call is not None else model_call
    second, err2 = parse_response(again(prompt))
    if err2:
        return {"page": page_no, "accepted": [], "rejected": [], "counts": {}, "error": err2}
    seen = {_identity(p) for p in second}
    stable = [p for p in first if _identity(p) in seen]
    unstable = [{**p, "reason": Reason.MODEL_UNSTABLE.value}
                for p in first if _identity(p) not in seen]
    gate = accept(stable, page_text, known_fields)
    gate["rejected"].extend(unstable)
    gate["counts"] = rejection_counts(gate["rejected"])
    gate["page"] = page_no
    return gate


# ------------------------------------------------------- the stored document

def _page_chunks(document_id: str, allowed_document_ids: frozenset[str]) -> dict[int, list]:
    """`{page_no: [chunk rows]}` for a stored document, keyed by EVERY page a
    chunk covers - `extract_facts`'s rule, so a page enclosed by a multi-page
    chunk is still a page."""
    submittal_review.ensure_schema()
    where, args = datasheets._scope_clause(allowed_document_ids, "document_id")
    chunks = connect().execute(
        "SELECT c.id, c.page_start, c.page_end, c.text, d.stored_path"
        " FROM chunks c JOIN documents d ON d.id = c.document_id" + where +
        " AND c.document_id = ? AND c.retrievable = 1 ORDER BY c.ordinal",
        [*args, document_id],
    ).fetchall()
    by_page: dict[int, list] = {}
    for chunk in chunks:
        for page_no in range(chunk["page_start"], (chunk["page_end"] or chunk["page_start"]) + 1):
            by_page.setdefault(page_no, []).append(chunk)
    return by_page


def _pdf_page_text(stored_path: str, page_no: int) -> str:
    """The page's text straight from the PDF, as `extract.extract_batch` reads
    it. Only reached when the stored chunks carry no text for the page."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return ""
    try:
        with pymupdf.open(stored_path) as doc:
            if not (1 <= page_no <= doc.page_count):
                return ""
            return doc[page_no - 1].get_text("text") or ""
    except Exception:  # noqa: BLE001 - an unreadable page has no text
        return ""


def stored_page_text(document_id: str, page_no: int, *, allowed_document_ids: frozenset[str]) -> str:
    """One page's text from the stored document.

    THE CHUNK TEXT FIRST, THE PDF SECOND. There is no page-text accessor in
    the package - `extract_facts` reads pairs from the PDF and the corpus from
    `chunks.text` - so this reads what ingestion stored: the text of every
    retrievable chunk covering the page, which is what the rest of the system
    cites. The PDF is opened only when those chunks carry nothing, which is a
    scanned page before OCR, and then it usually says nothing either.
    """
    by_page = _page_chunks(document_id, allowed_document_ids)
    chunks = by_page.get(page_no) or []
    text = "\n".join((c["text"] or "") for c in chunks).strip()
    if text:
        return text
    if chunks:
        return _pdf_page_text(chunks[0]["stored_path"], page_no)
    return ""


def read_datasheet(document_id: str, *, allowed_document_ids: frozenset[str],
                   model_call, second_call=None, page_text_of=None,
                   pages=None) -> dict:
    """Every page of a stored datasheet through `read_page`.

    `known_fields` per page come from `datasheets.list_facts` - what the
    deterministic extractor has already recorded - so the model is asked
    only about what was missed. `page_text_of(page_no) -> str` is injectable
    for tests and defaults to `stored_page_text`; `pages` restricts the run.

    Returns `{"document_id", "pages": [per-page read_page results],
    "accepted", "rejected", "counts", "errors"}`. Accepted and rejected
    proposals carry `page`, because a reason without the page it belongs to
    cannot be acted on.
    """
    by_page = _page_chunks(document_id, allowed_document_ids)
    if pages is None:
        pages = sorted(by_page)
    if page_text_of is None:
        def page_text_of(page_no: int) -> str:
            return stored_page_text(document_id, page_no,
                                    allowed_document_ids=allowed_document_ids)
    known_by_page: dict[int, list[str]] = {}
    for fact in datasheets.list_facts(document_id, allowed_document_ids=allowed_document_ids):
        known_by_page.setdefault(fact["page"], []).append(
            fact.get("field_label") or fact["field_name"])

    per_page: list[dict] = []
    accepted: list[dict] = []
    rejected: list[dict] = []
    errors: list[dict] = []
    for page_no in pages:
        text = page_text_of(page_no) or ""
        if not text.strip():
            per_page.append({"page": page_no, "accepted": [], "rejected": [],
                             "counts": {}, "skipped": "no text"})
            continue
        out = read_page(text, page_no, known_by_page.get(page_no, []),
                        model_call, second_call)
        per_page.append({"page": page_no, "accepted": len(out["accepted"]),
                         "rejected": len(out["rejected"]), "counts": out["counts"],
                         **({"error": out["error"]} if out.get("error") else {})})
        if out.get("error"):
            errors.append({"page": page_no, "error": out["error"]})
            continue
        accepted.extend({**p, "page": page_no} for p in out["accepted"])
        rejected.extend({**p, "page": page_no} for p in out["rejected"])
    return {"document_id": document_id, "pages": per_page,
            "accepted": accepted, "rejected": rejected,
            "counts": rejection_counts(rejected),
            "rejection_counts": rejection_counts(rejected), "errors": errors}


# ---------------------------------------------------------------- storage

#: Written into `extraction_method`, so a stored fact always says which path
#: produced it. The deterministic path writes "extracted".
EXTRACTION_METHOD = "model"
#: Below the deterministic path's 0.6: a model proposal that passed the gate
#: is evidence, and less of it than a pair the grid read directly.
CONFIDENCE = 0.5


def store_facts(review_run_id: str | None, document_id: str, accepted: list[dict], *,
                allowed_document_ids: frozenset[str]) -> dict:
    """Record accepted proposals through `datasheets.create_fact`.

    MARKED AS THE MODEL'S. `extraction_method="model"`, `confidence=0.5`,
    `source_text` is the quote, `page` is the page the proposal came from.
    THE KIND GOES IN `section` AS `model:<kind>`: `submittal_facts` has no
    column for who a value belongs to (required / offered / measured) and this
    task may not add one; `section` is free text the deterministic path fills
    with a heading, and a prefix nobody else writes is recoverable by
    anything that needs it later.

    NEVER OVERWRITES. A fact with the same normalised field on the same page
    - the extractor's or an earlier model run's - is kept and the proposal is
    reported under `kept_existing`. The deterministic path wins where the two
    disagree, because it can be re-run and the model cannot be argued with.

    Each accepted proposal must carry `page`; `read_datasheet` stamps it.
    Returns `{"written", "kept_existing", "refused", "facts": [rows]}`.
    """
    by_page = _page_chunks(document_id, allowed_document_ids)
    existing = {
        (fact["page"], fact["field_name"])
        for fact in datasheets.list_facts(document_id, allowed_document_ids=allowed_document_ids)
    }
    written: list[dict] = []
    kept_existing: list[dict] = []
    refused: list[dict] = []
    for p in accepted:
        page = p.get("page")
        field_name = p.get("field_name") or datasheets.normalise_field_name(p["field"])
        if (page, field_name) in existing:
            kept_existing.append(p)
            continue
        chunks = by_page.get(page) or []
        if not chunks:
            refused.append({**p, "reason": "no chunk covers this page"})
            continue
        raw_value = p["value"] if not p.get("unit") else f"{p['value']} {p['unit']}"
        try:
            row = datasheets.create_fact(
                submittal_document_id=document_id, chunk_id=chunks[0]["id"],
                field_label=p["field"], raw_value=raw_value, page=page,
                section=f"model:{p['kind']}", source_text=p["quote"],
                review_run_id=review_run_id, confidence=CONFIDENCE,
                extraction_method=EXTRACTION_METHOD,
            )
        except datasheets.FactError as exc:
            refused.append({**p, "reason": str(exc)})
            continue
        existing.add((page, field_name))
        written.append(row)
    return {"written": len(written), "kept_existing": len(kept_existing),
            "refused": refused, "facts": written}


__all__ = [
    "CONFIDENCE",
    "EXTRACTION_METHOD",
    "KINDS",
    "PROMPT",
    "Reason",
    "accept",
    "build_prompt",
    "parse_response",
    "read_datasheet",
    "read_page",
    "rejection_counts",
    "store_facts",
    "stored_page_text",
]
