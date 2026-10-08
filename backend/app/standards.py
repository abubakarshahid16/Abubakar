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

PHASE 3B ADDED THE STRUCTURED SHAPE

Numeric limits, units, conditions, exceptions, applicability tags, the
conflict report and the verification queue. The parsing itself lives in
`requirements_3b.py` and the unit handling in `claims.py`; this module is where
they meet the database.

All of it is DETERMINISTIC AND MODEL-FREE (master plan section 14). A limit
that depends on a language model is a limit nobody can reproduce, and the point
of reading a standard once is that the answer is stable.

`confirmed_by` and `confirmed_at` came from phase 1 and are now written by
`decide_requirement`, which is what turns a machine's guess into a person's
statement.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from . import chunker, claims, classification, orphan_guard, provenance, requirements_3b
from . import submittal_review
from . import tables as tables_mod
from .db import connect

#: Mandatory wording. A requirement is a sentence that OBLIGES something.
#:
#: `should` is deliberately absent: it is a RECOMMENDATION, and recording it as
#: a requirement would manufacture non-compliance against advice. `may` is
#: permission. Both are 3B's problem if they are anyone's - this phase records
#: obligations only and says so.
_MANDATORY = re.compile(
    r"\b(shall|must\s+not|must|is\s+required\s+to|are\s+required\s+to"
    r"|is\s+to\s+be|are\s+to\s+be|may\s+not\s+exceed\s+[-+]?\d)",
    re.IGNORECASE,
)

#: A negated obligation is still an obligation, and is kept because "shall not
#: be painted" is a requirement whose violation is a real finding.
_PROHIBITION = re.compile(
    r"\bshall\s+not\b|\bmust\s+not\b|\bmay\s+not\s+exceed\s+[-+]?\d",
    re.IGNORECASE,
)

#: Below this, a requirement is presented as AWAITING VERIFICATION rather than
#: as a fact. The number is a threshold on a heuristic, not a measurement, and
#: it is named here so it has exactly one home.
VERIFICATION_THRESHOLD = 0.75

#: The confidence a limit is held at when it contradicts its own sentence.
#: Below `VERIFICATION_THRESHOLD` on purpose, and stated as its own constant so
#: that raising the threshold can never silently promote a contradicted row
#: into the library.
CONTRADICTED_CONFIDENCE = 0.2

#: A sentence shorter than this is a fragment - a table cell, a heading that
#: happened to contain "shall" - not a requirement anyone can comply with.
MIN_REQUIREMENT_WORDS = 5

# A clause heading found in extracted source, rather than inferred from the
# chunk. This is intentionally narrower than `clause_number`: a sentence that
# merely starts with a quantity such as "90 dB" must never become clause 90.
_INLINE_CLAUSE = re.compile(r"^\s*(?P<clause>\d+(?:\.\d+)+)\b")

# Numbered exception lists often survive PDF extraction as one sentence. Only
# short list labels are candidates; this excludes embedded three-digit
# parenthetical references found in the measured passage.
_NUMBERED_ITEM = re.compile(r"(?<!\w)(?P<number>\d{1,2})[.)]\s+")

#: The role a document must hold before this module will touch it.
COMPANY_STANDARD = "COMPANY_STANDARD"


# ------------------------------------------------- the responsibility header
#
# WHY THE DOCUMENT'S OWN HEADER AND NOT THE LETTER IN ITS NUMBER.
#
# The obvious rule is a letter-to-discipline map: SAES-B is Loss Prevention,
# SAES-W is Welding. Measured against this corpus it is wrong often enough to
# be dangerous - SAES-A alone spans eleven committees (Process Engineering,
# Industrial Drainage, Corrosion Control, Environmental Protection, Energy
# Systems Optimization, Asset Management, Aviation Fuel Quality and more), L
# spans five, P six, K four. A map would assign every one of those a single
# confident value, and `applicability` would then select standards by a
# discipline the document does not belong to.
#
# The header states it. Each standard carries "Document Responsibility: <the
# committee>" on its cover, so the answer is read from the document rather than
# inferred from its name.

#: The header, and everything that could be the value. Bounded at 140
#: characters because the cover page runs straight on into the issue date and
#: the contents list, and `[^:]` stops at the next field's colon - the value
#: itself never contains one.
_RESPONSIBILITY = re.compile(
    r"Document\s+Responsibility\s*:\s*(?P<window>[^:]{0,140})", re.IGNORECASE | re.DOTALL)

#: The usual value: a committee name. DOTALL matters - the cover page wraps
#: "... Standards \nCommittee" on 9 of the documents that carry it, and a
#: pattern that stopped at the newline read those as having no value at all.
_COMMITTEE = re.compile(r"^(?P<value>.{3,90}?Committee)\b", re.IGNORECASE | re.DOTALL)

#: The value when it does NOT end in "Committee" - SAES-A-302's "Aviation Fuel
#: Quality" is the only one in this corpus. Deliberately narrow: letters and
#: ordinary title punctuation, nothing else. A digit here means the cut ran
#: into the issue date or the document number, and a value like
#: "Aviation Fuel Quality 15 March 2021 SAES-A" is worse than no value.
_PLAIN_VALUE = re.compile(r"^[A-Za-z][A-Za-z&.,'\-/ ]{2,60}$")

#: THE FORM THAT MUST NOT BE PARSED, and the reason the colon is required.
#:
#: Four standards mention the phrase only in their revision history: "Editorial
#: revision to transfer document responsibility from the Offshore Structures
#: Standards Committee to the Geotechnical Standards Committee". There is no
#: colon, and reading the first committee named would record the SUPERSEDED
#: owner - a confidently wrong discipline, which is the one outcome worse than
#: none. Those documents are left NULL and listed for a human.


