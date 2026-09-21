"""What a document IS. Never who may read it.

THE SEPARATION, stated once here and enforced by
tests/test_classification_independence.py rather than by anybody's care:
`disciplines` and `document_role_access` decide WHO MAY READ a document; this
module decides WHAT IT IS ABOUT. Nothing here reads, writes or references an
access table. A classification filter may only ever NARROW what a caller
already may read - intersection, never union - and `narrow_to_scope` below is
the only place that arithmetic happens.

It matters because the two look alike. `document_classification.discipline`
holds the same strings a discipline ROLE holds: "Process (AXENS)" is both a
column value here and the name of a role people are granted. A foreign key
between them would look like normalisation and would mean that reclassifying a
document silently regranted it.

THREE AXES, and each was chosen by measurement against the client's register
rather than designed:

  type        Document | Drawing | LicensorFinalBEP    (register column 1)
  discipline  24 values, vendor INSIDE the label exactly as the register
              writes it - "Process (AXENS)"            (register column 2)
  subject     ~25 systems, 6 facilities, plus "Project-wide"      (derived)

WHY SUBJECT IS THE COMPARISON AXIS AND DISCIPLINE IS NOT. Measured on 1,354
titles: subject terms cover 82% of them, and a subject spans 5.5 disciplines
on average with 18 of 22 systems spanning three or more. A discipline says who
WROTE a document; a subject says what it is ABOUT. Comparison happens along
subject, so filtering by discipline would slice a comparison set along the
wrong axis and silently drop the documents that make it a comparison.

WHAT WAS REJECTED, BY MEASUREMENT, and is deliberately not built here:

  * vendor as its own axis - already inside the discipline label, and
    splitting it would create two sources of truth for one field;
  * equipment tag as the linking key - only 16% of titles carry one, most of
    those are building codes, and it averages 1.7 documents per tag, so it
    links almost nothing;
  * document class as a filter - 88% derivable but nobody searches by it, so
    it is recorded and shown as a chip and is not a filter axis.

A SUGGESTION IS NOT A CLASSIFICATION. Nothing in this module auto-confirms.
`confirmed_by` stays NULL until an administrator says otherwise, because a
wrong classification misroutes searches for everyone rather than only for the
person who set it.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import get_args

from . import access
from . import schemas
from . import disciplines as disciplines_mod
from .db import connect

# ------------------------------------------------------------------- types

#: The register's own three. Not a database CHECK constraint - the importer
#: refuses a fourth value by name, which reads better than an IntegrityError,
#: and a future revision that legitimately adds one should fail where a human
#: is reading output rather than inside SQLite.
DOC_TYPES: tuple[str, ...] = ("Document", "Drawing", "LicensorFinalBEP")

#: The explicit subject for documents that apply to everything. 18% of the
#: register - philosophies, design criteria, overall block diagrams - and
#: exactly what gap analysis should hold as baselines.
PROJECT_WIDE = "Project-wide"

#: Which tier produced a value. Recorded per row so a reader can tell a
#: client-authoritative classification from a filename pattern match, and kept
#: after confirmation: an admin confirming what the register already said is
#: a different fact from an admin confirming a guess.
SOURCE_REGISTER = "register"
SOURCE_PATTERN = "pattern"
SOURCE_NONE = "none"

#: Document class patterns, longest-first so "SCOPE OF WORK" is not matched as
#: "WORK" and "PLOT PLAN" is not matched as "PLAN". Chip only.
DOC_CLASS_PATTERNS: tuple[tuple[str, str], ...] = (
    ("SCOPE OF WORK", r"\bscope\s+of\s+work\b"),
    ("PLOT PLAN", r"\bplot\s+plan\b"),
    ("SPECIFICATION", r"\bspecification\b|\bspec\b"),
    ("PHILOSOPHY", r"\bphilosoph(?:y|ies)\b"),
    ("CALCULATION", r"\bcalculation(?:s)?\b"),
    ("DATASHEET", r"\bdata\s?sheet(?:s)?\b"),
    # Matched against the NORMALISED text, where "&" has already become a
    # space - so the register's "P&ID" arrives as "p id" and a filename's
    # "PID" as "pid". Both spellings are listed rather than relying on one.
    ("P&ID", r"\bp\s?&?\s?id(?:s)?\b|\bpids?\b|\bpiping\s+and\s+instrument"),
    ("SLD", r"\bsld\b|\bsingle\s+line\s+diagram\b"),
    ("REPORT", r"\breport\b"),
)

#: The classes that mean "this applies to the whole project". Used only when a
#: register row matched and no subject term was found - see `suggest`.
PROJECT_WIDE_CLASSES: frozenset[str] = frozenset({"PHILOSOPHY"})
PROJECT_WIDE_WORDS = re.compile(
    r"\bphilosoph(?:y|ies)\b|\bdesign\s+basis\b|\bdesign\s+criteria\b"
    r"|\bbasis\s+of\s+design\b|\boverall\b", re.I)


@dataclass(frozen=True)
class Suggestion:
    """What the system thinks a document is, and where each field came from.

    Every field is nullable and a NULL is a real answer: nothing matched and
    nothing was guessed. A discipline inferred from one word in a filename is
    worse than no discipline, because it routes searches confidently to the
    wrong place and nobody discovers it by reading the value.
    """

    doc_type: str | None = None
    discipline: str | None = None
    doc_class: str | None = None
    register_id: str | None = None
    subject_ids: tuple[str, ...] = ()
    #: field name -> SOURCE_*. Per FIELD, not per suggestion: a title can match
    #: the register for its discipline while its subjects come from the
    #: vocabulary, and collapsing that to one label would lose which half is
    #: the client's own.
    source: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return (self.doc_type is None and self.discipline is None
                and self.doc_class is None and not self.subject_ids)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------- normalising

_PUNCT = re.compile(r"[^\w\s]+")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Case, punctuation and whitespace ONLY. NEVER meaning.

    A register title and an uploaded filename differ in punctuation and
    capitalisation constantly - "Hot Oil System P&ID" against
    "hot-oil-system-pid.pdf" - and matching those is the point. What this must
    never do is stem, synonym-map or drop words: "firewater pump" and
    "firewater pumps" are the same document and "firewater header" is not, and
    a normaliser that cannot tell those apart would attach the client's
    authoritative type and discipline to the wrong deliverable.
    """
    stripped = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", str(text or ""))
    return _SPACE.sub(" ", _PUNCT.sub(" ", stripped.lower())).strip()


