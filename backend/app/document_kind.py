"""#1474: the KIND of a document (datasheet, procedure, specification, ...).

Moved out of classification.py, which only calls into it. Reads only the title
block and cover; no model, no network.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .classification import (
    _SPACE,
    _now,
    suggest_equipment_type_from_title,
    title_block_lines,
)
from .db import connect

# ------------------------------------------------------- document kind (#1474)
#
# WHAT KIND OF DOCUMENT IS THIS, decided from how the document NAMES ITSELF:
# the number in its title block (the type code inside it), its title and cover
# headings. NEVER from a body-text mention of equipment: a procedure that talks
# about relief valves is a procedure (the defect this fixes: a HAZOP procedure
# classified as a pressure safety valve, its Word copy as a compressor).
#
# Behind `settings.document_kind_enabled`, OFF by default. No model call: the AI
# may later give a second opinion, it does not decide here. A kind found from a
# cue is stored WITH its quote and page; a guess says it is a guess; a document
# no cue names is `unknown` (general review) and is counted, never hidden.

DOCUMENT_KIND_CLASSIFIER_VERSION = "document-kind-v1"

#: The vocabulary. `unknown` is a real answer: general review, marked.
DOCUMENT_KINDS: tuple[str, ...] = (
    "datasheet", "procedure", "specification", "transmittal", "contract",
    "drawing", "feed", "standard", "unknown")

#: Type codes a document number carries ("<project>-<area>-SP-<serial>"). Read
#: only inside a line that is a document number, and only when a serial number
#: follows the code.
_NUMBER_TYPE_CODES: dict[str, str] = {
    "SP": "specification", "SPC": "specification", "SPEC": "specification",
    "PD": "procedure", "PRC": "procedure", "PRO": "procedure", "PROC": "procedure",
    "DS": "datasheet", "DTS": "datasheet", "DSH": "datasheet",
    "DW": "drawing", "DWG": "drawing",
    "TR": "transmittal", "TRN": "transmittal", "TRM": "transmittal",
    "CT": "contract", "CTR": "contract",
}
_NUMBER_LABEL = re.compile(
    r"\b(?:doc(?:ument)?\.?\s*(?:no|num(?:ber)?)|drawing\s*no|document\s*ref)\b", re.I)
_BARE_NUMBER = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+){3,}$")

#: Title cues, in priority order within ONE line. A line is a title/cover line
#: when it is short and is not a "Label: value" line (a label naming a standard
#: or a specification is a reference, not what the document is).
_KIND_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("procedure", re.compile(r"\bprocedures?\b|\bmethod\s+statement\b|\bwork\s+instruction\b", re.I)),
    ("transmittal", re.compile(r"\btransmittals?\b", re.I)),
    ("contract", re.compile(
        r"\bschedule\s+[\"“”]\s*[A-Z0-9]{1,3}\s*[\"“”]"
        r"|\b(?:agreement|general\s+conditions|terms\s+and\s+conditions"
        r"|conditions\s+of\s+contract)\b", re.I)),
    ("specification", re.compile(r"\bspecifications?\b", re.I)),
    ("drawing", re.compile(
        r"\bdrawings?\b|\bp\s?&\s?ids?\b|\bpiping\s+and\s+instrument\w*\s+diagram"
        r"|\bsingle[- ]line\s+diagram\b|\bgeneral\s+arrangement\b|\bisometric\b", re.I)),
    ("feed", re.compile(r"\bFEED\b|(?i:\bfront[- ]end\s+engineering\s+design\b)")),
    ("datasheet", re.compile(r"\bdata\s?sheets?\b", re.I)),
)
_STANDARD_LINE = re.compile(
    r"^(?:SAES|SAEP|SAIC|ISO|IEC|API|ASME|ASTM|NORSOK|NFPA|IEEE|BS|DIN|EN)"
    r"[-\s]?[A-Z]{0,3}[-\s]?\d", re.I)
_STANDARD_WORDS = re.compile(r"\bstandard\b", re.I)
_CONTRACT_BODY = re.compile(r"\bthis\s+(?:contract|agreement)\b", re.I)
_COVER_LINES = 25
_TITLE_WORDS_MAX = 14


@dataclass(frozen=True)
class DocumentKindEvidence:
    kind: str
    page: int | None
    quote: str | None
    method: str
    confidence: float | None
    guess: bool
    classifier_version: str
    classified_at: str
    conflict: str | None = None

    def as_dict(self) -> dict:
        return {"kind": self.kind, "page": self.page, "quote": self.quote,
                "method": self.method, "confidence": self.confidence,
                "guess": self.guess, "conflict": self.conflict,
                "classifier_version": self.classifier_version,
                "classified_at": self.classified_at}


def _cover_lines(pages: Sequence[dict]) -> list[tuple[int, str]]:
    """The title block (as `title_block_lines`) plus the first lines of page 1."""
    out = list(title_block_lines(pages))
    ordered = sorted(pages, key=lambda p: p["page_no"])
    if ordered:
        first = ordered[0]
        lines = [ln.strip() for ln in (first.get("text") or "").splitlines() if ln.strip()]
        for line in lines[:_COVER_LINES]:
            if (first["page_no"], line) not in out:
                out.append((first["page_no"], line))
    return out


def _type_code_hit(lines: Sequence[tuple[int, str]]) -> tuple[str, int, str] | None:
    for page, line in lines:
        if not (_NUMBER_LABEL.search(line) or _BARE_NUMBER.match(line.strip())):
            continue
        tokens = re.split(r"[^A-Za-z0-9]+", line.upper())
        for i, token in enumerate(tokens[:-1]):
            if token in _NUMBER_TYPE_CODES and tokens[i + 1].isdigit():
                return _NUMBER_TYPE_CODES[token], page, line
    return None


def _title_cue_hit(lines: Sequence[tuple[int, str]]) -> tuple[str, int, str] | None:
    for page, line in lines:
        text = line.strip().strip("|").strip()
        if not text or ":" in text or len(text.split()) > _TITLE_WORDS_MAX:
            continue
        for kind, pattern in _KIND_CUES:
            if pattern.search(text):
                return kind, page, text
        if _STANDARD_LINE.match(text) or (
                _STANDARD_WORDS.search(text) and len(text.split()) <= 6):
            return "standard", page, text
    return None


def _contract_body_hit(pages: Sequence[dict]) -> tuple[int, str] | None:
    ordered = sorted(pages, key=lambda p: p["page_no"])
    if not ordered:
        return None
    match = _CONTRACT_BODY.search(ordered[0].get("text") or "")
    if match is None:
        return None
    return ordered[0]["page_no"], _SPACE.sub(" ", match.group(0)).strip()


def decide_document_kind(pages: Sequence[dict], *, document_role: str | None = None
                         ) -> DocumentKindEvidence:
    """The kind of ONE document from its title block and cover; pure, no I/O.

    Order: the type code of the document number, then a title/cover heading,
    then the contract's own opening words, then a stored COMPANY_STANDARD role,
    then an equipment type named IN THE TITLE (a guess). Nothing else - no
    chunk, no body sentence. When the number and the title disagree the number
    wins and the title's reading is kept as `conflict`, and it is a guess."""
    now = _now()
    lines = _cover_lines(pages)

    def make(kind, page, quote, method, confidence, guess=False, conflict=None):
        return DocumentKindEvidence(
            kind=kind, page=page, quote=_SPACE.sub(" ", quote).strip() if quote else None,
            method=method, confidence=confidence, guess=guess,
            classifier_version=DOCUMENT_KIND_CLASSIFIER_VERSION, classified_at=now,
            conflict=conflict)

    code = _type_code_hit(lines)
    title = _title_cue_hit(lines)
    if code is not None:
        disagree = title is not None and title[0] != code[0]
        return make(code[0], code[1], code[2], "number_type_code", 0.8,
                    guess=disagree, conflict=title[0] if disagree else None)
    if title is not None:
        return make(title[0], title[1], title[2], "title_cue", 0.8)
    body = _contract_body_hit(pages)
    if body is not None:
        return make("contract", body[0], body[1], "cover_contract_words", 0.7, guess=True)
    if document_role == "COMPANY_STANDARD":
        return make("standard", None, None, "document_role", 0.7, guess=True)
    # Only heading-shaped lines: on a one-page note the whole page is "title
    # block", and a sentence of body text is not the document naming itself.
    named = suggest_equipment_type_from_title([
        (pg, ln) for pg, ln in title_block_lines(pages)
        if len(ln.split()) <= _TITLE_WORDS_MAX and not ln.rstrip().endswith(".")])
    if named is not None:
        return make("datasheet", named.page, named.quote, "title_equipment", 0.6, guess=True)
    return make("unknown", None, None, "no_cue", None, guess=True)