def responsibility_in(text: str) -> list[str]:
    """Every committee named by a `Document Responsibility:` header in `text`.

    Returns a list because a chunk can carry the header more than once - the
    cover block repeats on continuation pages - and the caller decides what to
    do with disagreement rather than this function guessing.
    """
    found = []
    for match in _RESPONSIBILITY.finditer(text or ""):
        window = match.group("window")
        committee = _COMMITTEE.match(window)
        if committee is not None:
            found.append(" ".join(committee.group("value").split()))
            continue
        # No "Committee" in range: take the rest of the LINE only. The cover
        # page separates fields by a line break or a run of spaces, so that is
        # the boundary - not a character count, which would cut a long name in
        # half and store the half.
        head = re.split(r"\s*\n|\s{2,}", window.strip(), maxsplit=1)[0].strip()
        if _PLAIN_VALUE.match(head):
            found.append(" ".join(head.split()))
    return found


def responsibility_of(document_id: str) -> str | None:
    """The committee this standard's own header names, or None.

    THE MOST FREQUENT VALUE WINS, not the first. The header repeats on every
    page of some documents and a single garbled page would otherwise decide
    for the whole standard; when several pages agree and one does not, the
    agreement is the better evidence. A genuine tie returns None rather than
    picking one - two different committees named equally often is a document
    this function does not understand, and NULL says so honestly.
    """
    counts: dict[str, int] = {}
    for row in connect().execute(
            "SELECT text FROM chunks WHERE document_id = ? AND text LIKE"
            " '%Document Responsibility%'", (document_id,)):
        for value in responsibility_in(row["text"]):
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def backfill_disciplines(*, only_if_unset: bool = True) -> dict:
    """Read every standard's header and store the committee as its discipline.

    NEVER A FALLBACK. A document whose header cannot be read is left NULL and
    named in the result. `applicability` treats NULL on either side as "not a
    match" (its docstring says so), so a missing discipline WEAKENS selection
    while a wrong one MISDIRECTS it - and the letter-based guess that would
    fill these in is wrong for whole families of this corpus.

    `equipment_type` is deliberately untouched. No published scheme exists to
    parse it from, and inventing one would put a guess in a column that reads
    like a fact.
    """
    rows = connect().execute(
        "SELECT d.id, d.filename FROM documents d"
        " ORDER BY d.filename").fetchall()
    result = {"documents": len(rows), "set": [], "unchanged": [], "without": []}
    for row in rows:
        value = responsibility_of(row["id"])
        if value is None:
            result["without"].append(row["filename"])
            continue
        changed = classification.set_discipline(
            row["id"], value, only_if_unset=only_if_unset)
        (result["set"] if changed else result["unchanged"]).append(row["filename"])
    return result


# ------------------------------------------------ page furniture and subject

#: The running footer every page of every SAES standard carries. Measured
#: shape, in both orders it occurs in:
#:
#:   "(c)Saudi Arabian Oil Company 2022 Page 4 of 38 Saudi Aramco: Company
#:    General Use"
#:   "Page 2 of 38 (c)Saudi Arabian Oil Company 2022 Saudi Aramco: Company
#:    General Use"
#:
#: It matters because extraction reads CHUNKS, not pages, and a chunk that
#: spans a page break has the footer sitting in the middle of a sentence. The
#: measured result was 38 of 718 requirement rows (5.3%) carrying text like
#: "However, the Page 42 of 57 (c)Saudi Arabian Oil Company, 2022 Saudi
#: Aramco: Company General Use welder performance shall be evaluated" - a
#: quotation that is not what the standard says, in a system whose whole claim
#: is that it quotes the document.
#:
#: The copyright symbol is matched as a non-word character: the extractor
#: decodes it as U+FFFD on this corpus, and hard-coding the replacement
#: character would break on a file that decoded it correctly.
_FOOTER = re.compile(
    r"\s*(?:\W{0,2}\s*Saudi Arabian Oil Company,?\s*\d{4}\s*)?"
    r"Page\s+\d+\s+of\s+\d+\s*"
    r"(?:\W{0,2}\s*Saudi Arabian Oil Company,?\s*\d{4}\s*)?"
    r"(?:Saudi Aramco:\s*Company General Use\s*)?",
    re.IGNORECASE)

#: The same furniture where it appears without a page number beside it.
#: "All rights reserved." is the tail of the same copyright line and arrives
#: on its own when the chunk boundary falls between them, which is how two
#: rows still opened with it after the footer pattern alone was applied.
_FURNITURE = re.compile(
    r"\s*(?:\W{0,2}\s*Saudi Arabian Oil Company,?\s*\d{4}"
    r"|All rights reserved\.?"
    r"|Saudi Aramco:\s*Company General Use)\s*", re.IGNORECASE)