def normalise_tight(text: str) -> str:
    """`normalise` with the separators removed as well as replaced.

    WHY A SECOND FORM. `normalise` turns punctuation into a SPACE, which is
    right for finding a term inside a title - but it splits "P&ID" into
    "p id", and a filename writing the same thing as "PID" then does not
    match the register's "P&ID". Measured on this project's own naming: the
    register writes "Hot Oil System P&ID" and uploads arrive as
    "HOT-OIL-SYSTEM-PID.pdf".

    Still case, punctuation and whitespace ONLY - nothing here touches
    meaning. Used for WHOLE-TITLE EQUALITY and never for substring search,
    because a tight form makes substrings dangerous: "meg" is inside "omega",
    so matching subjects this way would attach a MEG subject to a document
    about omega values.
    """
    return re.sub(r"[^a-z0-9]+", "", normalise(text))


# ------------------------------------------------------ the register lookup

def register_revision() -> str | None:
    """The newest imported revision, or None when no register is loaded.

    None is load-bearing: the coverage route reports `in_register: null`
    rather than a zero, so the frontend cannot compute a percentage against a
    denominator it was never handed.
    """
    row = connect().execute(
        "SELECT register_revision FROM deliverables_register"
        " ORDER BY imported_at DESC, register_revision DESC LIMIT 1").fetchone()
    return row[0] if row else None


def match_register(title: str, revision: str | None) -> dict | None:
    """The register row this title IS, or None.

    AUTHORITATIVE WHEN IT HITS. The register is the client's official list of
    deliverables, so a matched row's type and discipline are the client's own
    answer and not this system's guess. That is why tier 1 beats every pattern
    below it: a filename pattern is evidence, and the register is a fact.

    Matched on the normalised title and nothing else. No fuzzy distance, no
    partial credit: a near-miss would attach the wrong deliverable's official
    discipline to a document, which is worse than leaving it NULL.
    """
    if revision is None:
        return None
    key = normalise(title)
    tight = normalise_tight(title)
    if not key:
        return None
    for row in connect().execute(
            "SELECT id, doc_type, discipline, vendor, title FROM"
            " deliverables_register WHERE register_revision = ?", (revision,)):
        # Either normalisation, and both are whole-string equality. The tight
        # form is what lets "HOT-OIL-SYSTEM-PID.pdf" match "Hot Oil System
        # P&ID"; it is safe here precisely because it compares complete titles
        # rather than searching for a substring.
        if normalise(row["title"]) == key or normalise_tight(row["title"]) == tight:
            return dict(row)
    return None


def subjects_for_revision(revision: str | None) -> list[dict]:
    if revision is None:
        return []
    return [dict(r) for r in connect().execute(
        "SELECT id, name, kind FROM subjects WHERE register_revision = ?"
        " ORDER BY kind, name", (revision,))]


def match_subjects(text: str, revision: str | None) -> list[str]:
    """Subject ids whose name appears in the text. Zero or more.

    MANY, NOT ONE. A firewater layout for the substation has two subjects, and
    picking the "best" would lose the link that makes comparison work - the
    document would appear under one and vanish from the other, with the reader
    given no sign that the set they are comparing is incomplete.

    Matched on word boundaries over the normalised text, so "MEG" does not fire
    inside "omega" and "diesel" does not fire inside "diesels" - the latter
    would be a miss, not a false hit, which is the safer direction here.
    """
    if revision is None:
        return []
    haystack = f" {normalise(text)} "
    found: list[str] = []
    for row in subjects_for_revision(revision):
        if row["kind"] == "project_wide":
            continue          # never matched by text; see `suggest`
        needle = f" {normalise(row['name'])} "
        if needle in haystack and row["id"] not in found:
            found.append(row["id"])
    return found


