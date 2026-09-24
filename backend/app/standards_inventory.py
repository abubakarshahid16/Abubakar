"""Standards inventory (B5 part 2): family, edition/revision, licence status,
cover-page backfill, and which standards a submittal or requirement cites.

Per the owner's 2026-09-24 order. Scope of THIS module: the data model, the
cover-page metadata extractor the backfill script calls, the read-side query
that assembles one inventory row per COMPANY_STANDARD document, and the
"cited but not held" report (`cited_but_not_held`) - every standard cited by
a submittal or by a SAES requirement's own normative reference that is not
in the local library, with where it was cited. The licensed-lookup
transport and the Standards Library UI page are later stages, listed and
NOT yet built at the bottom of this docstring so nobody mistakes silence
for completion.

WHY LICENCE STATUS AND FAMILY ARE COMPUTED, NOT STORED AS A DUMPED GUESS.
`default_licence_status` and `family_from_identifier` only ever assert what
the presence of a file, or the text of an identifier, actually establishes
(CLAUDE.md rule 4: a guess is shown as a guess until a human confirms it).
Neither function invents a family or a licence position it cannot support.

WHY CITATIONS ARE COMPUTED LIVE, NEVER STORED. `classification.py`'s own
design note (on why it does not persist a submittal's cited-standards list)
applies here without change: a stored copy goes stale the moment a document
is re-chunked or re-extracted. This module recomputes a submittal's
citations from `datasheets.referenced_standards` over the SAME chunks
`applicability.py` already reads for review selection, and a requirement's
own citation from `requirements_3b.cited_document` over the SAME
`standard_requirements` row extraction already produced - so this report
can never disagree with what a real review, or a real extraction, saw.

CITED_BUT_NOT_HELD IS DELIBERATELY NOT MERGED INTO THE PER-SUBMITTAL CRS
MISSING-REFERENCE ROW. `crs_mapping.build_crs_rows`'s existing
`ROW_KIND_MISSING_REFERENCE` rows say "this submittal cites standard X" -
true only for a citation that submittal's own text actually makes. A SAES
requirement's citation was never made BY that submittal, and folding it
into the same per-submittal row would misattribute it. `cited_but_not_held`
is the combined, run-wide report (`GET /api/standards/cited-but-not-held`)
the owner asked for to take to the standards body - the CRS's own
per-submittal rows are unchanged and remain accurate to what that one
submittal actually cites.

NOT YET BUILT (tracked, not silently skipped):
  - the licensed-lookup transport (never fetches copyrighted text; records
    provenance only for freely published, authorized sources).
  - the Standards Library page addition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from . import datasheets, db, standards
from .db import connect

# --------------------------------------------------------------- vocabulary

FAMILY_SAES = "SAES"
FAMILY_SAMSS = "SAMSS"
FAMILY_API = "API"
FAMILY_ASME = "ASME"
FAMILY_ASTM = "ASTM"
FAMILY_ISO = "ISO"
FAMILY_IEC = "IEC"
FAMILY_NFPA = "NFPA"
FAMILY_NACE = "NACE"
FAMILY_KOC = "KOC"
FAMILY_OTHER = "OTHER"

FAMILIES = (FAMILY_SAES, FAMILY_SAMSS, FAMILY_API, FAMILY_ASME, FAMILY_ASTM,
            FAMILY_ISO, FAMILY_IEC, FAMILY_NFPA, FAMILY_NACE, FAMILY_KOC,
            FAMILY_OTHER)

#: Families this project's own client issues - present in the library
#: because Saudi Aramco (or KOC) wrote them, not because a third party's
#: copyrighted text was licensed.
_OWN_STANDARD_FAMILIES = frozenset({FAMILY_SAES, FAMILY_SAMSS, FAMILY_KOC})

#: Families a standards body publishes and normally sells under licence.
#: CLAUDE.md rule 1 and the owner's instruction: never fetch one of these
#: from an unlicensed source; a missing one is recorded MISSING_LOCALLY, not
#: downloaded.
COPYRIGHTED_FAMILIES = frozenset({FAMILY_API, FAMILY_ASME, FAMILY_ASTM,
                                  FAMILY_ISO, FAMILY_IEC, FAMILY_NFPA,
                                  FAMILY_NACE})

LICENCE_HELD = "held"
LICENCE_LICENSED_NOT_HELD = "licensed_not_held"
LICENCE_NOT_LICENSED = "not_licensed"
LICENCE_UNKNOWN = "unknown"

LICENCE_STATUSES = (LICENCE_HELD, LICENCE_LICENSED_NOT_HELD,
                     LICENCE_NOT_LICENSED, LICENCE_UNKNOWN)

#: The family token anywhere in an identifier, not anchored at the start -
#: a SAMSS citation is written number-first ("02-SAMSS-014"), so anchoring
#: at position 0 would silently read every SAMSS document as OTHER.
_FAMILY_TOKEN = re.compile(
    r"\b(SAES|SAMSS|API|ASME|ASTM|ISO|IEC|NFPA|NACE|KOC)\b", re.IGNORECASE)


def family_from_identifier(identifier: str | None) -> str:
    """The standard family named anywhere in `identifier`, or OTHER.

    Never UNKNOWN. UNKNOWN is reserved for "this system has not looked yet" -
    given actual text, a family classifier that has looked and found nothing
    recognisable reports OTHER, a real (if uninformative) answer, not the
    absence of one.
    """
    match = _FAMILY_TOKEN.search(identifier or "")
    return match.group(1).upper() if match else FAMILY_OTHER


def default_licence_status(family: str, *, held: bool) -> str:
    """The licence status this system may assert WITHOUT being told.

    `held`: the file is in the local library right now, so regardless of its
    origin this system already has a copy - `held`, unconditionally.

    Missing and a `COPYRIGHTED_FAMILIES` member: a real inference, not a
    guess. A body that sells API/ASME/ASTM/ISO/IEC/NFPA/NACE content would
    require a licence for any copy of it, so "we do not have this one" is
    honestly `licensed_not_held` - the owner's instruction is to record such
    gaps this way until a licensed copy is supplied.

    Missing and an owned family (SAES/SAMSS/KOC) or OTHER: this system has
    no basis to assert a licence position either way - `unknown`, for the
    owner to resolve (simply not yet uploaded, vs something else).
    """
    if held:
        return LICENCE_HELD
    if family in COPYRIGHTED_FAMILIES:
        return LICENCE_LICENSED_NOT_HELD
    return LICENCE_UNKNOWN


# ------------------------------------------------------------------ schema

def ensure_schema() -> None:
    """Additive columns on `document_classification`. Safe to call every
    request; `add_column_if_missing` is the project's own race-safe helper.

    `document_number_evidence`/`revision_evidence` follow the same JSON-blob
    shape `equipment_type_evidence` already uses (`classification.py`) - one
    home for "how did this system arrive at this field", not a second shape
    to keep in step with the first."""
    conn = connect()
    with conn:
        db.add_column_if_missing(conn, "document_classification",
                                  "standard_family", "TEXT")
        db.add_column_if_missing(conn, "document_classification",
                                  "licence_status", "TEXT")
        db.add_column_if_missing(conn, "document_classification",
                                  "document_number_evidence", "TEXT")
        db.add_column_if_missing(conn, "document_classification",
                                  "revision_evidence", "TEXT")
        db.add_column_if_missing(conn, "document_classification",
                                  "effective_date_evidence", "TEXT")


# ------------------------------------------------------- cover-page backfill

@dataclass(frozen=True)
class CoverField:
    """One fact read off a standard's own cover pages, with where it came
    from - never asserted without a page and the exact text it was read
    from."""
    value: str
    page: int
    quote: str


@dataclass(frozen=True)
class CoverMetadata:
    document_number: CoverField | None
    revision: CoverField | None
    effective_date: CoverField | None


#: A Saudi Aramco standard's own number, as its cover page prints it. NOT
#: zero-padded here - `applicability.library_identifier` reads FILENAMES and
#: normalises for matching; this reads the document's own printed text and
#: keeps it as printed, because a backfilled field is a transcription, not a
#: derived key.
_COVER_SAES_NUMBER = re.compile(r"\bSAES[-\s]*([A-Z])[-\s]*(\d{1,4})\b")

#: "Revision 3", "Rev. C", "REVISION: 03", "Rev: NEW" (a first issue, with no
#: prior revision - a real value, not a missing one).
#:
#: TWO GUARDS, BOTH FOUND BY RUNNING THIS AGAINST THE REAL 272-STANDARD
#: CORPUS BEFORE TRUSTING IT.
#:
#: `REV` MUST NOT CONTINUE AS MORE LETTERS. "under REVIEW", "was REVISED",
#: "management REVIEW" all contain the substring "REV" followed by ordinary
#: English letters; an unguarded `REV(?:ISION)?` read "IEW" and "ISE" out of
#: them as if they were revision codes. Either the full word "REVISION"
#: follows, or nothing that could extend "REV" into a longer English word
#: does - `(?![A-Za-z])` is checked right after "REV".
#:
#: "ISION" ITSELF NEEDS A TRAILING BOUNDARY. Plain "revisions" (plural, no
#: colon, in an ordinary sentence - "revisions, addenda and supplements
#: unless...") contains "revision" as a PREFIX; without `\b` after "ISION"
#: the match consumed "revision" and then read the plural's own "s" as a
#: one-letter revision code "S".
#:
#: THE CODE ITSELF MUST LOOK LIKE A REVISION, not just be 1-3 letters or
#: digits. A generic `[A-Z0-9]{1,3}` also matched "REVISION HISTORY" as
#: revision "HIS", and a genuine revision-log table header ("FROM REV TO
#: REV") as revision "TO" - both syntactically identical to a real "Rev: C".
#: A real revision code in this corpus is a small number, a single letter
#: (draft/lettered revisions), or the word NEW (first issue) - nothing else
#: is accepted, closing off the ordinary-English-word failure mode at its
#: root instead of chasing individual false positives with a blocklist.
_COVER_REVISION = re.compile(
    r"\bREV(?:ISION\b|(?![A-Za-z]))\.?\s*[:#]?\s*([0-9]{1,3}|[A-Z]|NEW)\b",
    re.IGNORECASE)

#: The date THIS revision took effect - "Issue Date: 18 August 2019" or the
#: older-format "Effective Date: ...". Deliberately NOT "Previous Issue"
#: (the date the PRIOR revision took effect - a real date, but the wrong
#: one) and NOT "Next Planned Update" (a future date that has not happened
#: yet). A newer Aramco cover format states Issue Date/Previous Issue/Next
#: Planned Update instead of a bare "Revision: N" (found while sampling the
#: real corpus's UNKNOWN revisions - these covers are not missing wording a
#: reader failed to catch; they are a genuinely different, date-based
#: format), so recognising the right ONE OF THE THREE matters: matching
#: "Previous Issue" or "Next Planned Update" into `effective_date` would
#: record a real date under the wrong claim, which this project's honesty
#: rules treat as worse than leaving the field UNKNOWN.
_COVER_ISSUE_DATE = re.compile(
    r"\b(?:Issue\s+Date|Effective\s+Date)\s*[:#]?\s*"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}"          # "18 August 2019"
    r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4}"        # "August 18, 2019"
    r"|\d{4}-\d{2}-\d{2})",                  # "2019-08-18"
    re.IGNORECASE)

#: The three shapes `_COVER_ISSUE_DATE` can capture, each parsed to ISO.
_DATE_INPUT_FORMATS = ("%d %B %Y", "%B %d, %Y", "%B %d %Y", "%Y-%m-%d")


def _to_iso_date(raw: str) -> str | None:
    """`raw`, as `_COVER_ISSUE_DATE` captured it, as `YYYY-MM-DD` - or None
    if it does not parse as any of the shapes the pattern can produce.

    STORED AS ISO, QUOTED AS PRINTED. `CoverField.value` becomes the ISO
    form so every effective_date in the inventory sorts and compares the
    same way regardless of which of the three cover-page phrasings produced
    it; `CoverField.quote` keeps the document's own words, so the original
    text is never lost - a caller who wants "18 August 2019" reads the
    evidence, not the stored field.
    """
    from datetime import datetime

    text = " ".join(raw.split())
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

#: How many of a standard's own leading pages to read for cover metadata.
#: Cover sheet plus one following revision-log page, no further - reading
#: into the body risks matching an unrelated internal revision reference
#: instead of the document's own.
_COVER_PAGES = 2


def extract_cover_metadata(pages: Sequence[dict]) -> CoverMetadata:
    """The document number, revision and issue date AS PRINTED on a
    standard's own cover pages, each with the page and exact quote it was
    read from.

    A field this system cannot find on the cover pages stays None - UNKNOWN,
    never guessed, never filled from a filename or a later body page.
    """
    ordered = sorted(pages, key=lambda p: p["page_no"])[:_COVER_PAGES]
    number: CoverField | None = None
    revision: CoverField | None = None
    effective_date: CoverField | None = None
    for page in ordered:
        text = page.get("text") or ""
        if number is None:
            match = _COVER_SAES_NUMBER.search(text)
            if match:
                number = CoverField(
                    value=f"SAES-{match.group(1).upper()}-{int(match.group(2)):03d}",
                    page=page["page_no"], quote=match.group(0).strip())
        if revision is None:
            match = _COVER_REVISION.search(text)
            if match:
                revision = CoverField(
                    value=match.group(1).upper(),
                    page=page["page_no"], quote=match.group(0).strip())
        if effective_date is None:
            match = _COVER_ISSUE_DATE.search(text)
            if match:
                iso = _to_iso_date(match.group(1))
                # A DATE THAT DOES NOT PARSE STAYS UNKNOWN, never stored as
                # the raw text - a caller comparing `effective_date` values
                # must be able to trust every one is ISO, not sometimes a
                # sentence fragment the pattern happened to match.
                if iso is not None:
                    effective_date = CoverField(
                        value=iso, page=page["page_no"],
                        quote=match.group(0).strip())
        if number is not None and revision is not None and effective_date is not None:
            break
    return CoverMetadata(document_number=number, revision=revision,
                         effective_date=effective_date)


def backfill_cover_metadata(document_id: str) -> dict:
    """Fill `document_number`/`revision`/`effective_date`/`standard_family`
    for ONE standard from its own cover pages, each write carrying a page +
    quote citation.

    NEVER OVERWRITES A REAL ANSWER. A `document_number`, `revision` or
    `effective_date` that is already non-NULL - confirmed by a human or set
    by an earlier run - is left untouched; this function only fills a field
    that is currently NULL. A cover page with nothing recognisable leaves
    the field NULL - UNKNOWN, not guessed, and not silently left looking the
    same as "not yet tried" (the caller distinguishes the two from
    `attempted` in the return value).
    """
    ensure_schema()
    conn = connect()
    existing = conn.execute(
        "SELECT document_number, revision, effective_date"
        " FROM document_classification WHERE document_id = ?",
        (document_id,)).fetchone()
    if existing is None:
        return {"document_id": document_id, "attempted": False,
                "reason": "no classification row"}
    pages = [dict(r) for r in conn.execute(
        "SELECT page_no, text FROM pages WHERE document_id = ?"
        " ORDER BY page_no", (document_id,))]
    if not pages:
        return {"document_id": document_id, "attempted": False,
                "reason": "no page text ingested"}
    meta = extract_cover_metadata(pages)

    assignments: list[str] = []
    params: list[object] = []
    result: dict = {"document_id": document_id, "attempted": True}

    if existing["document_number"] is None and meta.document_number is not None:
        family = family_from_identifier(meta.document_number.value)
        assignments += ["document_number = ?", "standard_family = ?",
                        "document_number_evidence = ?"]
        params += [meta.document_number.value, family, _evidence_json(
            meta.document_number, method="cover_page_match")]
        result["document_number"] = meta.document_number.value
        result["document_number_page"] = meta.document_number.page

    if existing["revision"] is None and meta.revision is not None:
        assignments += ["revision = ?", "revision_evidence = ?"]
        params += [meta.revision.value, _evidence_json(
            meta.revision, method="cover_page_match")]
        result["revision"] = meta.revision.value
        result["revision_page"] = meta.revision.page

    if existing["effective_date"] is None and meta.effective_date is not None:
        assignments += ["effective_date = ?", "effective_date_evidence = ?"]
        params += [meta.effective_date.value, _evidence_json(
            meta.effective_date, method="cover_page_match")]
        result["effective_date"] = meta.effective_date.value
        result["effective_date_page"] = meta.effective_date.page

    if not assignments:
        result["changed"] = False
        return result
    with conn:
        conn.execute(
            f"UPDATE document_classification SET {', '.join(assignments)}"
            " WHERE document_id = ?", [*params, document_id])
    result["changed"] = True
    return result


def _evidence_json(field: CoverField, *, method: str) -> str:
    import json
    return json.dumps({"page": field.page, "quote": field.quote,
                       "method": method})


# ------------------------------------------------------------- inventory read

def _cited_identifiers(*, allowed_document_ids: frozenset[str]) -> set[str]:
    """Every standard identifier's NORMALISED key cited by any
    CONTRACTOR_SUBMITTAL the caller may read - the union `applicability.py`
    computes per submittal, taken here across every submittal at once."""
    from .applicability import normalise_identifier

    if not allowed_document_ids:
        return set()
    marks = ",".join("?" for _ in allowed_document_ids)
    rows = connect().execute(
        f"""SELECT ch.text FROM chunks ch
            JOIN document_classification c ON c.document_id = ch.document_id
            WHERE ch.document_id IN ({marks})
              AND c.document_role = 'CONTRACTOR_SUBMITTAL'""",
        sorted(allowed_document_ids)).fetchall()
    text = " ".join(r["text"] or "" for r in rows)
    return {normalise_identifier(ident)
            for ident in datasheets.referenced_standards(text)}


def inventory_rows(*, allowed_document_ids: frozenset[str],
                   include_superseded: bool = True) -> list[dict]:
    """One row per COMPANY_STANDARD the caller may read: family, number,
    revision, effective date, source file hash, licence status, and whether
    any submittal under the caller's own grants cites it.

    `standards.list_standards` already assembles the scoped, permission-
    filtered base rows; this adds the inventory axes on top rather than
    re-deriving the scope query, so the two can never disagree about which
    documents are in scope.
    """
    from .applicability import normalise_identifier, library_identifier

    ensure_schema()
    base = standards.list_standards(
        allowed_document_ids=allowed_document_ids,
        include_superseded=include_superseded)
    if not base:
        return []
    ids = [row["id"] for row in base]
    marks = ",".join("?" for _ in ids)
    extra = {r["document_id"]: dict(r) for r in connect().execute(
        f"""SELECT c.document_id, c.standard_family, c.licence_status,
                   d.sha256
            FROM document_classification c
            JOIN documents d ON d.id = c.document_id
            WHERE c.document_id IN ({marks})""", ids).fetchall()}
    cited = _cited_identifiers(allowed_document_ids=allowed_document_ids)

    out = []
    for row in base:
        info = extra.get(row["id"], {})
        identifier = row.get("document_number") or library_identifier(
            row.get("filename") or "") or ""
        family = info.get("standard_family") or family_from_identifier(identifier)
        licence = info.get("licence_status") or default_licence_status(
            family, held=True)  # a row here is, by construction, held
        key = normalise_identifier(identifier)
        out.append({
            **row,
            "standard_family": family,
            "licence_status": licence,
            "source_file_sha256": info.get("sha256"),
            "cited_by_submittal": bool(key) and key in cited,
        })
    return out


# --------------------------------------------------- cited but not held

def _submittal_citations(*, allowed_document_ids: frozenset[str]) -> list[dict]:
    """One row per standard identifier cited by a CONTRACTOR_SUBMITTAL the
    caller may read, attributed to the document it was read from."""
    if not allowed_document_ids:
        return []
    marks = ",".join("?" for _ in allowed_document_ids)
    rows = connect().execute(
        f"""SELECT ch.document_id, d.filename, ch.text FROM chunks ch
            JOIN document_classification c ON c.document_id = ch.document_id
            JOIN documents d ON d.id = ch.document_id
            WHERE ch.document_id IN ({marks})
              AND c.document_role = 'CONTRACTOR_SUBMITTAL'""",
        sorted(allowed_document_ids)).fetchall()
    by_doc: dict[str, dict] = {}
    for row in rows:
        entry = by_doc.setdefault(
            row["document_id"], {"filename": row["filename"], "chunks": []})
        entry["chunks"].append(row["text"] or "")

    out: list[dict] = []
    for document_id, entry in by_doc.items():
        text = " ".join(entry["chunks"])
        for identifier in datasheets.referenced_standards(text):
            out.append({
                "identifier": identifier, "source_type": "submittal",
                "document_id": document_id, "filename": entry["filename"],
            })
    return out


def _requirement_citations(*, allowed_document_ids: frozenset[str]) -> list[dict]:
    """One row per normative reference a COMPANY_STANDARD's own requirement
    text names, attributed to the clause/page it was read from.

    Scoped to NON-SUPERSEDED standards only (`c.superseded_by IS NULL`) - the
    same currency rule `standards.selectable_standard_ids` applies elsewhere:
    a superseded revision's own citations are history, not a live gap to
    report.
    """
    from .requirements_3b import APPLICABILITY_TRIGGER, cited_document

    if not allowed_document_ids:
        return []
    marks = ",".join("?" for _ in allowed_document_ids)
    rows = connect().execute(
        f"""SELECT r.standard_document_id, d.filename, r.clause, r.page,
                   COALESCE(r.source_text, r.requirement_text) AS text
            FROM standard_requirements r
            JOIN document_classification c
                ON c.document_id = r.standard_document_id
            JOIN documents d ON d.id = r.standard_document_id
            WHERE r.standard_document_id IN ({marks})
              AND c.document_role = 'COMPANY_STANDARD'
              AND c.superseded_by IS NULL
              AND r.requirement_type = ?""",
        [*sorted(allowed_document_ids), APPLICABILITY_TRIGGER]).fetchall()

    out: list[dict] = []
    for row in rows:
        identifier = cited_document(row["text"] or "")
        if identifier is None:
            continue
        out.append({
            "identifier": identifier, "source_type": "requirement",
            "document_id": row["standard_document_id"],
            "filename": row["filename"], "clause": row["clause"],
            "page": row["page"],
        })
    return out


def cited_but_not_held(*, allowed_document_ids: frozenset[str]) -> list[dict]:
    """Every standard cited by a submittal or a SAES requirement that is NOT
    in the local library, with where it was cited - the missing list for
    the CRS and for the owner to take to the standards body.

    ONE HOME FOR THE MATCHING RULE, reusing `applicability._match_referenced`
    exactly as `applicability.missing_references` does (that function's own
    docstring: two independent copies of this rule disagreed about whether a
    submittal citation was a document id or an identifier, and one of them
    reported six held standards as missing). Matching here is by-name against
    the SAME held library `standards.list_standards` returns, so a standard
    reported "cited but not held" here can never be one this system actually
    has under a different key.

    Each returned row groups every citation for the SAME cited identifier
    (a standard can be cited by more than one submittal, or by more than one
    requirement) under one entry, listing every place it was cited - never
    one row per citation, which would make "3 mentions of API 610" look like
    three different missing standards.
    """
    from .applicability import _match_referenced, normalise_identifier

    library = standards.list_standards(
        allowed_document_ids=allowed_document_ids, include_superseded=True)
    citations = (
        _submittal_citations(allowed_document_ids=allowed_document_ids)
        + _requirement_citations(allowed_document_ids=allowed_document_ids))

    by_key: dict[str, dict] = {}
    for citation in citations:
        identifier = citation["identifier"]
        key = normalise_identifier(identifier)
        if not key:
            continue
        matched = _match_referenced(library, [identifier])
        if matched:
            continue  # held - not a gap
        entry = by_key.setdefault(key, {
            "identifier": identifier,
            "standard_family": family_from_identifier(identifier),
            "licence_status": default_licence_status(
                family_from_identifier(identifier), held=False),
            "cited_by": [],
        })
        entry["cited_by"].append({
            k: v for k, v in citation.items() if k != "identifier"})

    return sorted(by_key.values(), key=lambda e: e["identifier"])
