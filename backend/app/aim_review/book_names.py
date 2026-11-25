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
    found = (
        e for e, _n in L.cited_rule_books(conn, str(paper_id))
    )  # rule books only, before the reader's narrowing
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


def new_required(
    conn, paper_id: str, saved: dict, listed, cited, allowed, kind, gate_ok
) -> list[str]:
    """The books this run requires that a SAVED checklist does not rest on (then it is built again, not reused): the type's
    governing and method books on the shown list (`listed`), and the held books the paper cites (the job's ids, `cited`, and
    the paper's own stored citations), each usable here, its role applying to the kind and the send gate allowing it, so a
    book the build itself would leave out never forces a build again. 18 Nov 2026: a newly uploaded company book that a paper
    cites, never named in the tables or by the AI, was not used while a saved checklist of the type was reused."""
    lib = {
        e["id"]: e
        for e in L.library(
            conn, exclude=frozenset({str(paper_id)}), within=frozenset(allowed)
        )
    }
    want = (
        set(listed or ())
        | set(cited or ())
        | set(paper_cited(conn, paper_id, frozenset(lib)))
    )
    have = set(L.saved_books(saved))
    return sorted(
        b
        for b in want - have
        if b in lib
        and L.usable(lib[b])
        and L.role_applies(lib[b], kind)
        and not gate_ok(b)
    )


#: Why a standard the paper cites is on the not-held list (it was read by the AI on the paper and verified by code there).
WHY_CITED_NOT_HELD = "cited by the paper; not held"


def with_cited_not_held(conn, paper_id: str, cited, not_held: list[dict]) -> list[dict]:
    """The run's not-held list, plus each standard the paper ITSELF cites that no held document answers (18 Nov 2026: a paper
    citing a book with a new numbering three times never named it "cited, not held": the not-held list came only from the type's
    tables and the book choice, which never sees the paper). A cited name counts only when S1's quote naming it was found by code
    on its page (`verified`) AND the name stands in that quote (no name-shape rule: the paper's own words decide); it is said once."""
    lib = L.library(conn, exclude=frozenset({str(paper_id)}))
    have = {
        L._fold(str(n.get("name") or "")) for n in not_held or [] if isinstance(n, dict)
    }
    out = list(not_held or [])
    for c in [*(cited or []), *L.citation_evidence(conn, paper_id)]:
        if not isinstance(c, dict) or not c.get("verified"):
            continue
        name = " ".join(
            str(c.get("name") or "").split()
        )  # whole: never cut without a mark
        folded = L._fold(name)
        if (
            len(folded) < 3
            or folded not in L._fold(str(c.get("quote") or ""))
            or folded in have
        ):
            continue
        if (
            L.resolve(lib, name) is not None
        ):  # held (a rule book, or a paper of another role): never "not held"
            continue
        page = c.get("page") if isinstance(c.get("page"), int) else None
        out.append({"name": name, "why": WHY_CITED_NOT_HELD, "source": "the paper cites it (read on the paper, verified)",
                    "page": page, "quote": str(c.get("quote") or "")})  # whole (a verified quote)  # fmt: skip
        have.add(folded)
    return out


def cited_points(not_held: list[dict]) -> list[dict]:
    """One point per standard the paper cites that is not held (lead 4, 18 Nov 2026: "the check left open"): a Question on All
    points, "Cited by the paper (page N); the book is not held, so its requirements were not checked.", with the verified quote
    and its page; never a sent comment (`CITED_NOT_HELD` is a not-sent note), so the contractor sees no noise. Completeness
    counts it like any point."""
    from . import CITED_NOT_HELD

    out = []
    for n, nh in enumerate(
        [
            x
            for x in not_held or []
            if isinstance(x, dict) and x.get("why") == WHY_CITED_NOT_HELD
        ],
        1,
    ):
        page = nh.get("page")
        where = f" (page {page})" if page else ""
        out.append({"item_id": f"CNH{n:02d}", "label": "Question", "field": nh["name"], "page": page, "quote": nh.get("quote") or "",
                    "comment": f"Cited by the paper{where}; the book is not held, so its requirements were not checked.",
                    "standard": nh["name"], "source": "cited by the paper (book not held)", "topic": f"Cited standard {nh['name']}",
                    "code": CITED_NOT_HELD, "code_compare": None, "deferred": False, "ask": ""})  # fmt: skip
    return out


def unique_not_held(not_held: list[dict]) -> list[dict]:
    """The not-held list with each standard said ONCE, by `library.identifier_key` (the same key as citation matching): one number spelled with or without a dash, a "Pt-2" and a "Part II", a table name and the AI's longer name of the same standard are one;
    the first stays (the tables come first)."""
    seen, out = set(), []
    for n in not_held or []:
        key = (
            L.identifier_key(str((n or {}).get("name") or ""))
            if isinstance(n, dict)
            else ""
        )
        if not key or key not in seen:
            seen.add(key)
            out.append(n)
    return out