def match_doc_class(text: str) -> str | None:
    """The document class, for the CHIP ONLY. Longest pattern first."""
    lowered = normalise(text)
    for label, pattern in DOC_CLASS_PATTERNS:
        if re.search(pattern, lowered, re.I):
            return label
    return None


def project_wide_id(revision: str | None) -> str | None:
    if revision is None:
        return None
    row = connect().execute(
        "SELECT id FROM subjects WHERE register_revision = ? AND"
        " kind = 'project_wide' LIMIT 1", (revision,)).fetchone()
    return row[0] if row else None


# ------------------------------------------------------------- the suggestion

def suggest(filename: str, first_page_text: str,
            register_revision: str | None) -> Suggestion:
    """Three tiers, in order, and a NULL rather than a guess.

    TIER 1 - the title matches a register row. `doc_type` and `discipline`
    come from the CLIENT'S OWN ROW and are authoritative: the register is the
    official deliverables list, so a hit here is a fact rather than an
    inference, and it beats every pattern below.

    TIER 2 - the title and first page are matched against the derived subject
    vocabulary, giving zero or more subjects, and against the class patterns,
    giving a chip. Evidence, not authority: it never produces a discipline,
    because a discipline guessed from one word in a filename routes searches
    confidently to the wrong place.

    TIER 3 - nothing matched. Every field NULL. This is a real answer and the
    needs-classification queue is built from it.

    THE ONE INFERENCE, and its guard rails: if a register row matched, no
    subject term was found, AND the document reads as a philosophy, design
    basis, design criteria or an "overall" drawing, then "Project-wide" is
    suggested. All three conditions, because that combination is what the
    register's 18% project-wide group looks like. Without a register hit it
    would be a guess; with a subject term found it would be wrong; with
    neither condition it stays empty rather than becoming a wrong baseline -
    and a wrong Project-wide is expensive, because gap analysis holds those as
    the documents everything else is compared against.
    """
    title_text = str(filename or "")
    body = str(first_page_text or "")
    both = f"{title_text}\n{body}"

    source: dict = {}
    row = match_register(title_text, register_revision)

    doc_type = discipline = register_id = None
    if row is not None:
        doc_type = row["doc_type"]
        discipline = row["discipline"]
        register_id = row["id"]
        source["doc_type"] = SOURCE_REGISTER
        source["discipline"] = SOURCE_REGISTER

    doc_class = match_doc_class(both)
    if doc_class is not None:
        source["doc_class"] = SOURCE_PATTERN

    subject_ids = match_subjects(both, register_revision)
    if subject_ids:
        source["subjects"] = SOURCE_PATTERN
    elif row is not None and (
            doc_class in PROJECT_WIDE_CLASSES
            or PROJECT_WIDE_WORDS.search(both)):
        wide = project_wide_id(register_revision)
        if wide is not None:
            subject_ids = [wide]
            source["subjects"] = SOURCE_REGISTER

    if not source:
        source = {"doc_type": SOURCE_NONE, "discipline": SOURCE_NONE}

    return Suggestion(
        doc_type=doc_type, discipline=discipline, doc_class=doc_class,
        register_id=register_id, subject_ids=tuple(subject_ids), source=source,
    )


# ------------------------------------------------------------------- storage

def write_suggestion(document_id: str, suggestion: Suggestion, *,
                     suggested_by: str) -> None:
    """Store a suggestion. `confirmed_by` stays NULL - nothing auto-confirms.

    Idempotent per document: re-running ingestion replaces the SUGGESTION and
    leaves a human confirmation alone, because a re-suggest must never quietly
    un-confirm what an administrator decided.
    """
    conn = connect()
    with conn:
        existing = conn.execute(
            "SELECT confirmed_by, confirmed_at FROM document_classification"
            " WHERE document_id = ?", (document_id,)).fetchone()
        if existing is not None and existing["confirmed_by"] is not None:
            return          # confirmed: a suggestion does not overwrite it
        conn.execute(
            "INSERT INTO document_classification (document_id, doc_type,"
            " discipline, discipline_canonical, doc_class, register_id,"
            " suggested_by, confirmed_by, confirmed_at)"
            # Nine columns, seven bound values and two NULLs. This read
            # `(?,?,?,?,?,?,NULL,NULL)` - eight - when `discipline_canonical`
            # was added, and every document ingest would have failed to
            # classify: "8 values for 9 columns".
            " VALUES (?,?,?,?,?,?,?,NULL,NULL)"
            " ON CONFLICT(document_id) DO UPDATE SET"
            " doc_type=excluded.doc_type, discipline=excluded.discipline,"
            " discipline_canonical=excluded.discipline_canonical,"
            " doc_class=excluded.doc_class, register_id=excluded.register_id,"
            " suggested_by=excluded.suggested_by",
            # BOTH, ALWAYS, AND DERIVED HERE. The canonical value is computed
            # at the write rather than by a nightly job, so the two columns
            # cannot drift: there is no window in which a row has a raw value
            # and a stale canonical one.
            (document_id, suggestion.doc_type, suggestion.discipline,
             disciplines_mod.canonical(suggestion.discipline),
             suggestion.doc_class, suggestion.register_id, suggested_by))
        conn.execute(
            "DELETE FROM document_subjects WHERE document_id = ?"
            " AND confirmed_by IS NULL", (document_id,))
        for subject_id in suggestion.subject_ids:
            conn.execute(
                "INSERT OR IGNORE INTO document_subjects (document_id,"
                " subject_id, suggested_by, confirmed_by) VALUES (?,?,?,NULL)",
                (document_id, subject_id, suggested_by))


