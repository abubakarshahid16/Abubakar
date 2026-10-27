"""R8 (#772), second half: follow a cross-reference INTO the clause it names.

`standard_references` lists the standards the review's standards cite that the library does not
hold. Here, when a held standard says "per API 526, clause 5.2" and the library DOES hold API 526,
the held copy is searched for that clause, with the same reading the review already uses for a
datasheet's cited clauses (`standard_ids.clause_qualifiers` to read the citation,
`subject_scope._found_clauses` to find the clause in the cited standard's own text and stored
requirements). Each such citation ends in one of four named states, never silence:

  followed        the clause is in the held copy (page numbers are in `subject_scope`, not here)
  clause_missing  the held copy of the cited standard has stored requirements but none in that clause
  not_checked     the held copy has no stored requirements to search, or the clause reading is unsure
  in_range        a clause inside a printed range ("5.1 to 5.4"): the numbering may skip it, so it is counted, not followed
  whole           the citation names the standard alone: nothing to follow (counted)

Identifiers and counts only; no sentence of a document leaves this module. Read only, no model.
"""

from __future__ import annotations

from collections import Counter

from . import applicability, standard_ids, subject_scope
from .db import connect

NOTE = "Clauses cited by the standards used here: followed into the held copy or not found - engineer to check"
#: Cited clauses named in the note; the rest are counted.
LISTED = 15


def _flat(standard_id: str) -> tuple[str, list[tuple[int, int]]]:
    """The standard's page text joined (whitespace folded) and the offset where each page starts."""
    starts: list[tuple[int, int]] = []
    flat = ""
    for row in connect().execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
        (standard_id,),
    ):
        starts.append((len(flat), row["page_no"]))
        flat += " ".join((row["text"] or "").split()) + " "
    return flat, starts


def _requirements(standard_id: str) -> list[dict]:
    return [
        dict(r)
        for r in connect().execute(
            "SELECT clause, page, source_text, requirement_text FROM standard_requirements "
            "WHERE standard_document_id = ?",
            (standard_id,),
        )
    ]


def follow(used: list[str], allowed: frozenset[str]) -> dict:
    """{"checked": [{source, target, clause, state}], "whole": n, "unread": n} for the standards a
    run used. `source`/`target` are document ids, `clause` the clause as an engineer writes it."""
    from . import standard_references  # late: it imports this module

    library = standard_references._held_library(allowed)
    by_id = {entry["id"]: entry for entry in library}
    out: list[dict] = []
    whole = 0
    unread = 0
    requirements: dict[str, list[dict]] = {}
    for source in used:
        flat, _starts = _flat(source)
        if not flat.strip():
            unread += 1
            continue
        for entry, start, stop in applicability._citations_in(flat, library):
            if entry["id"] == source:
                continue
            clauses = standard_ids.clause_qualifiers(flat, start, stop)
            if not clauses:
                whole += 1
                continue
            rows = requirements.setdefault(entry["id"], _requirements(entry["id"]))
            found = {}
            if rows:
                text = subject_scope.StandardText(
                    subject_scope.standard_pages(entry["id"])
                )
                found = subject_scope._found_clauses(text, rows, clauses)
            for clause in clauses:
                if getattr(clause, "in_range", False):
                    state = (
                        "in_range"  # inside a printed range: the numbering may skip it
                    )
                elif not rows or not getattr(clause, "sure", True):
                    state = "not_checked"
                else:
                    state = "followed" if clause in found else "clause_missing"
                out.append(
                    {
                        "source": source,
                        "target": entry["id"],
                        "clause": standard_ids.clause_label(clause),
                        "state": state,
                    }
                )
    # one line per (source, target, clause): the same citation printed twice counts once
    seen: dict[tuple, dict] = {}
    for item in out:
        seen.setdefault((item["source"], item["target"], item["clause"]), item)
    return {
        "checked": list(seen.values()),
        "whole": whole,
        "unread": unread,
        "by_id": by_id,
    }


def notes(result: dict) -> list[dict]:
    """The Review note (internal, never a contractor comment), or [] when no clause was cited."""
    checked = result["checked"]
    if not checked:
        return []
    states = Counter(item["state"] for item in checked)
    by_id = result["by_id"]

    def name(doc_id: str) -> str:
        entry = by_id.get(doc_id) or {}
        return entry.get("document_number") or entry.get("filename") or doc_id

    missing = sorted(
        {
            f"{name(i['target'])} {i['clause']} (cited by {name(i['source'])})"
            for i in checked
            if i["state"] == "clause_missing"
        }
    )
    shown = "; ".join(missing[:LISTED])
    more = len(missing) - LISTED
    tail = f" and {more} more" if more > 0 else ""
    parts = [
        f"{len(checked)} clause reference(s) in the standards used name a standard the library holds: "
        f"{states['followed']} found in the held copy, {states['clause_missing']} not found, "
        f"{states['not_checked']} not checked (the held copy has no stored requirements to search, "
        f"or the clause could not be read for certain), {states['in_range']} inside a printed range "
        "(counted, not followed)."
    ]
    if missing:
        parts.append(f"Not found in the held copy: {shown}{tail}.")
    if result["whole"]:
        parts.append(
            f"{result['whole']} further citation(s) name the standard alone; nothing to follow."
        )
    if result["unread"]:
        parts.append(f"{result['unread']} standard(s) used had no readable text.")
    return [
        {
            "note": NOTE,
            "standard": "",
            "count": states["clause_missing"],
            "detail": " ".join(parts),
        }
    ]


def for_run(used: list[str], allowed: frozenset[str]) -> list[dict]:
    """The Review notes for a run's standards. A check that cannot run is said (the error's type
    only), never skipped silently and never fatal to the export."""
    try:
        return notes(follow(used, allowed))
    except Exception as exc:  # noqa: BLE001 - a side note must not fail the CRS content
        return [
            {
                "note": NOTE,
                "standard": "",
                "count": None,
                "detail": f"The clause-following check could not run ({type(exc).__name__}).",
            }
        ]
