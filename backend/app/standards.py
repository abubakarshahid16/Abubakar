"""The Standards Library: clause hierarchy, atomic requirements, revisions.

WHAT THIS MODULE IS NOT

It is not a second index and not a second retrieval path. A COMPANY_STANDARD
PDF already goes through the whole pipeline - it is chunked, it is in
`chunks_fts`, and it is embedded in `chunk_vectors`. This module is a LAYER
POINTING INTO THOSE CHUNKS. `standard_requirements.chunk_id` is the pointer.

A parallel store would duplicate retrieval and, worse, bypass the
`allowed_document_ids` masking that only the existing path enforces - the
masking is applied to the score vector before top-k precisely so the size of
the shrinkage cannot disclose how much matching material exists in documents
the caller cannot read. A second store would have none of that.

It is also not a second clause parser. `chunker.looks_like_heading`,
`_validate_heading`, `plausible_heading_numbers` and `segment_document` already
decide what a clause heading is, strictly, and the result is already stored on
`chunks.section`. This module reads that column. What it adds is the HIERARCHY
- parent clause, depth - which the chunker has no reason to compute.

THE LIBRARY IS LOGICALLY SEPARATE AND PHYSICALLY THE SAME DATABASE. One SQLite
file, one set of grant tables, one retrieval path. "Separate library" is a
statement about what a reader sees, never about where the bytes live.

WHAT IS DELIBERATELY ABSENT (phase 3B)

No conditions, exceptions, numeric limits, units, operators, requirement
normalisation, applicability tags or conflicting-standard handling. The table
has no columns for them and none are added here; 3B will ALTER it. Half a
numeric limit is worse than none: a requirement that carries `value: 90` with
no operator reads as a limit and is not one.

`confirmed_by` and `confirmed_at` already exist from phase 1, so 3B's
verification queue has its storage waiting - this phase writes neither.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone

from . import claims, submittal_review
from .db import connect

#: Mandatory wording. A requirement is a sentence that OBLIGES something.
#:
#: `should` is deliberately absent: it is a RECOMMENDATION, and recording it as
#: a requirement would manufacture non-compliance against advice. `may` is
#: permission. Both are 3B's problem if they are anyone's - this phase records
#: obligations only and says so.
_MANDATORY = re.compile(
    r"\b(shall|must|is\s+required\s+to|are\s+required\s+to|is\s+to\s+be"
    r"|are\s+to\s+be)\b",
    re.IGNORECASE,
)

#: A negated obligation is still an obligation, and is kept because "shall not
#: be painted" is a requirement whose violation is a real finding.
_PROHIBITION = re.compile(r"\bshall\s+not\b|\bmust\s+not\b", re.IGNORECASE)

#: Below this, a requirement is presented as AWAITING VERIFICATION rather than
#: as a fact. The number is a threshold on a heuristic, not a measurement, and
#: it is named here so it has exactly one home.
VERIFICATION_THRESHOLD = 0.75

#: A sentence shorter than this is a fragment - a table cell, a heading that
#: happened to contain "shall" - not a requirement anyone can comply with.
MIN_REQUIREMENT_WORDS = 5

#: The role a document must hold before this module will touch it.
COMPANY_STANDARD = "COMPANY_STANDARD"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit(action: str, actor: dict | None, resource_id: str | None,
           detail: str | None = None, outcome: str = "ok") -> None:
    """Durable record of a standards decision.

    The same shape as `admin._audit` and written directly rather than imported:
    `admin` resolves identity through `auth` and pulls the whole admin surface
    in with it, which is the same reason `access.py` declines to import it.
    Four modules in this codebase already write this row directly.

    `detail` carries IDS AND CLAUSE NUMBERS ONLY. Never requirement text, never
    a document title - the audit table is the one most likely to be exported.

    An unwritable audit must not block the change it describes, so the failure
    is swallowed, exactly as the admin helper does.
    """
    conn = connect()
    try:
        with conn:
            conn.execute(
                """INSERT INTO audit_events
                       (at, actor_user_id, actor_username, action,
                        resource_type, resource_id, outcome, detail)
                   VALUES (?, ?, ?, ?, 'standard', ?, ?, ?)""",
                (_now(), (actor or {}).get("id"),
                 ((actor or {}).get("email") or "unauthenticated")[:200],
                 action, resource_id, outcome, detail),
            )
    except Exception:  # noqa: BLE001 - an unwritable audit must not block the change
        pass


def _scope_clause(allowed_document_ids: frozenset[str], column: str) -> tuple[str, list[str]]:
    """A WHERE fragment restricting `column` to the caller's grants.

    `submittal_review._scope_clause`'s rule, restated for this module's
    queries: an EMPTY set means the caller is granted nothing and resolves to
    `1 = 0`, never to "no restriction". There is no `None` meaning corpus-wide.
    """
    if not allowed_document_ids:
        return " WHERE 1 = 0", []
    marks = ",".join("?" for _ in allowed_document_ids)
    return f" WHERE {column} IN ({marks})", sorted(allowed_document_ids)


# ------------------------------------------------------------ clause hierarchy

def clause_number(section: str | None) -> str | None:
    """The clause number off a `chunks.section` value, or None.

    `chunks.section` is a validated heading - "5.3.3 Coating systems" - because
    `chunker._validate_heading` refused everything that was not one. The number
    is the first token, which is exactly what `chunker._heading_number` takes.

    NEVER GUESSED. A chunk with no section yields None, and a requirement read
    from it is recorded with a null clause and a low confidence rather than
    being attached to whichever clause happened to precede it. An inherited
    clause number is a citation that resolves to the wrong place, which is
    worse than one that says it does not know.
    """
    if not section:
        return None
    head = section.split(" ", 1)[0].strip().rstrip(".")
    if not head:
        return None
    parts = [p for p in head.split(".") if p]
    # It came through _validate_heading, so it is digits with at most one
    # single-letter annex prefix. Re-checked rather than trusted: this function
    # is also reachable from a hand-written section on an older row.
    if not parts or not any(p.isdigit() for p in parts):
        return None
    return head


def parent_clause(clause: str | None) -> str | None:
    """`5.3.3` -> `5.3`, `5` -> None, `A.4` -> `A`.

    A top-level clause has no parent, and that is a real answer rather than a
    missing one: it is the root of the hierarchy.
    """
    if not clause:
        return None
    parts = [p for p in clause.split(".") if p]
    if len(parts) <= 1:
        return None
    return ".".join(parts[:-1])


def clause_depth(clause: str | None) -> int | None:
    if not clause:
        return None
    return len([p for p in clause.split(".") if p])


def clause_hierarchy(document_id: str, *, allowed_document_ids: frozenset[str]) -> list[dict]:
    """The clause structure of one standard, read from its chunks.

    One row per distinct clause, with its parent, the page it starts on and the
    chunk it was read from - so every clause in the library resolves to a real
    passage a reader can open.

    Ordered by page then by the chunk's ordinal, which is the document's own
    order. Sorting by clause number as a STRING would put 5.10 before 5.9, and
    sorting it numerically would impose an order the document may not have.
    """
    where, args = _scope_clause(allowed_document_ids, "document_id")
    rows = connect().execute(
        "SELECT id, section, page_start, ordinal FROM chunks" + where +
        " AND document_id = ? AND section IS NOT NULL"
        " ORDER BY page_start, ordinal", [*args, document_id],
    ).fetchall()
    seen: dict[str, dict] = {}
    for row in rows:
        clause = clause_number(row["section"])
        if clause is None or clause in seen:
            continue
        seen[clause] = {
            "clause": clause,
            "parent_clause": parent_clause(clause),
            "depth": clause_depth(clause),
            "title": row["section"].split(" ", 1)[1].strip()
                     if " " in row["section"] else None,
            "page": row["page_start"],
            "chunk_id": row["id"],
        }
    return list(seen.values())


# --------------------------------------------------------------- requirements

class RequirementError(ValueError):
    """A requirement could not be created. Carries a reason, never a row."""


def _confidence(clause: str | None, sentence: str) -> float:
    """How far this row should be trusted before a human has looked at it.

    A HEURISTIC, AND LABELLED AS ONE. It is not a probability and nothing
    treats it as one: its only job is to decide whether a row is presented as a
    requirement or as something awaiting verification.

    Two things lower it, and both are about whether the CITATION resolves
    rather than about whether the sentence is well written:
      * no clause number - the row cannot say where in the standard it came
        from, only which page;
      * a weak obligation - "is to be" is an obligation in some drafting and a
        description of intent in others.
    """
    score = 0.9
    if clause is None:
        # The dominant term. A requirement that cannot name its clause is the
        # case this threshold exists for.
        score -= 0.3
    if not re.search(r"\b(shall|must)\b", sentence, re.IGNORECASE):
        score -= 0.2
    return round(max(0.1, min(1.0, score)), 2)


def needs_verification(row: dict | sqlite3.Row) -> bool:
    """True while a human has not confirmed a row this module is unsure of.

    Confirmation wins over confidence: once `confirmed_by` is set the row is a
    human's statement, whatever the extractor thought of it. Phase 3A never
    sets it - the queue's storage is waiting for 3B.
    """
    if row["confirmed_by"]:
        return False
    confidence = row["confidence"]
    return confidence is None or confidence < VERIFICATION_THRESHOLD


def create_requirement(
    *, standard_document_id: str, chunk_id: str, requirement_text: str,
    source_text: str, clause: str | None, page: int | None,
    extraction_method: str = "extracted", confidence: float | None = None,
    category: str | None = None,
) -> dict:
    """Write one requirement. REFUSES a row whose citation does not resolve.

    The enforcement is here rather than in the schema because the column was
    added by ALTER, and SQLite cannot add a column with a foreign key to an
    existing table - so a migrated database has no constraint to lean on. This
    check holds on both.

    What "resolves" means, precisely: the chunk exists, it belongs to the
    standard being written about, and the page recorded is a page that chunk
    actually spans. A chunk id from another document would be a citation that
    opens something real and wrong, which is the worst of the three failures.
    """
    submittal_review.ensure_schema()
    if not requirement_text.strip():
        raise RequirementError("a requirement with no text is not a requirement")
    chunk = connect().execute(
        "SELECT id, document_id, page_start, page_end FROM chunks WHERE id = ?",
        (chunk_id,),
    ).fetchone()
    if chunk is None:
        raise RequirementError(f"no chunk {chunk_id!r}: the citation does not resolve")
    if chunk["document_id"] != standard_document_id:
        raise RequirementError(
            "the cited chunk belongs to a different document - a citation that "
            "opens the wrong passage is worse than one that opens nothing")
    if page is not None and not (chunk["page_start"] <= page <= chunk["page_end"]):
        raise RequirementError(
            f"page {page} is outside the cited chunk "
            f"({chunk['page_start']}-{chunk['page_end']})")

    now = _now()
    row = {
        "id": str(uuid.uuid4()),
        "standard_document_id": standard_document_id,
        "clause": clause,
        "page": page if page is not None else chunk["page_start"],
        "chunk_id": chunk_id,
        "requirement_text": requirement_text.strip(),
        "source_text": source_text.strip(),
        "category": category,
        "extraction_method": extraction_method,
        "confidence": confidence,
        "created_at": now,
        "updated_at": now,
    }
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO standard_requirements
               (id, standard_document_id, clause, page, chunk_id,
                requirement_text, source_text, category, extraction_method,
                confidence, created_at, updated_at)
               VALUES (:id, :standard_document_id, :clause, :page, :chunk_id,
                       :requirement_text, :source_text, :category,
                       :extraction_method, :confidence, :created_at,
                       :updated_at)""", row)
    return row


