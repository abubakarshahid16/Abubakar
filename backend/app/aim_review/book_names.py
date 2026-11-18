"""A held book is never "not held" (owner, 18 Nov 2026 after live: four held company books were listed "not held" by the valve and
vessel reviews and never used). The AI's "needed, not in the catalog"
names are resolved by the identifier inside the name, with THE app's lookup (`applicability.find_standard`, which reads family,
number and part; no new number reader, no name shape): a held rule book on the shown list is used; a held one not on the list is
counted as "held, not on the list" (the next plan lists it); only a name no held book answers stays "not held". Read by code;
nothing is sent."""

from __future__ import annotations

import logging
import re

from . import library as L

log = logging.getLogger(__name__)

#: A name the AI gives may carry several identifiers ("QX-D-1 / QX-D-2 vessel design"): each part is looked up.
_PARTS = re.compile(r"\s*(?:/|;|,|\band\b|\bor\b)\s*", re.IGNORECASE)


def held_book(lib: list[dict], name: str) -> dict | None:
    """The held RULE BOOK a name answers (`library.is_rule_book`), by the whole name, else by each of its parts; or None."""
    from app import applicability

    books = [e for e in lib if L.is_rule_book(e)]
    for part in [name, *(p for p in _PARTS.split(str(name or "")) if p.strip())]:
        found = applicability.find_standard(books, part)
        if found is not None:
            return found
    return None


def sort_needed(
    conn,
    paper_id: str,
    rows: list[dict],
    allowed: frozenset[str],
    kind: str | None,
    gate_ok,
) -> tuple[list[str], list[str], list[dict]]:
    """The AI's needed names split three ways: (held ids on the shown list that may serve, held ids NOT on the list, the rows no
    held book answers: "not held"). A held book serves when it is usable, its role applies to the kind and the send gate allows
    it; else it is held but not usable here (counted with "not on the list", never "not held")."""
    lib = L.library(conn, exclude=frozenset({str(paper_id)}))
    use: list[str] = []
    unlisted: list[str] = []
    not_held: list[dict] = []
    for row in rows:
        e = held_book(lib, str(row.get("name") or ""))
        if e is None:
            not_held.append(row)
        elif (
            e["id"] in allowed
            and L.usable(e)
            and L.role_applies(e, kind)
            and not gate_ok(e["id"])
        ):
            if e["id"] not in use:
                use.append(e["id"])
        elif e["id"] not in unlisted:
            unlisted.append(e["id"])
    return use, unlisted, not_held


def last_run_type(conn, paper_id: str) -> str | None:
    """The equipment type the paper's newest ENDED general review named (S1), when the app stores none: the plan then puts the
    books governing that type first. A recorded reading of the app's own run; None when there is none or it is not a known type."""
    import json

    from app import aim_review_store

    try:
        run = aim_review_store.latest_run(conn, str(paper_id), ended=True)
    except Exception as exc:  # noqa: BLE001 - no stored run is no hint
        log.info("general review plan: last run unreadable (%s)", type(exc).__name__)
        return None
    try:
        etype = (json.loads((run or {}).get("identity_json") or "{}") or {}).get(
            "equipment_type"
        )
    except (TypeError, ValueError):
        return None
    return etype if etype in L.type_ids() else None


def as_chosen(conn, ids: list[str], cat: list[dict], why: str) -> list[dict]:
    """The chosen-book lines (`checklist._chosen`'s shape) of held books the AI named as needed: their catalog line when the
    catalog holds one, else a text-only line (the book's pages are read, as for a cited book with no labelled rule)."""
    by_cat = {c["book"]: c for c in cat}
    by_id = {e["id"]: e for e in L.library(conn, within=frozenset(ids))}
    out = []
    for b in ids:
        # a book with no rule for this type is not in the catalog: it gets the next alias (S3 maps every chosen book by alias)
        line = by_cat.get(b) or {"book": b, "identifier": L.identifier_of(by_id[b]) if b in by_id else b,
                                 "committee": (by_id.get(b) or {}).get("committee") or "", "rules": 0, "tagged": 0,
                                 "subjects": [], "text_only": True, "required": False,
                                 "alias": f"B{len(cat) + 1 + sum(1 for x in out if x['book'] not in by_cat):02d}"}  # fmt: skip
        out.append({**line, "why": why, "chosen_subjects": "all"})
    return out


def apply_needed(
    conn,
    paper_id: str,
    out: dict,
    result: dict,
    want: dict,
    cat,
    allowed,
    kind,
    gate_ok,
) -> None:
    """S2's answer, after the chosen books: the AI's "needed, not in the catalog" names sorted by `sort_needed`: held books on the
    list join the chosen books, held ones not on the list join "unlisted", only the rest are "not held" (with the table's
    not-held names, `checklist.wanted`)."""
    needed = [{"name": str(r.get("name") or "")[:80], "why": str(r.get("why") or "")[:80], "source": "AI: needed, not in the catalog"}
              for r in out.get("not_held_needed") or [] if isinstance(r, dict) and str(r.get("name") or "").strip()]  # fmt: skip
    use, unlisted, not_held = sort_needed(
        conn, paper_id, needed, allowed, kind, gate_ok
    )
    have = {c["book"] for c in result["books"]}
    result["books"] += as_chosen(
        conn, [b for b in use if b not in have], cat, "AI: needed; held"
    )
    result["unlisted"] = list(dict.fromkeys([*result["unlisted"], *unlisted]))
    result["not_held"] = want["not_held"] + not_held


def paper_cited(conn, paper_id: str, within: frozenset[str]) -> frozenset[str]:
    """The held books the paper's own stored citations name (resolved by code, `library.resolve`; ids only, as the plan lists them
    "cited by the paper"), among `within`: never cut by the checklist's book cap."""
    lib = L.library(conn, exclude=frozenset({str(paper_id)}))
    found = (L.resolve(lib, name) for name in L._paper_citations(conn, str(paper_id)))
    return frozenset(e["id"] for e in found if e and e["id"] in within)


def resort_saved(
    conn, paper_id: str, not_held, allowed, kind, gate_ok
) -> tuple[list[str], list[str], list[dict]]:
    """A SAVED checklist's not-held list, sorted again for this paper (a checklist saved before the held-name rule, or before a
    book was held): (held ids on the shown list that may serve now: then the checklist is built again, not reused; held ids not
    on the list; the rows that stay "not held": the table's names as saved, and the AI's names no held book answers)."""
    from . import checklist as CL

    rows = [r for r in not_held or [] if isinstance(r, dict)]
    table = [r for r in rows if r.get("source") in CL.WANTED_SOURCES]
    ai = [r for r in rows if r.get("source") not in CL.WANTED_SOURCES]
    use, unlisted, still = sort_needed(conn, paper_id, ai, allowed, kind, gate_ok)
    return use, unlisted, table + still
