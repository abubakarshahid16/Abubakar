"""R8 (#772): a standard the library's standards cite but the library does not hold is LISTED,
never silently ignored.

A clause that says "per API 526" or "in accordance with ISO 15156" rests on a standard the review
cannot check unless the library holds it. Here the standards a review used are read for the
standards they cite, each citation is looked up in the library by `applicability.find_standard`
(the one lookup of #452), and the ones no held copy answers to become ONE Review note: how many,
which, and how many of the standards used cite them.

HONEST THREE WAYS: held (nothing said), not held (listed), and not read (a standard with no
chunks is counted, never read as "cites nothing"). A superseded copy is still a held copy. A
standard's own number is not a reference to another standard. Identifiers only: the note carries
standard numbers and counts, never a sentence of a document. Read only; no network; no model.
"""

from __future__ import annotations

from . import applicability, standard_ids
from .db import connect
from .standards import COMPANY_STANDARD, _scope_clause

NOTE = "Standards cited by the standards used here are not in the library - engineer to check"
#: Identifiers named in the note; the rest are counted.
LISTED = 15


def _held_library(allowed: frozenset[str]) -> list[dict]:
    """Every standard the caller may read, superseded and waiting-for-confirmation included:
    held is held. Same entry shape as `applicability._library`."""
    where, args = _scope_clause(allowed, "d.id")
    rows = (
        connect()
        .execute(
            "SELECT d.id, d.filename, c.document_number, c.title, c.discipline, c.equipment_type,"
            " c.service, c.project FROM documents d"
            " JOIN document_classification c ON c.document_id = d.id"
            + where
            + " AND c.document_role = ?",
            [*args, COMPANY_STANDARD],
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def cited_by(standard_ids_used: list[str], allowed: frozenset[str]) -> tuple[dict, int]:
    """({identifier key: {"identifier": as first printed, "by": set of document ids}}, how many
    of the standards had no readable chunk). A standard is never listed as citing itself."""
    cited: dict[str, dict] = {}
    unread = 0
    library = {entry["id"]: entry for entry in _held_library(allowed)}
    for doc_id in standard_ids_used:
        where, args = _scope_clause(allowed, "document_id")
        rows = (
            connect()
            .execute(
                "SELECT text FROM chunks" + where + " AND document_id = ?",
                [*args, doc_id],
            )
            .fetchall()
        )
        if not rows:
            unread += 1
            continue
        own = library.get(doc_id) or {}
        own_names = applicability._library_names(own)
        for row in rows:
            for raw, _start, _end in standard_ids.find_citations(row["text"] or ""):
                if any(standard_ids.same_standard(raw, name) for name in own_names):
                    continue
                entry = cited.setdefault(
                    standard_ids.key(raw), {"identifier": raw, "by": set()}
                )
                entry["by"].add(doc_id)
    return cited, unread


def not_held(
    standard_ids_used: list[str], allowed: frozenset[str]
) -> tuple[list[dict], int, int]:
    """(the cited standards no held copy answers to, as {identifier, cited_by}; how many of the
    standards used were not read; how many standards were used). Sorted by identifier."""
    cited, unread = cited_by(standard_ids_used, allowed)
    library = _held_library(allowed)
    missing = [
        {"identifier": item["identifier"], "cited_by": len(item["by"])}
        for item in cited.values()
        if applicability.find_standard(library, item["identifier"]) is None
    ]
    return (
        sorted(missing, key=lambda m: m["identifier"].upper()),
        unread,
        len(standard_ids_used),
    )


def notes(missing: list[dict], unread: int, used: int) -> list[dict]:
    """The Review notes (internal, never a contractor comment)."""
    if not missing:
        return []
    shown = ", ".join(
        f"{m['identifier']} (cited by {m['cited_by']})" for m in missing[:LISTED]
    )
    more = len(missing) - LISTED
    tail = f" and {more} more" if more > 0 else ""
    not_read = (
        f" {unread} of the {used} standards had no readable text and are not counted."
        if unread
        else ""
    )
    return [
        {
            "note": NOTE,
            "standard": "",
            "count": len(missing),
            "detail": (
                f"{len(missing)} standards cited by the {used} standards used in this review are not "
                f"held in the library, so what they require was not checked: {shown}{tail}.{not_read}"
            ),
        }
    ]


def for_run(review_run_id: str, allowed: frozenset[str]) -> list[dict]:
    """The Review notes of one run. A check that cannot run is said (the error's type only),
    never skipped silently and never fatal to the export."""
    try:
        used = [
            r["standard_document_id"]
            for r in connect().execute(
                "SELECT standard_document_id FROM review_applicable_standards"
                " WHERE review_run_id = ? AND COALESCE(included, 1) = 1",
                (review_run_id,),
            )
        ]
        return notes(*not_held(used, allowed))
    except Exception as exc:  # noqa: BLE001 - a side note must not fail the CRS content
        return [
            {
                "note": NOTE,
                "standard": "",
                "count": None,
                "detail": f"The cross-reference check could not run ({type(exc).__name__}).",
            }
        ]
