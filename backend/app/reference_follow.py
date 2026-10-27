"""R8 (#772), second half: follow a cross-reference INTO the clause it names.

`standard_references` lists the standards the review's standards cite that the library does not
hold. Here, when a held standard says "per API 526, clause 5.2" and the library DOES hold API 526,
the held copy is searched for that clause, with the same reading the review already uses for a
datasheet's cited clauses (`standard_ids.clause_qualifiers` to read the citation,
`subject_scope._found_clauses` to find the clause in the cited standard's own text and stored
requirements). Each such citation ends in a named state, never silence:

  followed        the clause is in the held copy (its page is listed when a stored requirement gives one)
  clause_missing  the held copy of the cited standard has stored requirements but none in that clause
  other_edition   the citation names an edition the held copy is not: the clause number may differ
  several_editions the library holds the cited standard in more than one edition: not followed
  not_checked     the held copy has no stored requirements to search, or the clause reading is unsure
  in_range        a clause inside a printed range ("5.1 to 5.4"): the numbering may skip it, so it is counted, not followed
  whole           the citation names the standard alone: nothing to follow (counted)

Identifiers and counts only; no sentence of a document leaves this module. Read only, no model.
"""

from __future__ import annotations

import re
from collections import Counter

from . import applicability, standard_ids, subject_scope
from .db import connect

_EDITION_AFTER = re.compile(r"[-:,\s]*(?:19[5-9]|20[0-4])\d\b")
NOTE = "Clauses cited by the standards used here: followed into the held copy or not found - engineer to check"
#: Cited clauses named in the note; the rest are counted.
LISTED = 15


def _flat(standard_id: str) -> str:
    """The standard's page text joined, whitespace folded."""
    rows = connect().execute(
        "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no", (standard_id,)
    )
    return "".join(" ".join((r["text"] or "").split()) + " " for r in rows)


def _requirements(standard_id: str) -> list[dict]:
    return [
        dict(r)
        for r in connect().execute(
            "SELECT clause, page, source_text, requirement_text FROM standard_requirements "
            "WHERE standard_document_id = ?",
            (standard_id,),
        )
    ]


def _entry_edition(entry: dict) -> str | None:
    """The edition year a held copy is, from its number, file name or title; None when it states none."""
    for name in (
        entry.get("document_number"),
        entry.get("filename"),
        entry.get("title"),
    ):
        year = standard_ids.edition_of(name or "")
        if year:
            return year
    return None


def _targets(library: list[dict], raw: str) -> list[dict]:
    """Every held copy the citation `raw` names (more than one when two editions are held)."""
    return [
        entry
        for entry in library
        if any(
            standard_ids.same_standard(raw, name)
            for name in applicability._library_names(entry)
        )
    ]


def _page_of(clause, rows: list[dict]) -> int | None:
    """The first page a stored requirement of that clause (or a part of it) is on."""
    pages = [
        r["page"]
        for r in rows
        if r.get("page") and subject_scope._stored_clause_in(r.get("clause"), clause)
    ]
    return min(pages) if pages else None


def _item(source, target, clause, state, page=None) -> dict:
    return {
        "source": source,
        "target": target,
        "clause": clause,
        "state": state,
        "page": page,
    }