def strip_page_furniture(text: str) -> str:
    """Remove the running header/footer so it cannot land inside a sentence.

    Applied BEFORE sentence splitting, which is the only place it works: once
    the splitter has run, the footer has already joined two half-sentences
    into one wrong sentence and no later cleanup can separate them again.
    """
    cleaned = _FOOTER.sub(" ", text or "")
    cleaned = _FURNITURE.sub(" ", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


#: Leading noise on a subject: a clause number, then any number of articles and
#: modal fragments. Applied repeatedly, because "the a" and "shall be a" both
#: occur once the comparator phrase has been cut away.
_SUBJECT_LEAD = re.compile(
    r"^(?:\d+(?:\.\d+)*\s*|the\s+|a\s+|an\s+|shall\s+be\s+|shall\s+|must\s+be\s+"
    r"|must\s+|is\s+|are\s+|be\s+|of\s+)", re.IGNORECASE)

#: The same fragments where they TRAIL the subject rather than lead it. The
#: comparator pattern cuts at "less than", so "the scale density shall be less
#: than 50 g/m2" leaves "scale density shall be" - a subject with a dangling
#: verb, which reads as a truncation rather than as a thing.
_SUBJECT_TAIL = re.compile(
    r"(?:\s+(?:shall|must|is|are|be|being|of|with|to|a|an|the))+$", re.IGNORECASE)


def subject_of(sentence: str) -> str | None:
    """What the clause is ABOUT, in the document's own words. Never a join key.

    THIS IS NOT `field` AND MUST NOT BECOME IT. `comparison._match_fact` joins
    on `field` by exact equality against a datasheet's normalised caption, and
    measured over this corpus the phrase before the operator is a descriptive
    clause - "the material stress in the bottom parts of the vessel" - which
    no caption will ever equal. Writing these into `field` would make the
    column look populated while matching nothing, which is worse than the
    honest NULL it holds now.

    So this is for a person reading the requirements list, and for nothing
    else. It is allowed to be long, and it is allowed to be imperfect.
    """
    head = requirements_3b.subject_phrase(strip_page_furniture(sentence))
    if not head:
        return None
    # The last comma-separated part: "In outdoor plant areas, equipment shall
    # be..." is about the equipment, not about outdoor plant areas.
    head = head.split(",")[-1].strip()
    previous = None
    while head and head != previous:
        previous = head
        head = _SUBJECT_LEAD.sub("", head, count=1).strip()
    previous = None
    while head and head != previous:
        previous = head
        head = _SUBJECT_TAIL.sub("", head).strip()
    head = head.strip(" .;:")
    # A subject of one or two characters is a fragment, not a subject.
    return head if len(head) > 2 else None


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

    P5: NO LONGER SWALLOWED. It used to be "an unwritable audit must not block
    the change it describes", which let a supersession or an engineer's
    requirement decision stand with no record of who made it. A failure now
    raises; the caller's request fails loudly instead of succeeding silently.
    """
    conn = connect()
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


def _requirement_parts(sentence: str) -> list[str]:
    """Return atomic numbered obligations when extraction joined a list.

    Splitting is deliberately gated on a complete 1..N sequence with at least
    two items. A lone numbered reference or a non-sequential group is returned
    unchanged. The list marker remains in `source_text`, preserving the exact
    extracted evidence.
    """
    markers = list(_NUMBERED_ITEM.finditer(sentence))
    numbers = [int(marker.group("number")) for marker in markers]
    if len(markers) < 2 or numbers != list(range(1, len(markers) + 1)):
        return [sentence]

    parts: list[str] = []
    prefix = sentence[:markers[0].start()].strip()
    if prefix:
        parts.append(prefix)
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(sentence)
        part = sentence[marker.start():end].strip()
        if part:
            parts.append(part)
    return parts


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
    category: str | None = None, structured: dict | None = None,
    extractor_version: str | None = None, input_hash: str | None = None,
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
        # #177 provenance - see `provenance.py`. NULL for a row no extractor
        # wrote (a human's, or a test's).
        "extractor_version": extractor_version,
        "input_hash": input_hash,
        "created_at": now,
        "updated_at": now,
    }
    # Phase 3B's structured shape. Absent keys stay NULL, which is what an
    # unrecognised limit looks like - never 0, and never a requirement_type
    # invented for text the parser did not understand.
    structured = structured or {}
    for key in ("requirement_type", "field", "operator", "value", "unit",
                "raw_value", "raw_unit", "condition", "exceptions",
                "discipline", "table_row", "subject", "required_evidence_type"):
        row[key] = structured.get(key)
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO standard_requirements
               (id, standard_document_id, clause, page, chunk_id,
                requirement_text, source_text, category, extraction_method,
                confidence, created_at, updated_at,
                requirement_type, field, operator, value, unit,
                raw_value, raw_unit, condition, exceptions, discipline,
                table_row, subject, required_evidence_type,
                extractor_version, input_hash)
               VALUES (:id, :standard_document_id, :clause, :page, :chunk_id,
                       :requirement_text, :source_text, :category,
                       :extraction_method, :confidence, :created_at,
                       :updated_at,
                       :requirement_type, :field, :operator, :value, :unit,
                       :raw_value, :raw_unit, :condition, :exceptions,
                       :discipline, :table_row, :subject,
                       :required_evidence_type,
                       :extractor_version, :input_hash)""", row)
    return row