#: The submittal-review metadata an administrator may set, in the order the
#: columns are declared. Kept as one tuple because it is written in `confirm`,
#: read in `of_document` and filtered in `narrow_to_scope`, and a field added
#: to one of those and forgotten in another is exactly the "fixed in one of two
#: places" defect CLAUDE.md rule 8 names.
#:
#: `equipment_tags` is absent on purpose: it is a JSON list, not a scalar, and
#: is handled separately in `confirm`.
METADATA_FIELDS = (
    "document_role", "document_number", "title", "revision", "effective_date",
    "project", "contractor_vendor", "equipment_type", "service",
    "transmittal_number", "superseded_by",
)


#: Every value `set_role` will accept, and the ONLY vocabulary check that
#: stands between a caller and the column. It has to live here rather than only
#: in Pydantic because `set_role`'s other caller is the WATCHER, which reaches
#: this module directly and never crosses a route - `confirm` documents its own
#: vocabulary as unchecked and names that a known limitation, and repeating the
#: limitation for a function a background thread calls unattended would be
#: choosing it a second time rather than inheriting it.
#:
#: DERIVED from `schemas.DocumentRole`, not retyped. Rule 8 - a claim fixed in
#: one of two homes is this project's most common review finding, and a role
#: added to the API vocabulary but not to a hand-written tuple here would be
#: accepted by the route and refused by the watcher.
ROLES: tuple[str, ...] = get_args(schemas.DocumentRole)


class UnknownRole(ValueError):
    """A role outside `ROLES`. Raised rather than stored, because the column is
    plain TEXT with no CHECK and a typo there is a document no filter matches -
    invisible in exactly the way a missing document is not."""


def set_role(document_id: str, role: str, *, only_if_unset: bool = False) -> bool:
    """Set `document_role` ALONE. Returns True if the column actually changed.

    NOT `confirm`, and the difference is the whole reason this exists.
    `confirm` is a PUT: it replaces the record, so a caller sending only a role
    CLEARS the title, the revision, the project and the rest. That is correct
    for an editor sending a whole form and catastrophic for a bulk action whose
    entire intent is "change one field on forty documents". Bulk-assigning a
    role through `confirm` would silently erase metadata somebody typed, on
    every document selected, with nothing in the response to say so.

    So this writes one column and touches nothing else - not the subjects, not
    the equipment tags, not `confirmed_by`. Setting a role is not confirming a
    classification, and stamping it as confirmed would claim a human had
    reviewed the type axis when nobody looked at it.

    A document with no classification row gets one, holding only the role.

    `only_if_unset` is for the WATCHER. A file re-appearing in a role subfolder
    must never overwrite a role a person set: the folder is a convenience, and
    a human's correction that a folder undoes on the next scan is a correction
    that does not survive. With it, a document that already has any role is
    left exactly as it is and this returns False.
    """
    if role not in ROLES:
        raise UnknownRole(
            f"{role!r} is not a document role; expected one of {', '.join(ROLES)}")
    changed = _set_one_column("document_role", document_id, role,
                              only_if_unset=only_if_unset)
    if changed and role == "COMPANY_STANDARD":
        _queue_extraction_if_ready(document_id)
    return changed