def follow(used: list[str], allowed: frozenset[str]) -> dict:
    """{"checked": [{source, target, clause, state, page}], "whole": n, "unread": n} for the
    standards a run used. `source`/`target` are document ids, `clause` the clause as an engineer
    writes it. A source the caller may not read is counted unread and never followed."""
    from . import standard_references  # late: it imports this module

    library = standard_references._held_library(allowed)
    by_id = {entry["id"]: entry for entry in library}
    out: list[dict] = []
    whole: set[tuple[str, str]] = set()
    unread = 0
    requirements: dict[str, list[dict]] = {}
    texts: dict[str, subject_scope.StandardText] = {}
    for source in used:
        flat = _flat(source) if source in allowed else ""
        if not flat.strip():
            unread += 1
            continue
        for entry, start, stop in applicability._citations_in(flat, library):
            if entry["id"] == source:
                continue
            raw = flat[start:stop]
            year = _EDITION_AFTER.match(
                flat, stop
            )  # "XYZ-100-2019 clause 5.2": step over the year
            clauses = standard_ids.clause_qualifiers(
                flat, start, year.end() if year else stop
            )
            if clauses is None:  # the clauses could not be read for certain
                out.append(
                    _item(source, entry["id"], "(clause not readable)", "not_checked")
                )
                continue
            if not clauses:
                whole.add((source, entry["id"]))
                continue
            held = [t for t in _targets(library, raw) if t["id"] != source] or [entry]
            cited = standard_ids.edition_of(flat[start : stop + 24])
            ambiguous = len(held) > 1
            wrong_edition = (
                not ambiguous and cited and _entry_edition(held[0]) not in (None, cited)
            )
            target = held[0]
            rows = requirements.setdefault(target["id"], _requirements(target["id"]))
            found = {}
            if rows and not ambiguous and not wrong_edition:
                if target["id"] not in texts:
                    texts[target["id"]] = subject_scope.StandardText(
                        subject_scope.standard_pages(target["id"])
                    )
                found = subject_scope._found_clauses(texts[target["id"]], rows, clauses)
            for clause in clauses:
                label = standard_ids.clause_label(clause)
                if getattr(clause, "in_range", False):
                    state = (
                        "in_range"  # inside a printed range: the numbering may skip it
                    )
                elif ambiguous:
                    state = "several_editions"
                elif wrong_edition:
                    state = "other_edition"
                elif not rows or not getattr(clause, "sure", True):
                    state = "not_checked"
                else:
                    state = "followed" if clause in found else "clause_missing"
                page = _page_of(clause, rows) if state == "followed" else None
                out.append(_item(source, target["id"], label, state, page))
    # one line per (source, target, clause): the same citation printed twice counts once
    seen: dict[tuple, dict] = {}
    for item in out:
        seen.setdefault((item["source"], item["target"], item["clause"]), item)
    return {
        "checked": list(seen.values()),
        "whole": len(whole),
        "unread": unread,
        "by_id": by_id,
    }


def _natural(label: str) -> list:
    """Sort key that reads 8.2 before 8.10."""
    return [int(p) if p.isdigit() else p.lower() for p in re.findall(r"\d+|\D+", label)]


def notes(result: dict) -> list[dict]:
    """The Review note (internal, never a contractor comment), or [] when no clause was cited."""
    checked = result["checked"]
    if not checked:
        return []
    states = Counter(item["state"] for item in checked)
    by_id = result["by_id"]

    def name(doc_id: str) -> str:
        entry = by_id.get(doc_id) or {}
        return (
            entry.get("document_number") or entry.get("filename") or "a held standard"
        )

    def listed(state: str, with_page: bool = False) -> str:
        lines = sorted(
            {
                f"{name(i['target'])} {i['clause']}"
                + (f" p.{i['page']}" if with_page and i["page"] else "")
                + f" (cited by {name(i['source'])})"
                for i in checked
                if i["state"] == state
            },
            key=_natural,
        )
        more = len(lines) - LISTED
        return "; ".join(lines[:LISTED]) + (f" and {more} more" if more > 0 else "")

    parts = [
        f"{len(checked)} clause reference(s) in the standards used name a standard the library holds: "
        f"{states['followed']} found in the held copy, {states['clause_missing']} not found in its "
        f"text or requirements, {states['not_checked']} not checked (no stored requirements to search, "
        f"or the clause could not be read for certain), {states['other_edition']} cite another "
        f"edition than the held one, {states['several_editions']} name a standard held in several "
        f"editions, {states['in_range']} inside a printed range (counted, not followed)."
    ]
    if states["followed"]:
        parts.append(f"Found: {listed('followed', with_page=True)}.")
    if states["clause_missing"]:
        parts.append(f"Not found: {listed('clause_missing')}.")
    if result["whole"]:
        parts.append(
            f"{result['whole']} cited standard(s) are named alone (no clause); nothing to follow."
        )
    if result["unread"]:
        parts.append(
            f"{result['unread']} standard(s) used had no readable text or may not be read by this user."
        )
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