def extract_requirements(
    document_id: str, *, allowed_document_ids: frozenset[str],
    actor: dict | None = None, replace: bool = True,
) -> dict:
    """Read one standard's chunks and record every obligation it states.

    EXTRACTION IS A GUESS AND STAYS LABELLED ONE. Every row is written with
    `extraction_method='extracted'` and `confirmed_by` NULL, so nothing here
    can be mistaken for a human's statement. CLAUDE.md rule 4.

    It reads the EXISTING chunks - the ones retrieval already searches - so a
    requirement's citation and a chat answer's citation point at the same
    passage. Chunks are read under the caller's grants like every other read
    in this module.

    `replace` re-runs cleanly: a standard's previous extraction is deleted
    first, because running it twice must not double every requirement.
    CONFIRMED ROWS ARE NEVER DELETED - once 3B lets a human confirm one,
    re-extracting must not silently discard their decision.
    """
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "document_id")
    chunks = connect().execute(
        "SELECT id, section, page_start, page_end, text FROM chunks" + where +
        " AND document_id = ? AND retrievable = 1 ORDER BY ordinal",
        [*args, document_id],
    ).fetchall()

    if replace:
        conn = connect()
        with conn:
            conn.execute(
                "DELETE FROM standard_requirements"
                " WHERE standard_document_id = ? AND confirmed_by IS NULL",
                (document_id,))

    written = 0
    low_confidence = 0
    for chunk in chunks:
        clause = clause_number(chunk["section"])
        for sentence in claims.split_sentences(chunk["text"]):
            if not _MANDATORY.search(sentence):
                continue
            if len(sentence.split()) < MIN_REQUIREMENT_WORDS:
                # A heading or a table cell that happens to contain "shall".
                continue
            confidence = _confidence(clause, sentence)
            try:
                create_requirement(
                    standard_document_id=document_id,
                    chunk_id=chunk["id"],
                    # The requirement text IS the verbatim sentence in this
                    # phase. They are separate columns because 3B will
                    # normalise one and must not lose the other - a paraphrase
                    # that replaces its source is a claim with no citation.
                    requirement_text=sentence,
                    source_text=sentence,
                    clause=clause,
                    page=chunk["page_start"],
                    extraction_method="extracted",
                    confidence=confidence,
                    category="prohibition" if _PROHIBITION.search(sentence) else None,
                )
            except RequirementError:
                # A chunk that vanished between the read and the write. Skipped
                # rather than written without a resolving citation.
                continue
            written += 1
            if confidence < VERIFICATION_THRESHOLD:
                low_confidence += 1

    _audit("standard.requirements_extracted", actor, document_id,
           detail=f"chunks={len(chunks)} requirements={written} "
                  f"awaiting_verification={low_confidence}")
    return {
        "document_id": document_id,
        "chunks_read": len(chunks),
        "requirements": written,
        "awaiting_verification": low_confidence,
    }


