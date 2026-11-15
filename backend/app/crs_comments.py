"""ONE COMMENT PER FIELD (owner order P2, 15 Nov 2026): the CRS comment sheet reads like an engineer's, not like a log of every ask.

The grouping is ONE pure function (`group`), used by the CRS file and by the page's listing, so the page and the file always show the
same comments. The key is general (rule 13): the paper's field (the point's name with its tag list taken off) and its tag set; a point
with no field is grouped by its rule book's clause, else it stands alone. Nothing is dropped: every underlying point stays as its own
row on the sheet Evidence, linked by the comment number.

  strongest status wins    Fail > Not met > Query > Met > Does not apply: the comment takes the class words of its strongest point
                           (a proven Fail keeps its own class); a class is never raised by merging.
  a contradiction          a Met point and a Not met point on one field are NOT merged silently: the comment says "the readers
                           disagree on this field" and is a Query.
  every clause listed      each member's (rule book, clause, page) is on the comment, and every page and tag it applies to.

A point an engineer removed is not part of a comment (it stays on Evidence and in the record of removals). No model, no network.
"""

from __future__ import annotations

import re

from . import review_point_decisions as decisions_mod
from . import review_points as rp
from .crs_export_quality import NOTE_PARKED

DISAGREE = "the readers disagree on this field"
DISAGREE_RANK = 4  # a Query: the point's own question rank
_NOT_MET, _MET = ("not_met",), ("met",)


def _norm(text) -> str:
    return " ".join(str(text or "").split()).lower()


_PAGE_LABEL = re.compile(r"^(?:pp?|pages?)\.?\s*\d+(?:\s*[-,]\s*\d+)*$", re.IGNORECASE)
_SECTION_TITLE = re.compile(
    r"^(?:(?:section|clause|annex|appendix|table|figure)\b|\d+(?:\.\d+)+\s)",
    re.IGNORECASE,
)
_PARKED = _norm(NOTE_PARKED).split(" - ")[0]


def is_parked(text) -> bool:
    """True when `text` IS the stored placeholder of a rule-check row an engineer has not decided (`NOTE_PARKED`): recognised by what
    it is, never by words that an engineer's own sentence may also use."""
    return _norm(text).startswith(_PARKED)


def is_field(name: str) -> bool:
    """A real field name: not empty, not a page label ("p.22"), not the parked placeholder, not a section title. General: no word
    list of any paper."""
    n = " ".join(str(name or "").split())
    return bool(n) and not (
        _PAGE_LABEL.match(n) or is_parked(n) or _SECTION_TITLE.match(n)
    )


def _field_of(point: dict) -> str:
    """The point's field: its name with the tag list taken off by `review_points.split_tags` (called, never copied: the tag scanner
    is review_points', #1823); "" when the name is not a field."""
    name = rp.split_tags(point.get("name") or "")[0]
    return _norm(name) if is_field(name) else ""


def key_of(point: dict) -> str:
    """The comment a point belongs to: its FIELD (the tags and pages it applies to are listed on the comment, they do not split it);
    a point whose name is not a field, by its rule book and clause; else the point itself."""
    field = _field_of(point)
    if field:
        return f"field|{field}"
    book, clause = _norm(point.get("rule_book")), _norm(point.get("clause"))
    if book and clause:
        return f"clause|{book}|{clause}"
    return f"point|{point.get('id')}"


def _clauses(members: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for p in members:
        ref = p.get("rule_ref") or {}  # a cited standard the review names but holds no document for: the reference as stored
        books = (
            [b["name"] for b in p.get("books") or []]
            or ([p["rule_book"]] if p.get("rule_book") else [])
            or ([ref["name"]] if ref.get("name") else [])
        )
        for book in books or [None]:
            if not book and not p.get("clause"):
                continue
            seen.setdefault(
                (book, p.get("clause"), p.get("page")),
                {"book": book, "clause": p.get("clause"), "page": p.get("page")},
            )
    return list(seen.values())


def group(points: list[dict]) -> list[dict]:
    """The comments of a list of points (raw or public), in the order of their first point (worst first). Removed points are left out.
    Each comment: number, key, name, member_ids, n_points, rank, tile, pill, firm, strongest (the point whose words lead), pages,
    tags, clauses, disagree."""
    order: list[str] = []
    members: dict[str, list[dict]] = {}
    for p in points:
        if (p.get("decision") or {}).get("state") == decisions_mod.REMOVE:
            continue
        k = key_of(p)
        if k not in members:
            order.append(k)
            members[k] = []
        members[k].append(p)
    out = []
    for number, k in enumerate(order, start=1):
        ms = members[k]
        strongest = min(
            ms, key=lambda p: p["rank"]
        )  # rank 1 is the worst: the strongest status
        tiles = {p.get("tile") for p in ms}
        disagree = bool(tiles & set(_NOT_MET)) and bool(tiles & set(_MET))
        lead = (
            min(
                (p for p in ms if p.get("tile") == "questions"),
                key=lambda p: p["rank"],
                default=None,
            )
            if disagree
            else strongest
        ) or strongest
        rank = DISAGREE_RANK if disagree else strongest["rank"]
        tags = sorted({t for p in ms for t in p.get("tags") or []})
        pages = sorted({p["page"] for p in ms if p.get("page")})
        out.append(
            {
                "number": number,
                "key": k,
                "name": strongest.get("name"),
                "member_ids": [p["id"] for p in ms],
                "n_points": len(ms),
                "rank": rank,
                "tile": rp.TILE_OF_RANK[rank],
                "pill": (
                    f"Question · {DISAGREE}"
                    if disagree
                    else strongest.get("pill") or rp.RANKS[rank][0]
                ),
                "firm": None if disagree else strongest.get("firm"),
                "strongest": lead if disagree else strongest,
                "pages": pages,
                "tags": tags,
                "clauses": _clauses(ms),
                "book_held": any(p.get("_book_docs") or p.get("_book_doc") for p in ms),  # cites a held book (named or not)
                "disagree": disagree,
            }
        )
    # WORST FIRST (U5): by the comment's own rank (its strongest point: proven Fail, two-reader not met, AI not met, question, met), then
    # by its highest priority, then the order its first point came in; numbers follow the final order.
    def worst(i_c: tuple[int, dict]) -> tuple[int, int, int]:
        ms = members[i_c[1]["key"]]
        top = min((rp.PRIORITY_ORDER.get(p.get("priority") or "", 3) for p in ms), default=3)
        return (i_c[1]["rank"], top, i_c[0])

    out = [c for _i, c in sorted(enumerate(out), key=worst)]
    for number, c in enumerate(out, start=1):
        c["number"] = number
    return out


def public(comment: dict) -> dict:
    """The comment as the page's listing carries it: the strongest point object is left out (the points are in the listing)."""
    return {k: v for k, v in comment.items() if k != "strongest"}