def _queue_extraction_if_ready(document_id: str) -> None:
    """Queue rule extraction for a document that BECOMES a company standard.

    THE OTHER HALF OF THE INGESTION HOOK, and without it that hook is inert
    for every document a person uploads. `ingest._queue_extraction_if_standard`
    asks whether a document is a COMPANY_STANDARD at the moment ingestion
    finishes. For an upload the answer is always no: `upload.py` writes a
    classification row with `document_role` NULL and the role is assigned
    afterwards, by an administrator or by the watch folder. Measured on the
    live corpus - 256 of the 272 standards carry `suggested_by = 'none'`,
    which is the bulk role endpoint, not a pattern match at upload.

    So the two hooks cover the two orders and neither covers both:
      role set first, then ingestion finishes  -> the ingest hook queues it
      ingestion finishes, then role set        -> this queues it

    Only when the document is already READY. A document still chunking will
    reach the ingest hook on its own, and queuing extraction for a document
    with no chunks yet would extract nothing and report success.

    Imported inside the function: `standards` pulls in the whole review
    surface, and this module must not depend on it merely to enqueue - the
    same reason `ingest` gives for the same import.

    Swallows its own failure. Assigning a role must not fail because
    downstream work could not be scheduled, and `enqueue_extraction` is
    idempotent per document, so a later retry costs nothing.
    """
    try:
        from . import states
        row = connect().execute(
            "SELECT status FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None or row["status"] != states.READY:
            return
        from . import standards
        standards.enqueue_extraction(document_id)
    except Exception as exc:  # noqa: BLE001 - see docstring
        from . import errors
        errors.record_failure(exc, stage="standard_extraction_enqueue")


def set_discipline(document_id: str, discipline: str, *,
                   only_if_unset: bool = True) -> bool:
    """Set `discipline` ALONE. Returns True if the column actually changed.

    Same contract as `set_role`, same reasons, and `only_if_unset` defaults
    TRUE here rather than False: the caller is a backfill over the whole
    corpus, and a backfill that overwrites is one accidental re-run away from
    undoing every correction a human has made.

    NO VOCABULARY CHECK, and unlike the role that is not an oversight. The
    role column has five legal values; `discipline` holds whatever the client's
    register and the standards' own covers say, which measured 52 distinct
    committee names across this corpus and will grow. An allowlist here would
    have to be edited every time Saudi Aramco renames a committee, and the
    failure mode would be a standard silently left unclassified.
    """
    if not (discipline or "").strip():
        # An empty string is not a discipline, and storing one makes a document
        # look classified to every reader while matching nothing. NULL is the
        # honest value for "not known" and this refuses to blur the two.
        raise ValueError("discipline must not be blank; leave it NULL instead")
    return _set_one_column("discipline", document_id, discipline.strip(),
                           only_if_unset=only_if_unset)


def _set_one_column(column: str, document_id: str, value: str, *,
                    only_if_unset: bool) -> bool:
    """The one writer behind `set_role` and `set_discipline`.

    ONE FUNCTION, because the interesting part is not the column name - it is
    the `IS NOT` comparison and the `only_if_unset` guard, and two copies of
    that would be two places for the next person to fix half of (rule 8).

    `column` is interpolated into SQL and is therefore NEVER caller data: both
    call sites pass a literal, and this refuses anything else rather than
    trusting that they always will.
    """
    if column not in ("document_role", "discipline"):
        raise ValueError(f"{column!r} is not a column this function may write")
    conn = connect()
    with conn:
        # ON CONFLICT ... WHERE, rather than a SELECT and then an UPDATE: two
        # statements would let a concurrent writer land between them, and the
        # loser would report False having actually been overwritten. `changes()`
        # after this is the count of rows the database really wrote.
        #
        # `IS NOT excluded.<column>` is not decoration. Without it SQLite
        # counts a row it rewrote with the SAME value as an update, so setting
        # COMPANY_STANDARD on a document that already held COMPANY_STANDARD
        # reported a change - and the bulk endpoint would then tell an
        # administrator it had updated forty documents when it had changed
        # none. `IS NOT` rather than `<>` because the existing value is usually
        # NULL, and `NULL <> 'X'` is NULL, which is not true, which would make
        # the only case that matters the one case that never writes.
        guard = (f" AND document_classification.{column} IS NULL"
                 if only_if_unset else "")
        cur = conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by,"
            f" {column}) VALUES (?, ?, ?)"
            " ON CONFLICT(document_id) DO UPDATE SET"
            f" {column} = excluded.{column}"
            f" WHERE document_classification.{column}"
            f" IS NOT excluded.{column}{guard}",
            (document_id, SOURCE_NONE, value))
        return cur.rowcount > 0