def extract_requirements(
    document_id: str, *, allowed_document_ids: frozenset[str],
    actor: dict | None = None, replace: bool = True,
    acknowledge_orphaned_findings: bool = False,
) -> dict:
    """Read one standard's chunks and record every obligation it states.

    B38: with replace=True, a re-extraction that would delete rows review
    findings cite is RECORDED and REFUSED unless
    `acknowledge_orphaned_findings` - see `orphan_guard`.

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
        "SELECT id, section, page_start, page_end, text, kind FROM chunks" + where +
        " AND document_id = ? AND retrievable = 1 ORDER BY ordinal",
        [*args, document_id],
    ).fetchall()
    # The discipline this standard is classified under, stamped on every
    # requirement it yields. An applicability tag, not a grant: it says what
    # the requirement is ABOUT, and the grant tables still decide who may read
    # it (CLAUDE.md rule 5).
    classification = connect().execute(
        "SELECT discipline, equipment_type, service FROM document_classification"
        " WHERE document_id = ?", (document_id,)).fetchone()
    discipline = classification["discipline"] if classification else None
    # #177 PROVENANCE: the code that reads the clauses and exactly what it
    # read - the stored file's hash plus every chunk's text, in order. See
    # `provenance.py`.
    stored = connect().execute(
        "SELECT sha256 FROM documents WHERE id = ?", (document_id,)).fetchone()
    extractor_version = provenance.code_version(
        "standards", "requirements_3b", "claims")
    inputs = provenance.input_hash(
        stored["sha256"] if stored else None, *(c["text"] for c in chunks))

    if replace:
        orphan_guard.check(
            "re_extraction",
            requirement_where="standard_document_id = ? AND confirmed_by IS NULL",
            params=(document_id,), document_id=document_id,
            acknowledge=acknowledge_orphaned_findings, actor=actor)
        conn = connect()
        with conn:
            conn.execute(
                "DELETE FROM standard_requirements"
                " WHERE standard_document_id = ? AND confirmed_by IS NULL",
                (document_id,))

    written = 0
    low_confidence = 0
    contradicted = 0
    #: (clause, sentence) already written for THIS document. The same clause
    #: repeats across chunks when a page break splits it and both halves carry
    #: the full sentence, which produced 54 of 762 rows (7.1%) that were
    #: byte-identical to another row. A duplicate requirement is not a second
    #: requirement: it double-counts in every total, and an engineer resolving
    #: findings sees the same clause twice with no way to tell which is which.
    #:
    #: Skipped BEFORE the write rather than deleted after, so the count this
    #: function reports is the count of rows that exist.
    seen: set[tuple[str | None, str]] = set()
    # SEEDED WITH THE ROWS THAT SURVIVED `replace`. Only unconfirmed rows are
    # deleted above, so a requirement a human has CONFIRMED is still there -
    # and re-extracting its sentence would write a second, unconfirmed copy
    # beside it. Every re-run would add another, and since every fix to this
    # extractor is delivered by re-running it, a confirmed requirement would
    # accumulate duplicates for as long as the system is maintained.
    #
    # The confirmed row IS that requirement. Finding it here means the sentence
    # is already recorded, by someone whose decision outranks this parse.
    seen.update(
        (r["clause"], r["requirement_text"])
        for r in connect().execute(
            "SELECT clause, requirement_text FROM standard_requirements"
            " WHERE standard_document_id = ?", (document_id,)))
    for chunk in chunks:
        if chunker.is_revision_history(chunk["section"]):
            # A record of what changed between revisions states no obligation:
            # "No CSD recommendation is required to conduct retroactive PMI
            # testing" in a Summary of Changes describes a deleted paragraph,
            # and read as a requirement it said the opposite of the standard.
            continue
        clause = clause_number(chunk["section"])
        # The running footer is removed BEFORE splitting. After the split it is
        # already inside a sentence, having joined the tail of one page to the
        # head of the next.
        for joined_sentence in claims.split_sentences(strip_page_furniture(chunk["text"])):
            # Some extracted chunks begin under an earlier section but retain
            # later clause headings in their text. Track only an explicit
            # dotted heading and only within this chunk; never inherit context
            # from another chunk or manufacture a clause from a bare number.
            inline_clause = _INLINE_CLAUSE.match(joined_sentence)
            if inline_clause:
                clause = inline_clause.group("clause")
            for sentence in _requirement_parts(joined_sentence):
                if not _MANDATORY.search(sentence):
                    continue
                if len(sentence.split()) < MIN_REQUIREMENT_WORDS:
                    # A heading or a table cell that happens to contain "shall".
                    continue
                key = (clause, sentence)
                if key in seen:
                    continue
                seen.add(key)
                confidence = _confidence(clause, sentence)
                # Phase 3B: the structured shape, parsed deterministically. A
                # sentence with no recognisable limit becomes a `statement`, which
                # is a true description of it rather than a numeric_limit with a
                # null value - a shape that reads as a limit nobody recorded.
                limit = requirements_3b.parse_limit(sentence)
                # THE SELF-AUDIT. A limit that points the opposite way to its
                # own sentence is the one failure a reviewer cannot catch by
                # checking the citation, because the citation is correct. It
                # is not dropped - dropping it would lose a real obligation
                # and say nothing - it is held below the verification
                # threshold, so it reaches a human as something to confirm
                # rather than the library as a rule to compare against.
                if requirements_3b.contradicts_source(limit, sentence):
                    confidence = min(confidence, CONTRADICTED_CONFIDENCE)
                    contradicted += 1
                exceptions = requirements_3b.parse_exceptions(sentence)
                structured = {
                    "requirement_type": requirements_3b.classify(sentence, limit),
                    "condition": requirements_3b.parse_condition(sentence),
                    "exceptions": requirements_3b.encode_exceptions(exceptions),
                    "discipline": discipline,
                    # Descriptive, for a human reading the list. NOT `field` - see
                    # `subject_of`, which explains at length why these two must not
                    # become the same column.
                    "subject": subject_of(sentence),
                    "required_evidence_type": requirements_3b.required_evidence_type(sentence),
                    **(limit or {}),
                }
                try:
                    create_requirement(
                        standard_document_id=document_id,
                        chunk_id=chunk["id"],
                        structured=structured,
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
                        extractor_version=extractor_version,
                        input_hash=inputs,
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
                  f"awaiting_verification={low_confidence} "
                  f"contradicted_source={contradicted}")
    return {
        "document_id": document_id,
        "chunks_read": len(chunks),
        "requirements": written,
        "awaiting_verification": low_confidence,
        # Reported separately from `awaiting_verification`, which it is a
        # subset of. A run where this is not zero has found the failure class
        # that cost this corpus 129 rows, and folding it into a larger number
        # would hide exactly the thing worth looking at.
        "contradicted_source": contradicted,
    }


def extract_table_values(
    document_id: str, *, allowed_document_ids: frozenset[str],
    actor: dict | None = None,
) -> dict:
    """Record one requirement per numeric cell of every parsed table.

    TABLES FIRST, because a requirement set built from the sentences and none
    of the tables looks complete and is missing the numbers an engineer checks
    against. A standard states its noise criterion curves, octave band levels
    and permissible exposure durations in tables, not in prose.

    Each row becomes `table_value` requirements: the row label is the subject,
    the column header is the field, the header's parenthesised spelling is the
    unit, and the cell is the value. Every one carries the chunk id and page of
    the table it came from, so it resolves exactly as a sentence-derived
    requirement does.

    AN UNPARSED TABLE PRODUCES NOTHING AND IS COUNTED. It lowers completeness
    rather than passing silently - see `tables.completeness`.
    """
    submittal_review.ensure_schema()
    parses = tables_mod.parse_document_tables(
        document_id, allowed_document_ids=allowed_document_ids)
    # #177 PROVENANCE, as in `extract_requirements`: the table parser is part
    # of this extractor's code, and the parsed cells are what it read.
    stored = connect().execute(
        "SELECT sha256 FROM documents WHERE id = ?", (document_id,)).fetchone()
    extractor_version = provenance.code_version("standards", "tables", "requirements_3b")
    inputs = provenance.input_hash(
        stored["sha256"] if stored else None,
        *("\x1e".join("\x1f".join(c or "" for c in row) for row in (p.rows or []))
          for p in parses))
    written = 0
    for parse in parses:
        if not parse.parsed or len(parse.rows) < 2:
            continue
        header = parse.columns
        for row_index, row in enumerate(parse.rows[1:], start=1):
            label = (row[0] if row else "").strip()
            if not label:
                continue
            for column_index, cell in enumerate(row[1:], start=1):
                if column_index >= len(header):
                    continue
                raw_value = (cell or "").strip()
                # A cell that is not a number is not a value. A label repeated
                # in a data column, an empty cell, a footnote marker - none of
                # them is a limit, and recording one would invent a
                # requirement out of formatting.
                if requirements_3b.cell_value(raw_value) is None:
                    continue
                column = header[column_index]
                unit = requirements_3b.header_unit(column)
                measurement = requirements_3b.measure(raw_value, unit)
                field = requirements_3b.field_name("", column)
                try:
                    create_requirement(
                        standard_document_id=document_id,
                        chunk_id=parse.chunk_id,
                        requirement_text=f"{label} - {column}: {raw_value}",
                        source_text=f"{label} | {column} | {raw_value}",
                        clause=None, page=parse.page,
                        extraction_method="extracted",
                        # A table cell carries no obligation word, so it is
                        # recorded at the verification threshold: a human
                        # decides whether this number is a requirement or a
                        # reference value. It is never presented as confirmed.
                        confidence=0.5,
                        structured={
                            "requirement_type": "table_value",
                            "field": field,
                            "condition": label,
                            "raw_value": raw_value,
                            "raw_unit": unit,
                            "value": measurement.normalized_value,
                            "unit": measurement.normalized_unit,
                            "table_row": row_index,
                        },
                        extractor_version=extractor_version,
                        input_hash=inputs)
                except RequirementError:
                    continue
                written += 1
    stats = tables_mod.completeness(parses)
    _audit("standard.table_values_extracted", actor, document_id,
           detail=f"tables={stats['tables_total']} parsed={stats['tables_parsed']} "
                  f"values={written}")
    return {"document_id": document_id, "values": written, **stats}


def table_report(document_id: str, *,
                 allowed_document_ids: frozenset[str]) -> dict:
    """Every table of a standard, parsed or explicitly unparsed, with the rate.

    The unparsed ones are the point. `parsed_fraction` is the honest measure of
    how much of a standard's tabular content this system actually read, and it
    is None - not 0 - when the standard has no tables at all.
    """
    parses = tables_mod.parse_document_tables(
        document_id, allowed_document_ids=allowed_document_ids)
    return {
        "document_id": document_id,
        "tables": [p.as_api() for p in parses],
        **tables_mod.completeness(parses),
    }


# ------------------------------------------------- verification queue (3B)

def verification_queue(*, allowed_document_ids: frozenset[str],
                       limit: int = 200) -> list[dict]:
    """Requirements awaiting a human, across every standard the caller may read.

    Filtered IN THE QUERY, and the LIMIT is exactly why that matters: dropping
    unauthorised rows in Python after a limit is the leak /api/documents
    already documents.
    """
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "r.standard_document_id")
    rows = connect().execute(
        "SELECT r.*, c.page_start AS chunk_page FROM standard_requirements r"
        " LEFT JOIN chunks c ON c.id = r.chunk_id" + where +
        " AND r.confirmed_by IS NULL"
        " AND (r.confidence IS NULL OR r.confidence < ?)"
        " ORDER BY r.confidence, r.created_at LIMIT ?",
        [*args, VERIFICATION_THRESHOLD, limit],
    ).fetchall()
    return [{**dict(r), "needs_verification": True,
             "citation_resolves": r["chunk_page"] is not None} for r in rows]


def decide_requirement(
    requirement_id: str, *, decision: str, allowed_document_ids: frozenset[str],
    actor: dict | None = None, edits: dict | None = None,
    acknowledge_orphaned_findings: bool = False,
) -> dict:
    """An engineer's decision on one extracted requirement.

    `decision` is `confirm`, `edit` or `reject`.

    A CORRECTION SETS extraction_method TO 'human'. That is the whole point of
    the column: after this, the row is a person's statement and no longer a
    machine's guess, and nothing downstream may present it as extracted.
    Confirming sets `confirmed_by`/`confirmed_at`, which `needs_verification`
    already reads, so a confirmed row leaves the queue whatever its confidence
    was.

    REJECT DELETES THE ROW. An extraction that is wrong is not evidence of
    anything and leaving it with a flag would put it in front of the next
    reader to judge again. The AUDIT is what survives - the record that
    somebody looked and said no.

    Scoped: a requirement whose standard the caller cannot read is not found,
    and "not found" is the same answer as "not yours".
    """
    submittal_review.ensure_schema()
    if decision not in {"confirm", "edit", "reject"}:
        raise RequirementError(f"unknown decision {decision!r}")
    where, args = _scope_clause(allowed_document_ids, "standard_document_id")
    row = connect().execute(
        "SELECT * FROM standard_requirements" + where + " AND id = ?",
        [*args, requirement_id]).fetchone()
    if row is None:
        raise RequirementError("no requirement with that id")

    conn = connect()
    now = _now()
    if decision == "reject":
        # B38: a rejected row that findings cite would orphan them.
        orphan_guard.check(
            "reject", requirement_where="id = ?", params=(requirement_id,),
            document_id=row["standard_document_id"],
            acknowledge=acknowledge_orphaned_findings, actor=actor)
        with conn:
            conn.execute("DELETE FROM standard_requirements WHERE id = ?",
                         (requirement_id,))
        _audit("standard.requirement_rejected", actor, row["standard_document_id"],
               detail=f"requirement={requirement_id} clause={row['clause']}")
        return {"id": requirement_id, "decision": "reject", "deleted": True}

    fields = {
        "extraction_method": "human",
        "confirmed_by": (actor or {}).get("id"),
        "confirmed_at": now,
        "updated_at": now,
    }
    if decision == "edit":
        for key in ("requirement_text", "clause", "field", "operator", "value",
                    "unit", "raw_value", "raw_unit", "condition",
                    "requirement_type", "discipline"):
            if edits and key in edits:
                fields[key] = edits[key]
        if edits and "exceptions" in edits:
            fields["exceptions"] = requirements_3b.encode_exceptions(
                edits["exceptions"] or [])
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(
            f"UPDATE standard_requirements SET {assignments} WHERE id = ?",
            [*fields.values(), requirement_id])
    _audit(f"standard.requirement_{decision}ed", actor,
           row["standard_document_id"],
           detail=f"requirement={requirement_id} clause={row['clause']}")
    updated = connect().execute(
        "SELECT * FROM standard_requirements WHERE id = ?",
        (requirement_id,)).fetchone()
    return {**dict(updated), "decision": decision}


# ------------------------------------------------- background extraction (3B)
#
# ONE WORKER, NOT A SECOND ONE. Master plan section 24 says one
# ingestion/review worker and one heavy job at a time, and section 24's
# priority list puts "background standard reprocessing" LAST. So extraction
# does not get a thread of its own: it is drained by the existing
# `IngestionWorker` only when no document needs work, which is exactly what
# "lowest priority" means on a single worker.
#
# ONE WORKER BY DESIGN IS NO LONGER ONE WORKER BY LUCK (#177). Until then the
# sentence above was the only protection: the queue was read with a plain
# SELECT, and a second worker on the same database ran every job twice. Jobs
# are now claimed atomically (`next_extraction_job`), so a second worker is a
# capacity decision rather than a correctness bug.
#
# The queue is the EXISTING `jobs` table with a new stage, not a new table -
# master plan section 25: "Do not create a new table if an existing table can
# be safely extended." `jobs` already carries document_id, stage, state and
# timestamps, which is the whole shape needed.

EXTRACTION_STAGE = "extract_requirements"


def enqueue_extraction(document_id: str, *, actor: dict | None = None,
                       priority: int | None = None) -> str:
    """Queue a standard for background extraction. Idempotent per document.

    A second request while one is pending returns the pending job rather than
    stacking another: re-extraction replaces the same rows, so running it twice
    concurrently is work nobody asked for on a machine with 16 GB. A job
    waiting out a retry backoff is pending too (#177). A POISONED one is not:
    poison ends the automatic retries, and an operator asking again is exactly
    how that standard gets another chance.

    PRIORITY (#177), decided at the call site that knows who is waiting: the
    admin Extract route passes INTERACTIVE, because a person pressed a button
    and is watching for the result. The ingestion and classification hooks
    queue every standard that lands, which is backfill, and take the default.
    """
    import uuid as _uuid
    from . import job_queue
    if priority is None:
        priority = job_queue.PRIORITY_BACKFILL
    from .config import config_version
    submittal_review.ensure_schema()
    conn = connect()
    job_id = f"job_{_uuid.uuid4().hex[:12]}"
    now = _now()
    # B11: THE CHECK AND THE INSERT UNDER ONE WRITE LOCK. They were two steps,
    # so two concurrent requests both saw nothing pending and queued two jobs.
    with job_queue.immediate(conn):
        existing = conn.execute(
            "SELECT id FROM jobs WHERE document_id = ? AND stage = ?"
            " AND state IN ('queued','running','retrying')", (document_id, EXTRACTION_STAGE)
        ).fetchone()
        if existing is not None:
            return existing["id"]
        # PROVENANCE AT ENQUEUE: which extractor code and which settings this
        # job's output will come from, on the job row itself.
        conn.execute(
            """INSERT INTO jobs (id, document_id, stage, state, started_at,
                                 updated_at, priority, created_by, code_version,
                                 config_version)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)""",
            (job_id, document_id, EXTRACTION_STAGE, now, now, priority,
             (actor or {}).get("id"),
             provenance.code_version("standards", "tables", "requirements_3b"),
             config_version()))
        job_queue.audit(conn, "job.queued", job_id,
                        actor_user_id=(actor or {}).get("id"),
                        detail=f"stage={EXTRACTION_STAGE}")
    _audit("standard.extraction_queued", actor, document_id, detail=f"job={job_id}")
    return job_id


#: How long an extraction may sit in `running` before it is presumed dead.
#:
#: Extraction is deterministic regex over already-chunked text and takes about
#: a fifth of a second per standard; the whole 272 would finish inside a
#: minute. Fifteen minutes is therefore not a guess at how long the work takes,
#: it is a margin so wide that anything past it cannot be running - while still
#: being short enough that a restart does not leave a queue stalled for a day.
STALE_EXTRACTION_MINUTES = 15


def recover_stale_extraction_jobs(*, older_than_minutes: int = STALE_EXTRACTION_MINUTES) -> int:
    """Put abandoned `running` extractions back in the queue. Returns the count.

    THE ORPHAN NOBODY WOULD EVER SEE. `next_extraction_job` selects `queued`
    and only `queued`, so a job that was `running` when the process died is
    never picked up again - by anything, ever. When this was written there was
    no sweeper, no timeout and no retry anywhere in this codebase; #177 added
    retries for a stage that FAILS, but a process that dies mid-job never
    reaches the failure handler, so this sweep is still the only thing that
    finds it. The standard simply never
    gets extracted, `extraction_job_state` reports `running` forever, and the
    screen shows work in progress that no process is doing.

    That is worse than a failure. A failed job says so and can be retried; this
    one claims to be busy.

    Called at STARTUP, where the fact that makes it safe is available: this
    process has just begun, so nothing it owns is running, and a job still
    marked running belongs to a process that is gone. The age threshold guards
    the other case - a second worker on the same database - by refusing to
    reclaim anything recent enough to plausibly still be alive.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
              ).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn = connect()
    with conn:
        # The dead claimant's name is cleared with its claim: it no longer
        # holds anything, and leaving it would let `run_extraction_job` treat
        # a returning stale caller as the owner.
        cur = conn.execute(
            "UPDATE jobs SET state = 'queued', claimed_by = NULL,"
            " claimed_at = NULL, updated_at = ?"
            " WHERE stage = ? AND state = 'running' AND updated_at < ?",
            (_now(), EXTRACTION_STAGE, cutoff))
        return cur.rowcount


