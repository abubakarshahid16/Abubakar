"""Standards beyond Saudi Aramco's: WHERE to get a missing one, and a record
of getting it.

THE CLIENT'S REQUIREMENT (.cowork/CLIENT_FEEDBACK_REQUIREMENTS_ADDENDUM.md
section 1): review against every applicable source - API, ASME, ASTM, ISO,
IEC, NFPA, NACE, NORSOK, KOC - not only SAES/SAMSS; a missing one is reported
MISSING_LOCALLY; an obtained copy is stored, hashed, cited and MARKED AS
EXTERNALLY OBTAINED. `standards_inventory.cited_but_not_held` already finds
the missing ones. This module is the "NOT YET BUILT" half of that module's
docstring: the lookup and the provenance.

WHY IT FETCHES NOTHING. Every one of these families is sold under licence by
its publisher. Checked on the publishers' own sites (2026-09-29): even NORSOK,
often assumed free, is sold by Standards Norway as subscription, collection or
single licence. So "online lookup" here means POINTING at the official
catalogue, never downloading a copy: `where_to_obtain` builds a link to the
publisher's own catalogue page from a fixed allow-list (no search query, so
not even the identifier leaves the machine when the link is followed), and the
engineer obtains the licensed copy through the company's normal channel and
uploads it like any other standard. Fetching a freely published source
automatically is the client's open decision 3 ("Is online lookup permitted,
and who approves retrieved documents?") and is not built.

THE LIFECYCLE, per cited identifier:
  MISSING_LOCALLY  cited, not held, nothing recorded (the default)
  REQUESTED        an engineer recorded that it has been asked for / ordered
  OBTAINED         a copy was uploaded and recorded as obtained externally
Once a copy is uploaded and matches, `cited_but_not_held` stops listing it by
itself (the same matcher selection uses), so OBTAINED is visible on the
held standard's provenance rather than on the missing list.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import standards_inventory
from .db import connect, schema_once

MISSING_LOCALLY = "MISSING_LOCALLY"
REQUESTED = "REQUESTED"
OBTAINED = "OBTAINED"

SOURCE_EXTERNAL = "external"

#: The publisher's own catalogue for each family. Fixed pages, no query
#: string: following a link sends no identifier, no project name, nothing
#: from a document (CLAUDE.md rule 1). Each checked 2026-09-29.
PUBLISHERS: tuple[tuple[re.Pattern, str, str, str], ...] = (
    (re.compile(r"^\s*API\b", re.I), "American Petroleum Institute (API)",
     "https://www.apiwebstore.org/", "Sold under licence"),
    (re.compile(r"^\s*ASME\b", re.I), "ASME",
     "https://www.asme.org/codes-standards/find-codes-standards", "Sold under licence"),
    (re.compile(r"^\s*ASTM\b", re.I), "ASTM International",
     "https://www.astm.org/products-services/standards-and-publications.html",
     "Sold under licence"),
    (re.compile(r"^\s*ISO\b", re.I), "ISO",
     "https://www.iso.org/search.html", "Sold under licence"),
    (re.compile(r"^\s*IEC\b", re.I), "IEC Webstore",
     "https://webstore.iec.ch/", "Sold under licence"),
    (re.compile(r"^\s*NFPA\b", re.I), "NFPA",
     "https://www.nfpa.org/for-professionals/codes-and-standards/list-of-codes-and-standards",
     "Sold under licence; NFPA also offers free read-only access online, "
     "which is not a copy this system may store"),
    (re.compile(r"^\s*(NACE|AMPP)\b", re.I), "AMPP (formerly NACE)",
     "https://store.ampp.org/nacestandards", "Sold under licence"),
    (re.compile(r"^\s*NORSOK\b", re.I), "Standards Norway (NORSOK)",
     "https://standard.no/en/sectors/petroleum/norsok-standards/",
     "Sold under licence (subscription, collection or single licence)"),
)

#: The client's own standards: obtained from the client, never a web source.
_COMPANY = re.compile(r"\bSAES\b|\bSAMSS\b|\bKOC\b|KOC-", re.I)
COMPANY_NOTE = ("Company standard - request it from the client's standards "
                "custodian and upload it")
UNKNOWN_NOTE = ("Publisher not recognised - identify the issuing body before "
                "requesting it")


def where_to_obtain(identifier: str) -> dict:
    """{publisher, url, note}. A company standard or an unrecognised one has
    no url - never a guessed site."""
    if _COMPANY.search(identifier or ""):
        return {"publisher": "Client (company standard)", "url": None,
                "note": COMPANY_NOTE}
    for pattern, publisher, url, note in PUBLISHERS:
        if pattern.search(identifier or ""):
            return {"publisher": publisher, "url": url, "note": note}
    return {"publisher": None, "url": None, "note": UNKNOWN_NOTE}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _key(identifier: str) -> str:
    from .applicability import normalise_identifier
    return normalise_identifier(identifier)


@schema_once
def ensure_schema() -> None:
    conn = connect()
    with conn:
        # One row per cited identifier someone has acted on. No row means
        # MISSING_LOCALLY - the state is never stored as a default.
        conn.execute("""CREATE TABLE IF NOT EXISTS standard_acquisitions (
            identifier_key TEXT PRIMARY KEY,
            identifier     TEXT NOT NULL,
            status         TEXT NOT NULL,
            note           TEXT,
            requested_by   TEXT,
            requested_at   TEXT,
            obtained_document_id TEXT,
            updated_at     TEXT NOT NULL)""")
        # Where a held standard's copy came from. A row only for a copy
        # recorded as obtained externally; the file's own hash is read from
        # `documents` at record time and kept, so a later re-upload under the
        # same id cannot silently inherit a provenance it never had.
        conn.execute("""CREATE TABLE IF NOT EXISTS document_provenance (
            document_id   TEXT PRIMARY KEY,
            source_type   TEXT NOT NULL,
            identifier    TEXT NOT NULL,
            obtained_from TEXT NOT NULL,
            sha256        TEXT NOT NULL,
            recorded_by   TEXT NOT NULL,
            recorded_at   TEXT NOT NULL)""")


def missing_standards(*, allowed_document_ids: frozenset[str]) -> list[dict]:
    """The cited-but-not-held list, each with where to obtain it and its
    acquisition status. Scope: exactly `cited_but_not_held`'s - never wider."""
    ensure_schema()
    rows = standards_inventory.cited_but_not_held(
        allowed_document_ids=allowed_document_ids)
    keys = [_key(r["identifier"]) for r in rows]
    recorded: dict[str, dict] = {}
    if keys:
        marks = ",".join("?" for _ in keys)
        recorded = {r["identifier_key"]: dict(r) for r in connect().execute(
            f"SELECT * FROM standard_acquisitions WHERE identifier_key IN ({marks})",
            keys)}
    out = []
    for row, key in zip(rows, keys):
        rec = recorded.get(key) or {}
        out.append({
            **row,
            "status": rec.get("status") or MISSING_LOCALLY,
            "note": rec.get("note"),
            "requested_by": rec.get("requested_by"),
            "requested_at": rec.get("requested_at"),
            "obtain": where_to_obtain(row["identifier"]),
        })
    return out