def confirm(document_id: str, *, doc_type: str | None,
            discipline: str | None, doc_class: str | None,
            subject_ids: Sequence[str], confirmed_by: str | None,
            metadata: dict | None = None,
            equipment_tags: Sequence[str] | None = None) -> dict:
    """An administrator's decision. Sets `confirmed_by` and `confirmed_at`.

    THE AUTHORITY IS THE ADMIN CAPABILITY, checked at the route rather than
    here - this module does not read roles. The reason it is privileged: a
    wrong classification misroutes searches for EVERYONE, not only for the
    person who set it, so it needs a role that answers for everyone.

    The subject set is REPLACED, not merged. An administrator removing a
    subject must be able to remove it; merging would make removal impossible
    and leave a document permanently attached to a comparison it does not
    belong in.

    `metadata` and `equipment_tags` carry the submittal-review fields and are
    REPLACED on the same principle: a PUT sends the whole record, so a field
    left out is cleared rather than silently kept. `None` for the whole
    `metadata` argument is different from an empty dict - it means this caller
    is not touching metadata at all, which is what keeps every pre-phase-2
    caller (and every existing test) behaving exactly as before.

    THE ROLE VOCABULARY IS NOT CHECKED HERE. It is enforced in Pydantic at the
    route, because that is where a bad value can be refused with a message
    naming the field. A direct caller of this function is trusted to have
    validated, and `docs/AI_SUBMITTAL_REVIEW_PROGRESS.md` records that as a
    known limitation rather than pretending the column constrains itself.
    """
    now = _now()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, doc_type,"
            " discipline, discipline_canonical, doc_class, register_id,"
            " suggested_by, confirmed_by, confirmed_at)"
            " VALUES (?,?,?,?,?,NULL,?,?,?)"
            " ON CONFLICT(document_id) DO UPDATE SET"
            " doc_type=excluded.doc_type, discipline=excluded.discipline,"
            " discipline_canonical=excluded.discipline_canonical,"
            " doc_class=excluded.doc_class, confirmed_by=excluded.confirmed_by,"
            " confirmed_at=excluded.confirmed_at",
            (document_id, doc_type, discipline,
             disciplines_mod.canonical(discipline), doc_class, SOURCE_NONE,
             confirmed_by, now))
        if metadata is not None:
            # Built from METADATA_FIELDS rather than spelled out, so a column
            # added to that tuple cannot be written in one place and forgotten
            # in another.
            assignments = ", ".join(f"{name} = ?" for name in METADATA_FIELDS)
            values = [metadata.get(name) for name in METADATA_FIELDS]
            conn.execute(
                f"UPDATE document_classification SET {assignments}"
                " WHERE document_id = ?", [*values, document_id])
        if equipment_tags is not None:
            # Stored as a JSON array in one TEXT column. An empty list is
            # stored as '[]' and reads back as "none recorded", which is the
            # same answer as NULL and is why the read path tolerates both.
            conn.execute(
                "UPDATE document_classification SET equipment_tags = ?"
                " WHERE document_id = ?",
                (json.dumps([str(t) for t in equipment_tags]), document_id))
        conn.execute("DELETE FROM document_subjects WHERE document_id = ?",
                     (document_id,))
        for subject_id in subject_ids or ():
            conn.execute(
                "INSERT OR IGNORE INTO document_subjects (document_id,"
                " subject_id, suggested_by, confirmed_by) VALUES (?,?,?,?)",
                (document_id, subject_id, SOURCE_NONE, confirmed_by))
    return of_document(document_id) or {}