def classify_document_kind(document_id: str) -> DocumentKindEvidence | None:
    """Decide and store `document_kind` + its evidence for ONE document.

    Returns None and writes nothing when the switch is off or a person has
    confirmed the classification. A document with no classification row gets
    one (suggested_by names this classifier; nothing is confirmed)."""
    from .config import settings
    if not settings.document_kind_enabled:
        return None
    from .db import add_column_if_missing
    conn = connect()
    # A database copy read outside the server (the CRS bench) has not been
    # through `init_db`; the two columns are added the same way it adds them.
    for column in ("document_kind", "document_kind_evidence"):
        add_column_if_missing(conn, "document_classification", column, "TEXT")
    existing = conn.execute(
        "SELECT document_role, confirmed_by FROM document_classification"
        " WHERE document_id = ?", (document_id,)).fetchone()
    if existing is not None and existing["confirmed_by"] is not None:
        return None
    pages = [dict(r) for r in conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
        (document_id,))]
    evidence = decide_document_kind(
        pages, document_role=existing["document_role"] if existing else None)
    payload = json.dumps(evidence.as_dict())
    with conn:
        if existing is None:
            conn.execute(
                "INSERT INTO document_classification (document_id, suggested_by,"
                " document_kind, document_kind_evidence) VALUES (?,?,?,?)",
                (document_id, "document_kind_classifier", evidence.kind, payload))
        else:
            conn.execute(
                "UPDATE document_classification SET document_kind = ?,"
                " document_kind_evidence = ? WHERE document_id = ?",
                (evidence.kind, payload, document_id))
    return evidence


def document_kind_counts(document_ids: Iterable[str] | None = None) -> dict:
    """Documents per kind. `not_classified` counts documents with no kind
    stored, `unknown` those the classifier read and could not name - so the
    share sent to general review is countable, with its denominator."""
    conn = connect()
    ids = None if document_ids is None else list(document_ids)
    if ids is not None and not ids:
        return {"total": 0, "kinds": {}, "not_classified": 0}
    where, params = "", []
    if ids is not None:
        where, params = f" WHERE d.id IN ({','.join('?' * len(ids))})", ids
    kinds: dict[str, int] = {}
    not_classified = 0
    for row in conn.execute(
            "SELECT c.document_kind AS k, COUNT(*) AS n FROM documents d"
            " LEFT JOIN document_classification c ON c.document_id = d.id"
            f"{where} GROUP BY c.document_kind", params):
        if row["k"] is None:
            not_classified += row["n"]
        else:
            kinds[row["k"]] = row["n"]
    return {"total": sum(kinds.values()) + not_classified, "kinds": kinds,
            "not_classified": not_classified}