class AcquisitionError(ValueError):
    """The request cannot be recorded honestly. The message says why."""


def mark_requested(identifier: str, *, user_id: str, note: str | None,
                   allowed_document_ids: frozenset[str]) -> dict:
    """Record that a missing standard has been asked for. Only an identifier
    the caller can SEE on the missing list - never an arbitrary string, so
    this cannot be used to plant rows about standards nobody cited."""
    ensure_schema()
    key = _key(identifier)
    listed = {_key(r["identifier"]): r for r in standards_inventory.cited_but_not_held(
        allowed_document_ids=allowed_document_ids)}
    if not key or key not in listed:
        raise AcquisitionError("not a standard on your missing list")
    now = _now()
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO standard_acquisitions
                   (identifier_key, identifier, status, note, requested_by,
                    requested_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(identifier_key) DO UPDATE SET
                   status = excluded.status, note = excluded.note,
                   requested_by = excluded.requested_by,
                   requested_at = excluded.requested_at,
                   updated_at = excluded.updated_at""",
            (key, listed[key]["identifier"], REQUESTED, (note or "").strip() or None,
             user_id, now, now))
    return {"identifier": listed[key]["identifier"], "status": REQUESTED,
            "requested_by": user_id, "requested_at": now}


def record_external_copy(document_id: str, *, identifier: str, obtained_from: str,
                         user_id: str, allowed_document_ids: frozenset[str]) -> dict:
    """Mark an uploaded standard as a copy obtained externally (the client's
    'marked as externally obtained'), and close its acquisition as OBTAINED.

    The document must be one the caller may read and must be a standard in
    the library; `obtained_from` is required (a publisher, an order or
    licence reference) - a provenance record that names no source is not one.
    """
    ensure_schema()
    obtained_from = (obtained_from or "").strip()
    if not obtained_from:
        raise AcquisitionError("say where the copy was obtained from")
    if document_id not in allowed_document_ids:
        raise AcquisitionError("no such standard")
    doc = connect().execute(
        """SELECT d.sha256, c.document_role FROM documents d
           LEFT JOIN document_classification c ON c.document_id = d.id
           WHERE d.id = ?""", (document_id,)).fetchone()
    if doc is None or doc["document_role"] != "COMPANY_STANDARD":
        raise AcquisitionError("no such standard")
    key = _key(identifier)
    if not key:
        raise AcquisitionError("the standard's number is required")
    now = _now()
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO document_provenance
                   (document_id, source_type, identifier, obtained_from, sha256,
                    recorded_by, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(document_id) DO UPDATE SET
                   identifier = excluded.identifier,
                   obtained_from = excluded.obtained_from,
                   sha256 = excluded.sha256,
                   recorded_by = excluded.recorded_by,
                   recorded_at = excluded.recorded_at""",
            (document_id, SOURCE_EXTERNAL, identifier.strip(), obtained_from,
             doc["sha256"], user_id, now))
        conn.execute(
            """INSERT INTO standard_acquisitions
                   (identifier_key, identifier, status, obtained_document_id,
                    updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(identifier_key) DO UPDATE SET
                   status = excluded.status,
                   obtained_document_id = excluded.obtained_document_id,
                   updated_at = excluded.updated_at""",
            (key, identifier.strip(), OBTAINED, document_id, now))
    return provenance_of(document_id) or {}


def provenance_of(document_id: str) -> dict | None:
    """The recorded provenance of a held standard, or None (no record: not
    claimed either way). `current` is False when the file's hash no longer
    matches the one recorded - a replaced file does not inherit the record."""
    ensure_schema()
    row = connect().execute(
        """SELECT p.*, d.sha256 AS current_sha256 FROM document_provenance p
           JOIN documents d ON d.id = p.document_id WHERE p.document_id = ?""",
        (document_id,)).fetchone()
    if row is None:
        return None
    out = {k: row[k] for k in ("document_id", "source_type", "identifier",
                               "obtained_from", "sha256", "recorded_by", "recorded_at")}
    out["current"] = row["sha256"] == row["current_sha256"]
    return out