def of_document(document_id: str) -> dict | None:
    """The stored classification, or None. No scope check - the ROUTE scopes."""
    row = connect().execute(
        "SELECT * FROM document_classification WHERE document_id = ?",
        (document_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    # Stored as a JSON array in one TEXT column; decoded here so no caller has
    # to know that. A row written before this column existed holds NULL, and a
    # malformed value is read as "none recorded" rather than raising - the same
    # tolerance review._row applies to its own JSON columns.
    try:
        tags = json.loads(out.get("equipment_tags") or "[]")
    except (TypeError, ValueError):
        tags = []
    out["equipment_tags"] = tags if isinstance(tags, list) else []
    out["subjects"] = [dict(r) for r in connect().execute(
        "SELECT s.id, s.name, s.kind, ds.suggested_by, ds.confirmed_by"
        " FROM document_subjects ds JOIN subjects s ON s.id = ds.subject_id"
        " WHERE ds.document_id = ? ORDER BY s.kind, s.name", (document_id,))]
    out["confirmed"] = row["confirmed_by"] is not None
    return out


# -------------------------------------------------------------- the filter

@dataclass(frozen=True)
class ScopeFilter:
    """A caller's classification filter. Absent fields mean "do not filter"."""

    types: tuple[str, ...] = ()
    disciplines: tuple[str, ...] = ()
    subject_ids: tuple[str, ...] = ()
    # ------------------------------------------ AI submittal review, phase 2
    # Three more axes over the SAME table, deliberately routed through this
    # same filter object rather than added to the documents route as extra
    # WHERE clauses. The intersection that makes a filter safe is written once,
    # in `narrow_to_scope`; a second filtering path would be a second place to
    # get it wrong, and the one that got it wrong would be the new one.
    roles: tuple[str, ...] = ()
    equipment_types: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.types or self.disciplines or self.subject_ids
                    or self.roles or self.equipment_types or self.projects)

    def as_api(self) -> dict:
        return {"types": list(self.types), "disciplines": list(self.disciplines),
                "subject_ids": list(self.subject_ids),
                "roles": list(self.roles),
                "equipment_types": list(self.equipment_types),
                "projects": list(self.projects)}


def narrow_to_scope(
    scope: access.AccessScope, wanted: ScopeFilter,
) -> tuple[frozenset[str], bool]:
    """`(ids to search, whether the filter applied)`. INTERSECTION, ALWAYS.

    THE SAME MECHANISM AS `analysis.narrow_to_named`: resolve a candidate id
    set, intersect it with `scope.allowed_document_ids`, and return the pair so
    the caller can echo whether narrowing happened. The intersection is the
    part that matters and it is written once, here.

    IT DELIBERATELY DOES NOT SHARE THAT FUNCTION'S FALLBACK, and this is the
    one place the two must differ. `narrow_to_named` treats "nothing resolved"
    as "do not narrow", because a question that names a misspelt document is
    better answered broadly than emptily. A classification filter is the
    opposite: the caller ASKED for hot oil, so a filter that matched nothing
    must return NOTHING. Falling back to the whole corpus there would widen a
    filter into a no-op and hand the reader results they had explicitly
    excluded - and worse, it would be indistinguishable from the filter
    working. Fail closed.

    A subject whose documents this caller may not read therefore yields an
    empty set rather than a leak, and it yields it without saying whether any
    such document exists.
    """
    if wanted.is_empty:
        return scope.allowed_document_ids, False

    clauses: list[str] = []
    params: list[str] = []
    if wanted.types:
        marks = ",".join("?" * len(wanted.types))
        clauses.append(f"c.doc_type IN ({marks})")
        params.extend(wanted.types)
    if wanted.disciplines:
        # FILTERED ON THE CANONICAL VALUE, and the REQUESTED values are
        # canonicalised too. A caller asking for "Non-metallic Standards
        # Committee" and a caller asking for "Nonmetallic Standards Committee"
        # are asking the same question, and before this they got different
        # answers depending on which spelling their document happened to use.
        # COALESCE because a row written before the column existed has NULL
        # there until the startup backfill runs; falling back to the raw value
        # means such a row is still findable by its own spelling rather than
        # silently dropping out of every filtered result.
        wantedcanon = [disciplines_mod.canonical(d) or d
                       for d in wanted.disciplines]
        marks = ",".join("?" * len(wantedcanon))
        clauses.append(
            f"COALESCE(c.discipline_canonical, c.discipline) IN ({marks})")
        params.extend(wantedcanon)
    # The phase 2 axes. Each is ANDed with the others - selecting a role and a
    # discipline means "documents that are both", never "either". An OR here
    # would widen a filter the more the caller narrowed it, which is the one
    # way a filter can surprise a reader with MORE than they asked for.
    if wanted.roles:
        marks = ",".join("?" * len(wanted.roles))
        clauses.append(f"c.document_role IN ({marks})")
        params.extend(wanted.roles)
    if wanted.equipment_types:
        marks = ",".join("?" * len(wanted.equipment_types))
        clauses.append(f"c.equipment_type IN ({marks})")
        params.extend(wanted.equipment_types)
    if wanted.projects:
        marks = ",".join("?" * len(wanted.projects))
        clauses.append(f"c.project IN ({marks})")
        params.extend(wanted.projects)

    sql = ["SELECT DISTINCT c.document_id FROM document_classification c"]
    if wanted.subject_ids:
        marks = ",".join("?" * len(wanted.subject_ids))
        sql.append(" JOIN document_subjects ds ON"
                   " ds.document_id = c.document_id")
        clauses.append(f"ds.subject_id IN ({marks})")
        params.extend(wanted.subject_ids)
    if clauses:
        sql.append(" WHERE " + " AND ".join(clauses))

    matched = {r[0] for r in connect().execute("".join(sql), params)}
    # THE INTERSECTION. Never a union, and never the matched set on its own:
    # a classification says nothing about who may read a document.
    return frozenset(matched & set(scope.allowed_document_ids)), True


def restrict(scope: access.AccessScope,
             wanted: ScopeFilter) -> tuple[access.AccessScope, bool]:
    """A NARROWER scope, and whether the filter applied.

    Returning a scope rather than an id set is what makes widening
    structurally impossible. Every retrieval path in this system already takes
    `allowed_document_ids` from the scope it is handed, so a narrowed scope
    needs no change anywhere downstream - and there is no second code path on
    which an unfiltered set could be used by mistake.

    `dataclasses.replace` keeps `user_id`, `capabilities` and `unrestricted`
    exactly as they were: a classification filter changes WHAT IS SEARCHED and
    never WHO THE CALLER IS. In particular `unrestricted` is carried through
    untouched - narrowing an unrestricted scope narrows the search and does
    not turn the caller into a restricted one.
    """
    ids, applied = narrow_to_scope(scope, wanted)
    if not applied:
        return scope, False
    return replace(scope, allowed_document_ids=frozenset(ids)), True


# --------------------------------------------------------------- vocabulary

def vocabulary() -> dict:
    """Types, disciplines and subjects. NOT SCOPED, on purpose.

    A DISCIPLINE THE CALLER CANNOT READ STAYS VISIBLE. Discipline names are
    project structure - the client's org chart, effectively - and not evidence
    that any document exists. Hiding one teaches a user that the system is
    broken rather than that they need access; showing it with a zero count
    tells them the truth. The COUNTS are scoped; the vocabulary is not.
    """
    revision = register_revision()
    conn = connect()
    disciplines = [r[0] for r in conn.execute(
        "SELECT DISTINCT discipline FROM deliverables_register"
        " WHERE register_revision = ? ORDER BY discipline", (revision,))
    ] if revision else []
    types = [r[0] for r in conn.execute(
        "SELECT DISTINCT doc_type FROM deliverables_register"
        " WHERE register_revision = ? ORDER BY doc_type", (revision,))
    ] if revision else []
    return {
        "register_revision": revision,
        "types": types or list(DOC_TYPES),
        "disciplines": disciplines,
        "subjects": subjects_for_revision(revision),
    }


def needs_classification(scope: access.AccessScope) -> int:
    """How many documents IN THIS CALLER'S SCOPE await confirmation.

    Scoped, unlike the vocabulary: a count is a statement about documents, and
    a document outside the caller's scope is not theirs to be told about. A
    document with no classification row at all counts too - it needs one.
    """
    allowed = list(scope.allowed_document_ids)
    if not allowed:
        return 0
    marks = ",".join("?" * len(allowed))
    return connect().execute(
        f"SELECT COUNT(*) FROM documents d"
        f" LEFT JOIN document_classification c ON c.document_id = d.id"
        f" WHERE d.id IN ({marks})"
        f"   AND (c.document_id IS NULL OR c.confirmed_by IS NULL)",
        allowed).fetchone()[0]


def _scoped_marks(allowed: Iterable[str]) -> tuple[str, list[str]]:
    ids = list(allowed)
    return ",".join("?" * len(ids)), ids


def coverage(scope: access.AccessScope) -> dict:
    """Counts per axis, scoped, with `in_register` NULL when none is loaded.

    `in_register` IS NULL RATHER THAN ZERO when no register has been imported.
    A zero denominator invites a percentage; a null cannot be divided by, so
    the frontend is structurally prevented from printing "0% classified" about
    a project whose register simply has not been loaded yet.
    """
    revision = register_revision()
    conn = connect()
    marks, allowed = _scoped_marks(scope.allowed_document_ids)

    def rows(sql: str, params: Sequence = ()) -> list:
        return [] if not allowed else list(conn.execute(sql, params))

    reg_types: dict = {}
    reg_disc: dict = {}
    if revision:
        reg_types = {r[0]: r[1] for r in conn.execute(
            "SELECT doc_type, COUNT(*) FROM deliverables_register"
            " WHERE register_revision = ? GROUP BY doc_type", (revision,))}
        reg_disc = {r[0]: r[1] for r in conn.execute(
            "SELECT discipline, COUNT(*) FROM deliverables_register"
            " WHERE register_revision = ? GROUP BY discipline", (revision,))}

    by_type_rows = rows(
        f"SELECT c.doc_type AS k, COUNT(*) AS uploaded,"
        f" SUM(CASE WHEN c.confirmed_by IS NULL THEN 1 ELSE 0 END) AS unconf"
        f" FROM document_classification c WHERE c.document_id IN ({marks})"
        f" AND c.doc_type IS NOT NULL GROUP BY c.doc_type", allowed)
    by_disc_rows = rows(
        f"SELECT c.discipline AS k, COUNT(*) AS uploaded,"
        f" SUM(CASE WHEN c.confirmed_by IS NULL THEN 1 ELSE 0 END) AS unconf"
        f" FROM document_classification c WHERE c.document_id IN ({marks})"
        f" AND c.discipline IS NOT NULL GROUP BY c.discipline", allowed)

    uploaded_types = {r["k"]: (r["uploaded"], r["unconf"]) for r in by_type_rows}
    uploaded_disc = {r["k"]: (r["uploaded"], r["unconf"]) for r in by_disc_rows}

    by_type = [
        {"type": name,
         "in_register": reg_types.get(name) if revision else None,
         "uploaded": uploaded_types.get(name, (0, 0))[0],
         "unconfirmed": uploaded_types.get(name, (0, 0))[1]}
        for name in sorted(set(reg_types) | set(uploaded_types))
    ]
    by_discipline = [
        {"discipline": name,
         "in_register": reg_disc.get(name) if revision else None,
         "uploaded": uploaded_disc.get(name, (0, 0))[0],
         "unconfirmed": uploaded_disc.get(name, (0, 0))[1]}
        for name in sorted(set(reg_disc) | set(uploaded_disc))
    ]

    # `disciplines_spanned` is the measurement that justified making subject
    # the comparison axis, reported per subject so a reader can see it on
    # their own corpus rather than taking 5.5 on trust.
    by_subject = [
        {"subject": r["name"], "kind": r["kind"], "uploaded": r["uploaded"],
         "disciplines_spanned": r["spanned"]}
        for r in rows(
            f"SELECT s.name, s.kind, COUNT(DISTINCT ds.document_id) AS uploaded,"
            f" COUNT(DISTINCT c.discipline) AS spanned"
            f" FROM subjects s"
            f" JOIN document_subjects ds ON ds.subject_id = s.id"
            f" LEFT JOIN document_classification c ON c.document_id = ds.document_id"
            f" WHERE ds.document_id IN ({marks})"
            f" GROUP BY s.id ORDER BY uploaded DESC, s.name", allowed)
    ]

    return {
        "register_loaded": revision is not None,
        "register_revision": revision,
        "by_type": by_type,
        "by_discipline": by_discipline,
        "by_subject": by_subject,
        "needs_classification": needs_classification(scope),
        "corpus_wide": bool(scope.unrestricted or scope.is_admin),
    }


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