#: A job any worker may take right now: waiting its first turn, or a retry
#: whose backoff has elapsed. One string, used by both claim paths below, so
#: the two cannot disagree about what "claimable" means.
_CLAIMABLE = ("(state = 'queued' OR (state = 'retrying'"
              " AND next_attempt_at IS NOT NULL AND next_attempt_at <= :now))")


def next_extraction_job(worker_id: str | None = None) -> str | None:
    """CLAIM the next extraction and return its document id, or None.

    #177: THIS WAS A PLAIN SELECT, and "ONE WORKER, NOT A SECOND ONE" above
    was the only thing standing between it and duplicated work - two pollers
    both read the same queued row and both ran it (test_job_claiming_race.py
    reproduced that deterministically). It is now ONE conditional UPDATE: the
    row moves to 'running' under this worker's name only if it is still
    claimable at the moment of the write, and RETURNING says whether this
    call is the one that moved it. A worker that got nothing back holds
    nothing, whatever it read before.

    Highest priority first, then oldest - so an extraction an administrator
    asked for runs ahead of the backfill the ingestion hook queued.
    """
    from . import job_queue
    from .config import settings
    me = worker_id or job_queue.worker_id()
    now = _now()
    conn = connect()
    with conn:
        row = conn.execute(
            f"""UPDATE jobs SET state = 'running', claimed_by = :me,
                       claimed_at = :now, updated_at = :now
                WHERE id = (SELECT id FROM jobs WHERE stage = :stage
                              AND {_CLAIMABLE}
                            ORDER BY priority DESC, started_at LIMIT 1)
                  AND {_CLAIMABLE}
                  AND {job_queue.under_limit_sql()}
                RETURNING document_id""",
            {"me": me, "now": now, "stage": EXTRACTION_STAGE,
             "stale": job_queue.stale_cutoff(),
             "limit": settings.job_max_running}).fetchone()
    return row["document_id"] if row else None


