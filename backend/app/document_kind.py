"""#1474: the KIND of a document (datasheet, procedure, specification, ...).

Moved out of classification.py, which only calls into it. Reads only the title
block and cover; no model, no network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .blank_form import is_blank_form, line_shape
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
# Behind `settings.document_kind_enabled`, ON by default (#1626). No model call: the AI
# may later give a second opinion, it does not decide here. A kind found from a
# cue is stored WITH its quote and page; a guess says it is a guess; a document
# no cue names is `unknown` (general review) and is counted, never hidden.

DOCUMENT_KIND_CLASSIFIER_VERSION = "document-kind-v1"

#: The vocabulary. `unknown` is a real answer: general review, marked.
DOCUMENT_KINDS: tuple[str, ...] = (
    "datasheet",
    "procedure",
    "specification",
    "transmittal",
    "contract",
    "drawing",
    "feed",
    "standard",
    "unknown",
)

#: Type codes a document number carries ("<project>-<area>-SP-<serial>"). Read
#: only inside a line that is a document number, and only when a serial number
#: follows the code.
_NUMBER_TYPE_CODES: dict[str, str] = {
    "SP": "specification",
    "SPC": "specification",
    "SPEC": "specification",
    "PD": "procedure",
    "PRC": "procedure",
    "PRO": "procedure",
    "PROC": "procedure",
    "DS": "datasheet",
    "DTS": "datasheet",
    "DSH": "datasheet",
    "DW": "drawing",
    "DWG": "drawing",
    "TR": "transmittal",
    "TRN": "transmittal",
    "TRM": "transmittal",
    "CT": "contract",
    "CTR": "contract",
}
_NUMBER_LABEL = re.compile(
    r"\b(?:doc(?:ument)?\.?\s*(?:no|num(?:ber)?)|drawing\s*no|document\s*ref)\b", re.I
)
_BARE_NUMBER = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+){3,}$")

#: Title cues, in priority order within ONE line. A line is a title/cover line
#: when it is short and is not a "Label: value" line (a label naming a standard
#: or a specification is a reference, not what the document is).
_KIND_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "procedure",
        re.compile(
            r"\bprocedures?\b|\bmethod\s+statement\b|\bwork\s+instruction\b"
            # #1476: a test plan says how a test is done (a plot plan is not one).
            r"|\b(?:test(?:ing)?|inspection\s+and\s+test)\s+plans?\b",
            re.I,
        ),
    ),
    ("transmittal", re.compile(r"\btransmittals?\b", re.I)),
    (
        "contract",
        re.compile(
            r"\bschedule\s+[\"“”]\s*[A-Z0-9]{1,3}\s*[\"“”]"
            r"|\b(?:agreement|general\s+conditions|terms\s+and\s+conditions"
            r"|conditions\s+of\s+contract)\b",
            re.I,
        ),
    ),
    ("specification", re.compile(r"\bspecifications?\b", re.I)),
    (
        "drawing",
        re.compile(
            r"\bdrawings?\b|\bp\s?&\s?ids?\b|\bpiping\s+and\s+instrument\w*\s+diagram"
            r"|\bsingle[- ]line\s+diagram\b|\bgeneral\s+arrangement\b|\bisometric\b",
            re.I,
        ),
    ),
    ("feed", re.compile(r"\bFEED\b|(?i:\bfront[- ]end\s+engineering\s+design\b)")),
    ("datasheet", re.compile(r"\bdata\s?sheets?\b", re.I)),
)
#: A title cue list: `_KIND_CUES`, or the paper kind's own (`paper_kind`).
Cues = Sequence[tuple[str, re.Pattern[str]]]
_STANDARD_LINE = re.compile(
    r"^(?:SAES|SAEP|SAIC|ISO|IEC|API|ASME|ASTM|NORSOK|NFPA|IEEE|BS|DIN|EN)"
    r"[-\s]?[A-Z]{0,3}[-\s]?\d",
    re.I,
)
#: A kind word followed by number / no. / ref is a label naming ANOTHER
#: document ("P&ID NUMBER", "Drawing No"), not this document's title.
_REFERENCE_AFTER = re.compile(
    r"\s*(?:number\b|no\b\.?(?!-)|nr\b\.?|ref\b\.?(?!-)|reference\b)", re.I
)
_STANDARD_WORDS = re.compile(r"\bstandard\b", re.I)
_CONTRACT_BODY = re.compile(r"\bthis\s+(?:contract|agreement)\b", re.I)
_COVER_LINES = 25
_COVER_PAGES = 2  # the cover and the title page
_TITLE_PAGE_LINES = 5  # the top of the title page, not its body
_CONTENTS_HEADING = re.compile(r"^\W*(?:table\s+of\s+)?contents\b", re.I)
_NUMBERED_LINE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+\S")
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
        return {
            "kind": self.kind,
            "page": self.page,
            "quote": self.quote,
            "method": self.method,
            "confidence": self.confidence,
            "guess": self.guess,
            "conflict": self.conflict,
            "classifier_version": self.classifier_version,
            "classified_at": self.classified_at,
        }


def _cover_lines(pages: Sequence[dict]) -> list[tuple[int, str]]:
    """The title block (as `title_block_lines`) on the cover and title pages
    only, plus the first lines of page 1 and the top lines of page 2 (the title
    page). Owner decision 1 Nov (#1476): a later page - an attachment's own
    heading on page 51 - never decides the kind."""
    ordered = sorted(pages, key=lambda p: p["page_no"])
    cover_pages = {p["page_no"] for p in ordered[:_COVER_PAGES]}
    out = [(pg, ln) for pg, ln in title_block_lines(pages) if pg in cover_pages]
    if ordered:
        first = ordered[0]
        lines = [
            ln.strip() for ln in (first.get("text") or "").splitlines() if ln.strip()
        ]
        for line in lines[:_COVER_LINES]:
            if (first["page_no"], line) not in out:
                out.append((first["page_no"], line))
    for title_page in ordered[1:_COVER_PAGES]:
        lines = [
            ln.strip()
            for ln in (title_page.get("text") or "").splitlines()
            if ln.strip()
        ]
        if lines and _CONTENTS_HEADING.match(lines[0]):
            continue  # a contents page lists other parts, it is not a title
        for line in lines[:_TITLE_PAGE_LINES]:
            if _NUMBERED_LINE.match(line):
                continue  # "2 Test Procedure": a contents or section line
            if (title_page["page_no"], line) not in out:
                out.append((title_page["page_no"], line))
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


def _title_cue_hit(
    lines: Sequence[tuple[int, str]], cues: Cues = _KIND_CUES
) -> tuple[str, int, str] | None:
    # #1476: the earliest page first - a document names itself at its start, and
    # an attachment deep inside (a safety data sheet on page 51) is not its title.
    # `cues`: the paper kind (`paper_kind`) passes its own list; default unchanged.
    for page, line in sorted(lines, key=lambda pl: pl[0]):
        text = line.strip().strip("|").strip()
        if not text or ":" in text or len(text.split()) > _TITLE_WORDS_MAX:
            continue
        for kind, pattern in cues:
            if any(
                not _REFERENCE_AFTER.match(text, m.end())
                for m in pattern.finditer(text)
            ):
                return kind, page, text
        if _STANDARD_LINE.match(text) or (
            _STANDARD_WORDS.search(text) and len(text.split()) <= 6
        ):
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


def decide_document_kind(
    pages: Sequence[dict], *, document_role: str | None = None, cues: Cues = _KIND_CUES
) -> DocumentKindEvidence:
    """The kind of ONE document from its title block and cover; pure, no I/O.

    Order: a stored COMPANY_STANDARD role (always a standard; title cues only
    decide among submittal kinds), then the type code of the document number,
    then a title/cover heading, then the contract's own opening words, then an
    equipment type named IN THE TITLE (a guess). Nothing else - no
    chunk, no body sentence. When the number and the title disagree the number
    wins and the title's reading is kept as `conflict`, and it is a guess."""
    now = _now()
    lines = _cover_lines(pages)

    def make(kind, page, quote, method, confidence, guess=False, conflict=None):
        return DocumentKindEvidence(
            kind=kind,
            page=page,
            quote=_SPACE.sub(" ", quote).strip() if quote else None,
            method=method,
            confidence=confidence,
            guess=guess,
            classifier_version=DOCUMENT_KIND_CLASSIFIER_VERSION,
            classified_at=now,
            conflict=conflict,
        )

    if document_role == "COMPANY_STANDARD":
        # A standard ABOUT drawings is still a standard: the stored role decides,
        # and says it is from the role, not from a title.
        return make("standard", None, None, "document_role", 0.7, guess=True)
    blank = is_blank_form(lines)
    if blank:
        # Owner order 1 Nov: a form of labels with no values never takes its
        # kind from a label. A cell-less heading may; a label row only when it
        # names the form a data sheet (the one kind a blank form can be).
        data_sheet = _KIND_CUES[-1][1]
        lines = [
            (pg, ln)
            for pg, ln in lines
            if line_shape(ln) == "other" or data_sheet.search(ln)
        ]
    code = _type_code_hit(lines)
    title = _title_cue_hit(lines, cues)
    if code is not None:
        disagree = title is not None and title[0] != code[0]
        return make(
            code[0],
            code[1],
            code[2],
            "number_type_code",
            0.8,
            guess=disagree,
            conflict=title[0] if disagree else None,
        )
    if title is not None:
        return make(title[0], title[1], title[2], "title_cue", 0.8)
    body = None if blank else _contract_body_hit(pages)
    if body is not None:
        return make(
            "contract", body[0], body[1], "cover_contract_words", 0.7, guess=True
        )
    # Only heading-shaped lines: on a one-page note the whole page is "title
    # block", and a sentence of body text is not the document naming itself.
    named = suggest_equipment_type_from_title(
        [
            (pg, ln)
            for pg, ln in title_block_lines(pages)
            if len(ln.split()) <= _TITLE_WORDS_MAX
            and not ln.rstrip().endswith(".")
            and not (blank and line_shape(ln) != "other")
        ]
    )
    if named is not None:
        return make(
            "datasheet", named.page, named.quote, "title_equipment", 0.6, guess=True
        )
    if blank:
        return make("unknown", None, None, "blank_form", None, guess=True)
    return make("unknown", None, None, "no_cue", None, guess=True)


def stored_kind(document_id: str):
    """`(kind, state)` the ONE kind table (`document_kinds`, the router's) holds
    for the document, or None."""
    row = (
        connect()
        .execute(
            "SELECT kind, state FROM document_kinds WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    return None if row is None else (row["kind"], row["state"])


def contested(document_id: str) -> bool:
    """Is the stored kind only a guess whose own evidence names a conflict, with no
    engineer's confirmation? Then it decides nothing: not a path, not a rule set."""
    row = (
        connect()
        .execute(
            "SELECT state, evidence FROM document_kinds WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    if row is None or row["state"] == "confirmed":
        return False
    try:
        evidence = json.loads(row["evidence"] or "{}")
        return bool(evidence.get("guess") and evidence.get("conflict"))
    except (TypeError, ValueError, AttributeError):
        return False


def classify_document_kind(document_id: str) -> DocumentKindEvidence | None:
    """Decide the document's kind and store it in the router's table.

    ONE kind per document: this is a second suggester for `doc_router`'s table
    `document_kinds`, never a second store. A kind an engineer confirmed (there)
    is never touched. A kind found is a SUGGESTION (state `suggested`, `guess`
    in the evidence says how sure); nothing found stores no kind and the state
    `needs_engineer`. Returns None, writing nothing, when the switch is off or
    the kind is confirmed."""
    from . import doc_router
    from .config import settings

    if not settings.document_kind_enabled:
        return None
    existing = stored_kind(document_id)
    if existing is not None and existing[1] == doc_router.STATE_CONFIRMED:
        return None
    conn = connect()
    pages = [
        dict(r)
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    role = conn.execute(
        "SELECT document_role FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    evidence = decide_document_kind(
        pages, document_role=role["document_role"] if role else None
    )
    known = evidence.kind != "unknown"
    _write(
        document_id,
        evidence.kind if known else None,
        doc_router.STATE_SUGGESTED if known else doc_router.STATE_NEEDS_ENGINEER,
        {"decider": "document_kind", **evidence.as_dict()},
    )
    return evidence


def classify_contract(document_id: str) -> DocumentKindEvidence | None:
    """The CONTRACT kind for a document of ANY role (order 14 lane E, owner 16 Nov 2026): the parts of a contract carry no
    CONTRACTOR_SUBMITTAL role, so `classify_document_kind` never runs on them and the other suggester (`doc_router`) has no
    contract cues. Here the same general decision (`decide_document_kind`: a contract heading on the cover such as a
    quoted schedule label, "agreement", "general conditions", or "this contract" opening the paper) is stored ONLY when it
    says contract, as a SUGGESTION (rule 4: a guess until a person confirms it). Any other decision writes nothing: the
    document keeps what it has. A confirmed kind is never touched; the switch off writes nothing. Returns the evidence
    stored, else None."""
    from . import doc_router
    from .config import settings

    if not settings.document_kind_enabled:
        return None
    existing = stored_kind(document_id)
    if existing is not None and existing[1] == doc_router.STATE_CONFIRMED:
        return None
    conn = connect()
    pages = [
        dict(r)
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    role = conn.execute(
        "SELECT document_role FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    evidence = decide_document_kind(
        pages, document_role=role["document_role"] if role else None
    )
    if evidence.kind != "contract":
        return None
    _write(
        document_id,
        "contract",
        doc_router.STATE_SUGGESTED,
        {"decider": "document_kind.contract", **evidence.as_dict()},
    )
    return evidence


def _write(document_id: str, kind, state: str, evidence: dict) -> None:
    from . import doc_router

    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, evidence,"
            " router_version, routed_at) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(document_id) DO UPDATE SET kind = excluded.kind,"
            " state = excluded.state, evidence = excluded.evidence,"
            " router_version = excluded.router_version,"
            " routed_at = excluded.routed_at WHERE document_kinds.state != 'confirmed'",
            (
                document_id,
                kind,
                state,
                json.dumps(evidence),
                str(doc_router.vocabulary().get("router_version", "1")),
                doc_router._now(),
            ),
        )


def mark_equipment_guessed_from_body(document_id: str) -> None:
    """The kind is unknown and the equipment type came from body text: say so
    on the kind record (state stays `needs_engineer`), so the engineer is asked
    to confirm the kind and the equipment is shown as a guess."""
    from . import doc_router

    row = (
        connect()
        .execute(
            "SELECT kind, state, evidence FROM document_kinds WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    if row is None or row["state"] == doc_router.STATE_CONFIRMED:
        return
    keeps_kind = contested(document_id)
    if row["kind"] is not None and not keeps_kind:
        return
    try:
        evidence = json.loads(row["evidence"] or "{}")
    except ValueError:
        evidence = {}
    evidence["equipment_guessed_from_body"] = True
    if keeps_kind:
        _write(document_id, row["kind"], row["state"], evidence)
    else:
        _write(document_id, None, doc_router.STATE_NEEDS_ENGINEER, evidence)


def body_equipment_allowed(pages: Sequence[dict], document_id: str, role) -> bool:
    """May body text name the equipment? Only for a datasheet, or - marked a
    guess, engineer asked - when the kind could not be told. A kind an engineer
    confirmed decides; otherwise the title block and cover decide."""
    stored = stored_kind(document_id)
    if stored is not None and stored[1] == "confirmed":
        return stored[0] == "datasheet"
    decided = decide_document_kind(pages, document_role=role)
    if decided.method == "blank_form":
        return False  # a blank form's labels name no equipment: ask the engineer
    if decided.kind in ("datasheet", "unknown"):
        return True
    # The number and the title disagree, and one of them says datasheet: the kind
    # is not told, so the body may name the equipment, marked a guess.
    return decided.guess and decided.conflict == "datasheet"


def counts_from(conn, document_ids: Iterable[str] | None = None) -> dict:
    """Documents per kind in the ONE kind table, from any connection. `unknown`
    = kind empty and an engineer asked (this decider's answer and the router's
    alike); `not_classified` = no record. `unknown_rate` has its denominator."""
    ids = None if document_ids is None else list(document_ids)
    if ids is not None and not ids:
        return {
            "total": 0,
            "kinds": {},
            "unknown": 0,
            "not_classified": 0,
            "unknown_rate": None,
        }
    where, params = "", []
    if ids is not None:
        where, params = f" WHERE d.id IN ({','.join('?' * len(ids))})", ids
    kinds: dict[str, int] = {}
    unknown = not_classified = 0
    for row in conn.execute(
        "SELECT k.kind AS kind, k.document_id AS rid, COUNT(*) AS n FROM documents d"
        f" LEFT JOIN document_kinds k ON k.document_id = d.id{where}"
        " GROUP BY k.kind, (k.document_id IS NULL)",
        params,
    ):
        if row["rid"] is None:
            not_classified += row["n"]
        elif row["kind"] is None:
            unknown += row["n"]
        else:
            kinds[row["kind"]] = row["n"]
    decided = sum(kinds.values()) + unknown
    total = decided + not_classified
    return {
        "total": total,
        "decided": decided,
        "kinds": kinds,
        "unknown": unknown,
        "not_classified": not_classified,
        # unknown of the documents that HAVE a kind decision - the rate the 10%
        # stop rule means. Documents never decided are not in it (see `decided`).
        "unknown_rate": round(unknown / decided, 4) if decided else None,
    }


def rate_lines(counts: dict) -> list[str]:
    """The report: two numbers, each with its own boundary."""
    decided, total, unknown = counts["decided"], counts["total"], counts["unknown"]
    rate = counts["unknown_rate"]
    lines = [f"documents: {total}"]
    lines += [f"  {k}: {n}" for k, n in sorted(counts["kinds"].items())]
    lines.append(f"  unknown (kind empty, engineer asked): {unknown}")
    lines.append(f"  no kind decision yet: {counts['not_classified']}")
    lines.append(
        "unknown of documents with a kind decision: "
        + (
            "n/a (none decided)"
            if rate is None
            else f"{unknown}/{decided} = {rate:.1%}"
        )
    )
    lines.append(f"documents decided at all: {decided}/{total}")
    return lines


def document_kind_counts(document_ids: Iterable[str] | None = None) -> dict:
    return counts_from(connect(), document_ids)


# ------------------------------------------------------- one upload: a suggested kind AND role (order 14 lane E)
#
# Owner, 16 Nov 2026: a file uploaded on ANY page gets the same treatment: the app suggests its kind and its role, shows
# "suggested, confirm or change", and once a person confirms the role the file is in the right list. The ROLE SUGGESTION lives
# in the kind row's evidence (`role_suggestion`), NEVER in `document_role`: the Claude approved list reads `document_role` only,
# so a suggestion never counts there; only a confirmed role (the existing `classification.set_role`) does, and a contract never
# joins it. Behind `upload_role_suggestion_enabled`, off by default: off, nothing here reads or writes anything.

SUBMITTAL, STANDARD, CONTRACT_DOC, SPEC_ROLE = (
    "CONTRACTOR_SUBMITTAL",
    "COMPANY_STANDARD",
    "CONTRACT_DOCUMENT",
    "SPECIFICATION",
)
#: The role a decided kind points to; a kind not listed points to none (the person chooses).
ROLE_FOR_KIND = {
    "contract": CONTRACT_DOC,
    "standard": STANDARD,
    "datasheet": SUBMITTAL,
    "procedure": SUBMITTAL,
    "drawing": SUBMITTAL,
    "transmittal": SUBMITTAL,
    "specification": SPEC_ROLE,
}
#: The page a file was uploaded on, and the role that page is for (none: the Documents page is for any role).
PAGE_ROLE = {"review": SUBMITTAL, "standards": STANDARD, "documents": None}
CONTEXT_FILE = "upload_context.jsonl"


def suggest_role(kind: str | None, page: str | None) -> dict | None:
    """The suggested role from the two signals, or None when neither names one. Pure. The page is what the person meant by
    uploading there; the kind is what the paper says it is. When both name a role and they differ, the page's role is
    suggested and the disagreement is named (`kind_says`), so the person sees it before confirming."""
    by_kind = ROLE_FOR_KIND.get(kind or "")
    by_page = PAGE_ROLE.get(page or "")
    if by_page:
        out = {"role": by_page, "basis": "page", "page": page, "kind": kind}
        if by_kind and by_kind != by_page:
            out["kind_says"] = by_kind
        return out
    if by_kind:
        return {"role": by_kind, "basis": "kind", "page": page, "kind": kind}
    return None


def _context_path():
    from .config import settings

    return settings.data_dir / CONTEXT_FILE


def record_upload_context(document_id: str, page: str | None) -> bool:
    """Keep the page a file was uploaded on until the file is read in (the kind row does not exist yet at upload). Switch on and a
    known page only; one appended line, ids and the page name only. Returns whether it was kept."""
    from .config import settings

    if not settings.upload_role_suggestion_enabled or page not in PAGE_ROLE:
        return False
    path = _context_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"document_id": document_id, "uploaded_from": page, "at": _now()})
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return True


def upload_context(document_id: str) -> str | None:
    """The page the file was last uploaded on, or None."""
    path = _context_path()
    if not path.exists():
        return None
    found = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if row.get("document_id") == document_id:
            found = row.get("uploaded_from")
    return found


def suggest_kind_and_role(document_id: str) -> dict | None:
    """After a file is read in (switch on): its kind as `decide_document_kind` reads it whatever its role (stored as a SUGGESTION
    unless a person confirmed a kind; an unknown decision keeps what the router stored), and a ROLE SUGGESTION in the same row's
    evidence. A file that already has a role gets no suggestion (a person or a page already decided). Returns the role
    suggestion written ({"role": None} when there is none), or None when nothing was written."""
    from . import doc_router
    from .config import settings

    if not settings.upload_role_suggestion_enabled:
        return None
    conn = connect()
    role = conn.execute(
        "SELECT document_role FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if role is not None and role["document_role"]:
        return None
    pages = [
        dict(r)
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    row = conn.execute(
        "SELECT kind, state, evidence FROM document_kinds WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    try:
        held = json.loads(row["evidence"] or "{}") if row else {}
    except ValueError:
        held = {}
    held = held if isinstance(held, dict) else {}
    decided = decide_document_kind(pages)
    if row is not None and row["state"] == doc_router.STATE_CONFIRMED:
        kind, state, evidence = row["kind"], row["state"], held
    elif decided.kind != "unknown" and not (
        # Rule 1 (review R104): a stored "contract" kind is never replaced by a reading (an OCR re-route can change the
        # text); only a person's confirm changes it. The router's one rule, `doc_router._keeps_contract`.
        row is not None and doc_router._keeps_contract(row["kind"], None)
    ):
        kind, state = decided.kind, doc_router.STATE_SUGGESTED
        evidence = {"decider": "document_kind.upload", **decided.as_dict()}
    else:
        kind = row["kind"] if row else None
        state = row["state"] if row else doc_router.STATE_NEEDS_ENGINEER
        evidence = held
    suggestion = suggest_role(kind, upload_context(document_id)) or {
        "role": None,
        "basis": "none",
        "kind": kind,
    }
    evidence = {**evidence, "role_suggestion": suggestion}
    if row is not None and row["state"] == doc_router.STATE_CONFIRMED:
        with conn:
            conn.execute(
                "UPDATE document_kinds SET evidence = ? WHERE document_id = ?",
                (json.dumps(evidence), document_id),
            )
    else:
        _write(document_id, kind, state, evidence)
    return suggestion


def after_upload(document_id: str, page: str | None, duplicate: bool) -> None:
    """The upload route's one call (switch on): keep the page the file came in on, and for a file already read in (a duplicate)
    suggest its kind and role now. Off: nothing. Never fails an upload."""
    from .config import settings

    if not settings.upload_role_suggestion_enabled:
        return
    try:
        record_upload_context(document_id, page)
        if duplicate:
            suggest_kind_and_role(document_id)
    except Exception as exc:  # noqa: BLE001 - a suggestion must never fail an upload
        import logging

        logging.getLogger(__name__).warning(
            "upload role suggestion skipped for %s: %s", document_id, type(exc).__name__
        )


def after_read_in(document_id: str) -> None:
    """The ingest worker's one call, right after the router (switch on): the suggested kind and role. Never fails an ingest."""
    from .config import settings

    if not settings.upload_role_suggestion_enabled:
        return
    try:
        suggest_kind_and_role(document_id)
    except Exception as exc:  # noqa: BLE001 - a suggestion must never fail an ingest
        import logging

        logging.getLogger(__name__).warning(
            "kind and role suggestion skipped for %s: %s", document_id, type(exc).__name__
        )