def list_requirements(
    document_id: str, *, allowed_document_ids: frozenset[str],
) -> list[dict]:
    """One standard's requirements, under the caller's grants.

    Joined to `chunks` so every row carries the page and section it resolves
    to - and so a requirement whose chunk has gone is visible as such rather
    than silently dropped by an inner join.
    """
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "r.standard_document_id")
    rows = connect().execute(
        "SELECT r.*, c.page_start AS chunk_page, c.section AS chunk_section"
        " FROM standard_requirements r"
        " LEFT JOIN chunks c ON c.id = r.chunk_id" + where +
        " AND r.standard_document_id = ?"
        " ORDER BY r.page, r.clause, r.created_at", [*args, document_id],
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["needs_verification"] = needs_verification(row)
        item["citation_resolves"] = row["chunk_page"] is not None
        out.append(item)
    return out


# ----------------------------------------------------------------- the library

def list_standards(*, allowed_document_ids: frozenset[str],
                   include_superseded: bool = True) -> list[dict]:
    """Every COMPANY_STANDARD the caller may read.

    Filtered IN THE QUERY, on the document id, against the caller's grants -
    `metrics._where`'s rule, and the reason it matters here is that this list
    is paginated by the UI: dropping rows in Python after a LIMIT is the leak
    /api/documents already documents.

    THE ROLE IS A CLASSIFICATION, NOT A GRANT. `document_role` decides what
    appears in the library; `allowed_document_ids` decides what the caller may
    see. The two are ANDed, so the library can only ever be a subset of what
    the caller already holds - intersection, never union (CLAUDE.md rule 5).

    A standard with no requirements yet reports `requirements: 0`. Zero is a
    real answer and the UI must render it as "none extracted", never as
    "none required" and never as readiness.
    """
    where, args = _scope_clause(allowed_document_ids, "d.id")
    sql = (
        "SELECT d.id, d.filename, d.status, d.page_count, d.uploaded_at,"
        "       c.title, c.document_number, c.revision, c.effective_date,"
        "       c.discipline, c.superseded_by,"
        "       (SELECT COUNT(*) FROM standard_requirements r"
        "         WHERE r.standard_document_id = d.id) AS requirement_count,"
        "       (SELECT COUNT(*) FROM standard_requirements r"
        "         WHERE r.standard_document_id = d.id"
        "           AND r.confirmed_by IS NULL"
        "           AND (r.confidence IS NULL OR r.confidence < ?)"
        "       ) AS awaiting_verification"
        " FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id" + where +
        " AND c.document_role = ?"
    )
    params: list[object] = [VERIFICATION_THRESHOLD, *args, COMPANY_STANDARD]
    if not include_superseded:
        sql += " AND c.superseded_by IS NULL"
    sql += " ORDER BY c.document_number, c.revision, d.uploaded_at DESC"
    rows = connect().execute(sql, params).fetchall()
    return [{**dict(row), "superseded": row["superseded_by"] is not None}
            for row in rows]


def selectable_standard_ids(*, allowed_document_ids: frozenset[str]) -> frozenset[str]:
    """The standards a review may be run AGAINST.

    THE SUPERSESSION RULE, IN ONE PLACE. A superseded standard is excluded from
    SELECTION and remains fully READABLE and CITABLE - those are different
    questions and this project keeps getting them confused. An engineer must
    still be able to open the revision a submittal was reviewed against last
    year; what must not happen is a new review quietly using it.

    Phase 3B consumes this. It is written here, now, because the rule belongs
    with the data that expresses it rather than with the engine that asks.
    """
    where, args = _scope_clause(allowed_document_ids, "d.id")
    rows = connect().execute(
        "SELECT d.id FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id" + where +
        " AND c.document_role = ? AND c.superseded_by IS NULL",
        [*args, COMPANY_STANDARD],
    ).fetchall()
    return frozenset(row["id"] for row in rows)


def revision_history(document_id: str, *,
                     allowed_document_ids: frozenset[str]) -> list[dict]:
    """Every revision of the same standard NUMBER the caller may read.

    Grouped by `document_number` rather than by a revision chain, because a
    chain built from `superseded_by` alone breaks the moment one link is
    missing - and a missing link is the normal state while a library is being
    populated. The number is what an engineer actually asks by.

    A document with no recorded number has no history to show, and says so by
    returning only itself: inventing a group from the filename would put two
    unrelated standards in one another's history.
    """
    where, args = _scope_clause(allowed_document_ids, "d.id")
    row = connect().execute(
        "SELECT c.document_number FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id" + where +
        " AND d.id = ?", [*args, document_id],
    ).fetchone()
    if row is None:
        # Not readable, or not there. The same answer for both.
        return []
    number = row["document_number"]
    if not number:
        return [r for r in list_standards(allowed_document_ids=allowed_document_ids)
                if r["id"] == document_id]
    return [
        r for r in list_standards(allowed_document_ids=allowed_document_ids)
        if r["document_number"] == number
    ]


def supersede(document_id: str, superseded_by: str | None, *,
              allowed_document_ids: frozenset[str],
              actor: dict | None = None) -> dict:
    """Mark a standard as replaced - or clear the mark when `superseded_by` is
    None.

    BOTH DOCUMENTS MUST BE READABLE BY THE CALLER. Writing a superseding id the
    caller cannot read would let them learn that a document exists by pointing
    at it, and would put an unresolvable id in front of every later reader.

    AUDITED, because it changes which standards a review will select. The audit
    row carries the two ids and nothing else.

    A standard cannot supersede itself: the result would be a document excluded
    from selection with no replacement, which reads as an error nobody can fix.
    """
    submittal_review.ensure_schema()
    if superseded_by is not None:
        if superseded_by == document_id:
            raise RequirementError("a standard cannot supersede itself")
        if superseded_by not in allowed_document_ids:
            raise RequirementError("no document with that id")
    if document_id not in allowed_document_ids:
        raise RequirementError("no document with that id")

    conn = connect()
    with conn:
        updated = conn.execute(
            "UPDATE document_classification SET superseded_by = ?"
            " WHERE document_id = ?", (superseded_by, document_id)).rowcount
    if not updated:
        raise RequirementError("that document has no classification to update")
    _audit("standard.superseded" if superseded_by else "standard.supersession_cleared",
           actor, document_id, detail=f"superseded_by={superseded_by}")
    return {"document_id": document_id, "superseded_by": superseded_by}