def run_extraction_job(document_id: str, worker_id: str | None = None) -> dict:
    """Run one claimed extraction to completion. Called by the worker.

    THE CLAIM IS CHECKED HERE, NOT TRUSTED (#177). The job must be 'running'
    under this worker's name - it came from `next_extraction_job` - or still
    claimable, in which case it is claimed now with the same conditional
    UPDATE. Anything else is somebody else's job and nothing is run: the
    pre-#177 code issued its claiming UPDATE and went on to extract whether or
    not that UPDATE touched a row.

    A FAILURE IS RETRIED, THEN POISONED (#177), via `job_queue.fail`: the
    error is kept on the row either way, and a poisoned job is never picked up
    again on its own.

    THE WORKER HAS NO CALLER AND THEREFORE NO SCOPE, so it reads every document
    id and passes it explicitly. That is the same decision `access.
    unrestricted_scope()` makes and it is named here for the same reason: a
    system actor's breadth must be written down at the point it is taken, never
    defaulted into by omitting an argument. The read paths still require the
    parameter; nothing here relaxes them.
    """
    from . import errors, job_queue
    from .config import settings
    me = worker_id or job_queue.worker_id()
    conn = connect()
    now = _now()
    with conn:
        job = conn.execute(
            "SELECT id FROM jobs WHERE document_id = ? AND stage = ?"
            " AND state = 'running' AND claimed_by = ?"
            " ORDER BY started_at DESC LIMIT 1",
            (document_id, EXTRACTION_STAGE, me)).fetchone()
        if job is None:
            job = conn.execute(
                f"""UPDATE jobs SET state = 'running', claimed_by = :me,
                           claimed_at = :now, updated_at = :now
                    WHERE id = (SELECT id FROM jobs WHERE document_id = :doc
                                  AND stage = :stage AND {_CLAIMABLE}
                                ORDER BY started_at DESC LIMIT 1)
                      AND {_CLAIMABLE}
                      AND {job_queue.under_limit_sql()}
                    RETURNING id""",
                {"me": me, "now": now, "doc": document_id,
                 "stage": EXTRACTION_STAGE, "stale": job_queue.stale_cutoff(),
                 "limit": settings.job_max_running}).fetchone()
    if job is None:
        return {"document_id": document_id, "state": "not_claimed",
                "requirements": 0, "table_values": 0}
    job_id = job["id"]
    every_document = frozenset(
        r["id"] for r in conn.execute("SELECT id FROM documents"))
    try:
        sentences = extract_requirements(
            document_id, allowed_document_ids=every_document)
        tabular = extract_table_values(
            document_id, allowed_document_ids=every_document)
    except Exception as exc:  # noqa: BLE001 - a failed job must not kill the worker
        safe = errors.record_failure(exc, document_id=document_id,
                                     stage=EXTRACTION_STAGE)
        with conn:
            # error_code keeps its pre-#177 meaning (the exception's type
            # name); the redacted message is what #177 adds.
            state = job_queue.fail(conn, job_id, code=type(exc).__name__,
                                   message=safe["message"])
        return {"document_id": document_id, "state": state,
                "requirements": 0, "table_values": 0}
    with conn:
        # The retry count is history and is kept; the error and schedule
        # belonged to attempts that are now superseded by a success.
        conn.execute(
            "UPDATE jobs SET state = 'done', error_code = NULL,"
            " error_message = NULL, next_attempt_at = NULL, updated_at = ?"
            " WHERE id = ?", (_now(), job_id))
        job_queue.audit(conn, "job.done", job_id, detail=f"stage={EXTRACTION_STAGE}")
    return {"document_id": document_id, "state": "done",
            "requirements": sentences.get("requirements", 0),
            "table_values": tabular.get("values", 0)}


def extraction_job_state(document_id: str, *,
                         allowed_document_ids: frozenset[str]) -> dict | None:
    """The state of a standard's extraction job, under the caller's grants."""
    if document_id not in allowed_document_ids:
        return None
    row = connect().execute(
        "SELECT id, state, error_code, started_at, updated_at FROM jobs"
        " WHERE document_id = ? AND stage = ? ORDER BY started_at DESC LIMIT 1",
        (document_id, EXTRACTION_STAGE)).fetchone()
    return dict(row) if row else None


def conflicts(*, allowed_document_ids: frozenset[str]) -> list[dict]:
    """Fields two standards limit differently. SURFACED, NEVER RESOLVED.

    Only over standards the caller may read, so a conflict with a document
    they hold no grant for is not disclosed - and is therefore not shown at
    all, rather than shown with one side missing.
    """
    submittal_review.ensure_schema()
    where, args = _scope_clause(allowed_document_ids, "standard_document_id")
    rows = connect().execute(
        "SELECT * FROM standard_requirements" + where +
        " AND value IS NOT NULL AND field IS NOT NULL", args).fetchall()
    return requirements_3b.find_conflicts([dict(r) for r in rows])


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
        # Decoded here so no caller has to know it is JSON in one column, and
        # a malformed value reads as "none recorded" rather than raising.
        item["exceptions"] = requirements_3b.decode_exceptions(item.get("exceptions"))
        out.append(item)
    return out


def search_requirements(
    query: str, *, allowed_document_ids: frozenset[str], limit: int = 20,
    discipline: str | None = None, equipment_type: str | None = None,
    service: str | None = None, document_role: str | None = None,
    project: str | None = None, standard_document_id: str | None = None,
    revision: str | None = None,
) -> list[dict]:
    """Requirement-level HYBRID retrieval: pre-filter, then rank, never
    dense-only.

    THE DISCOVERY-TIME PATH `list_requirements` IS NOT. That function fetches
    every requirement of ONE ALREADY-SELECTED standard - correct and
    deterministic for comparison, and left untouched (ranking it would make a
    comparison's completeness depend on a similarity cutoff). This answers a
    different question: "which clauses, across every standard I may read,
    talk about X" - and nothing in this codebase answered it before.

    NOT A SECOND SEARCH STACK. `standard_requirements.chunk_id` already
    points into the exact `chunks` rows `search.search` already indexes
    (`chunks_fts`, `chunk_vectors` - see that column's own comment). So this
    runs the SAME hybrid search everything else uses - lexical BM25 fused
    with dense embeddings by RRF, optionally reranked; dense is never used
    alone, because it never is anywhere else in this system either - and
    resolves each hit's chunk back to the requirement rows it carries. A
    chunk with no requirement (prose that was never atomised into one) simply
    contributes nothing here, the same way a requirement whose chunk vanished
    resolves to nothing in `list_requirements`.

    PRE-FILTERS NARROW THE ID SET BEFORE RETRIEVAL, NEVER AFTER. Matches the
    structured_search.py (B42) and CLAUDE.md rule 5 discipline: a filter may
    only narrow what the caller already may read - intersection, never
    union. `allowed_document_ids` is ANDed with the structured filters here
    exactly as it is everywhere else in this module (`_scope_clause`), and
    the narrowed set - never the original - is what retrieval receives, so a
    requirement outside the filter is never even a retrieval candidate, let
    alone one a rank could surface.
    """
    if not allowed_document_ids or not query.strip():
        return []
    submittal_review.ensure_schema()
    scope = set(allowed_document_ids)
    if standard_document_id is not None:
        scope &= {standard_document_id}
    filters: list[str] = []
    fargs: list[str] = []
    for column, value in (
        ("dc.discipline_canonical", discipline),
        ("dc.document_role", document_role),
        ("dc.project", project),
        ("dc.revision", revision),
        ("dc.equipment_type", equipment_type),
        ("dc.service", service),
    ):
        if value is not None:
            filters.append(f"{column} = ?")
            fargs.append(value)
    if filters and scope:
        marks = ",".join("?" for _ in scope)
        rows = connect().execute(
            f"SELECT d.id FROM documents d"
            f" JOIN document_classification dc ON dc.document_id = d.id"
            f" WHERE d.id IN ({marks}) AND " + " AND ".join(filters),
            [*sorted(scope), *fargs],
        ).fetchall()
        scope = {r["id"] for r in rows}
    narrowed = frozenset(scope)
    if not narrowed:
        return []

    from . import search as search_mod
    result = search_mod.search(
        query, limit=max(limit * 4, limit), allowed_document_ids=narrowed)

    where, args = _scope_clause(narrowed, "r.standard_document_id")
    out: list[dict] = []
    seen_ids: set[str] = set()
    for rank, hit in enumerate(result["hits"]):
        if len(out) >= limit:
            break
        rows = connect().execute(
            "SELECT r.* FROM standard_requirements r" + where +
            " AND r.chunk_id = ? ORDER BY r.created_at",
            [*args, hit["chunk_id"]],
        ).fetchall()
        for row in rows:
            if row["id"] in seen_ids or len(out) >= limit:
                continue
            seen_ids.add(row["id"])
            item = dict(row)
            item["exceptions"] = requirements_3b.decode_exceptions(item.get("exceptions"))
            item["citation_resolves"] = True
            item["retrieval"] = {
                "chunk_id": hit["chunk_id"], "rank": rank,
                "score": hit["score"], "bm25": hit["bm25"],
                "cosine": hit["cosine"],
            }
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
        "       c.discipline, c.discipline_canonical, c.superseded_by,"
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
