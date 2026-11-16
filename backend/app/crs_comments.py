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

NOT A COMMENT (order 14 lane B, owner 16 Nov 2026: "drop noise rows, merge repeats, move 'N rules not matched' to a coverage note").
A field whose points carry no finding is not a comment: every point on it is met (nothing to change), or none of it applies or was
checked (does not apply, rule not yet approved, not reviewed), or it is a "N rules could not be matched" line (one coverage note,
`coverage_note`). `group` returns the comments only; `set_aside` returns the rest with what each is called (`not_a_comment`). Nothing
is dropped: each such point stays on the sheet Evidence and is counted on the first sheet. A met point on a field that also has a
finding stays IN that comment (a disagreement is never hidden).

FIELD KEY. The field is folded (`fold_field`: lower case, only letters and digits kept: "Over pressure %" = "Overpressure"; text in
brackets is kept, R61); an AI point's field is its stored line's field (`crs_ai_workbook.field_name`), never
the name the page gives a point with no field. A topic is the rule book's key (`standard_ids.key`) and the clause.
"""

from __future__ import annotations

import re

from . import crs_ai_words as words
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


def fold_field(name) -> str:
    """The field folded for comparison: lower case, only letters and digits kept ("Over pressure %" = "Overpressure"). Text in brackets
    is KEPT: a bracket that is part of the name is part of the field (R61: "Gas (H2 and CO2 content)" is not "Gas"); a tag list is
    already off (`review_points.split_tags`)."""
    return re.sub(r"[^0-9a-z]+", "", _norm(name))


def _clause_key(clause) -> str:
    c = re.sub(r"^(?:clause|section|para(?:graph)?)\.?\s*", "", _norm(clause))
    return c.replace(" ", "")


def _book_key(book) -> str:
    from .standard_ids import key

    return key(str(book or "")) or _norm(book)


def _line_of(point: dict) -> dict:
    line = point.get("_line")
    return line if isinstance(line, dict) else {}


def is_coverage(point: dict) -> bool:
    """A "N rules of a book could not be matched to a field" line (rule choice v2): a coverage note, never a comment."""
    return _line_of(point).get("source") == "group"


def _field_of(point: dict) -> str:
    """The point's field: an AI point's stored line's field (`crs_ai_workbook.field_name`), else its name, with the tag list taken off
    by `review_points.split_tags` (called, never copied: the tag scanner is review_points', #1823); "" when it is not a field. The name
    the page gives an AI point with no field (its rule, or a fixed phrase) is never a field."""
    line = _line_of(point)
    if line:
        from . import crs_ai_workbook

        name = rp.split_tags(crs_ai_workbook.field_name(line))[0]
    else:
        name = rp.split_tags(point.get("name") or "")[0]
    return _norm(name) if is_field(name) else ""


def key_of(point: dict) -> str:
    """The comment a point belongs to: its FIELD, folded (the tags and pages it applies to are listed on the comment, they do not split
    it); a point with no field, by its rule book and clause; a coverage line and anything else, the point itself."""
    if is_coverage(point):
        return f"coverage|{point.get('id')}"
    field = fold_field(_field_of(point))
    if field:
        return f"field|{field}"
    book = point.get("rule_book") or (point.get("rule_ref") or {}).get("name")
    if _norm(book) and _norm(point.get("clause")):
        return f"clause|{_book_key(book)}|{_clause_key(point.get('clause'))}"
    return f"point|{point.get('id')}"


#: The guard reasons of an AI "met" that code could not CONFIRM but that say nothing is open or missing: the quote was not found, the
#: readers disagree. Such a line is ticked by the engineer, not a comment. A "met" held because the value is open (deferred), not stated
#: or only a label stays a comment: a missing statement is never shown as nothing to change (CLAUDE.md rule 4).
def tick_only(point: dict) -> bool:
    """An AI line its reader judged met (its reason "met" or "pass_...") whose PAPER quote code verified, held back only because its
    CLAUSE quote was not verified: the engineer ticks it; it is not a comment. Never ticked (each checked on its own, whatever reason
    the guard gave first): a paper quote not verified, the readers disagreeing, words saying the value is not stated, a quote of the
    field's label only, a value left open (R91: these are real questions)."""
    from . import agent_review_verdict as v

    line = _line_of(point)
    reason = str(line.get("reason_code") or "").strip().lower()
    if not (reason == "met" or reason.startswith("pass")):
        return False
    second = line.get("second_opinion")
    if line.get("not_mentioned_hold") or v.quote_is_label_only(line) or v.quote_defers(line.get("paper_quote")):
        return False
    if isinstance(second, dict) and second.get("agree") is False:
        return False
    return v.met_unsafe_why(line) == v.UNVERIFIED_CLAUSE_WHY


def not_a_comment(comment: dict) -> str | None:
    """What a grouped field is called when it carries NO finding (it is then not a comment), else None: a coverage line; every point
    met (`KIND_NOTHING_TO_CHANGE`); every point met or a met code could not confirm (`KIND_MET_NOT_CONFIRMED`); none of it applies or
    was checked (the strongest point's own kind). A field where readers disagree is always a comment."""
    s = comment["strongest"]
    if is_coverage(s):
        return words.KIND_COVERAGE
    if comment["disagree"]:
        return None
    ms = comment.get("_members") or [s]
    if comment["tile"] == "met":
        return words.KIND_NOTHING_TO_CHANGE
    if all(p.get("tile") in ("met", "does_not_apply") or tick_only(p) for p in ms) and any(tick_only(p) for p in ms):
        return words.KIND_MET_NOT_CONFIRMED
    if comment["tile"] == "does_not_apply":
        return s.get("other_kind") or words.KIND_NOT_APPLICABLE
    return None


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


def group(points: list[dict], findings_only: bool = True, near: bool = True) -> list[dict]:
    """The comments of a list of points (raw or public), worst first. Removed points are left out, and so (`findings_only`) is every
    field that carries no finding (`not_a_comment`; `set_aside` lists them). Each comment: number, key, name, member_ids, n_points,
    rank, tile, pill, firm, strongest (the point whose words lead), pages, tags, clauses, disagree."""
    every = _group_all(points, near)
    if not findings_only:
        return every
    out = [c for c in every if not_a_comment(c) is None]
    for number, c in enumerate(out, start=1):
        c["number"] = number
    return out


def set_aside(points: list[dict]) -> list[tuple[dict, str]]:
    """The grouped fields that are NOT comments, each with what it is called (`not_a_comment`), worst first. With `group` they hold
    every point that is not removed: nothing is dropped."""
    return [(c, kind) for c in _group_all(points) if (kind := not_a_comment(c))]


def coverage_note(points: list[dict]) -> str:
    """ONE sentence for every "N rules could not be matched" line among the points (or stored lines): how many rules, of which books
    (a book the caller may not read is not named); "" when there is none."""
    by_book: dict[str, int] = {}
    for p in points:
        line = p if p.get("source") == "group" else _line_of(p)
        if line.get("source") != "group":
            continue
        book = " ".join(str(line.get("standard") or "").split())  # "" when the caller may not read the book: counted, not named
        by_book[book] = by_book.get(book, 0) + int(line.get("group_count") or 0)
    if not by_book:
        return ""
    total = sum(by_book.values())
    each = "; ".join(f"{b}: {n}" for b, n in sorted(by_book.items()) if b)
    if each and "" in by_book:
        each += f"; a rule book not named here: {by_book['']}"
    return (
        f"{total} rules of the rule books this review selected could not be matched to a field of this paper"
        + (f" ({each})" if each else "")
        + ". An engineer checks them; they are not comments."
    )


def field_words(field: str) -> frozenset[str]:
    """The words of a field (folded, split on every character that is not a letter or digit; text in brackets KEPT, R61)."""
    return frozenset(w for w in re.split(r"[^0-9a-z]+", _norm(field)) if w)


NEAR_SAME_ONE_WORD = 8  # a one-word field is near-same to a longer one only when that word is this long ("compressibility", never "gas")


def near_same(a: frozenset[str], b: frozenset[str]) -> bool:
    """The shorter field's words are all in the longer, make at least half of it, and are not one short word: "compressibility" and
    "compressibility factor", "required capacity" and "required relieving capacity"; never "inlet size" and "outlet size", never "gas" and
    "gas (h2 and co2 content)" (R61)."""
    short, long_ = sorted((a, b), key=len)
    if not short or short == long_ or not short <= long_ or 2 * len(short) < len(long_):
        return False
    return len(short) > 1 or len(next(iter(short))) >= NEAR_SAME_ONE_WORD


def _evidence(ms: list[dict]) -> set[tuple]:
    """What the points of a field show: (page, paper quote) and (book key, clause) pairs; two fields sharing one are about one thing."""
    out = set()
    for p in ms:
        q = _norm(p.get("paper_quote") or _line_of(p).get("paper_quote"))
        if q:
            out.add(("paper", p.get("page"), q))
        book, clause = p.get("rule_book") or (p.get("rule_ref") or {}).get("name"), p.get("clause")
        if _norm(book) and _norm(clause):
            out.add(("rule", _book_key(book), _clause_key(clause)))
    return out


def _near_same_roots(order: list[str], members: dict[str, list[dict]]) -> dict[str, str]:
    """Each field key -> the field key it joins: a shorter field joins the ONE longer field it is near-same to (two or more candidates:
    it stays alone, never guessed); followed to the end, so every field lands on one comment."""
    wds = {k: field_words(_field_of(members[k][0])) for k in order if k.startswith("field|")}
    parent = {}
    for k, w in wds.items():
        longer = [k2 for k2, w2 in wds.items() if k2 != k and len(w2) > len(w) and near_same(w, w2)]
        if len(w) == 1 or len(longer) > 1:  # a one-word name, or two candidates: only one that shares a paper line or book and clause
            longer = [k2 for k2 in longer if _evidence(members[k]) & _evidence(members[k2])]
        if len(longer) == 1:
            parent[k] = longer[0]
    # R91: a longer name that two DIFFERENT fields are near-same to is the paper's combined label ("design/operating pressure",
    # "back press. constant/variable"): two values, so nothing joins it
    hits: dict[str, int] = {}
    for target in parent.values():
        hits[target] = hits.get(target, 0) + 1
    parent = {k: t for k, t in parent.items() if hits[t] == 1}

    def root_of(k: str) -> str:
        r, seen = k, set()
        while r in parent and r not in seen:
            seen.add(r)
            r = parent[r]
        return r

    return {k: root_of(k) for k in order}


def _group_all(points: list[dict], near: bool = True) -> list[dict]:
    """Every grouped field (comments and the fields that carry no finding), numbered in order. Near-same fields are one comment."""
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
    root = _near_same_roots(order, members) if near else {k: k for k in order}
    for k in order:
        if root[k] != k:
            members[root[k]].extend(members.pop(k))
    order = [k for k in order if k in members]
    out = []
    for number, k in enumerate(order, start=1):
        ms = members[k]
        strongest = min(
            ms, key=lambda p: (p["rank"], tick_only(p))
        )  # rank 1 is the worst: the strongest status; a met code could not confirm never leads a field that has a real question
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
                "_members": ms,
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
    return {k: v for k, v in comment.items() if k not in ("strongest", "_members")}


# ------------------------------------------------------------------------------------------------ the AI run's own file (order 14 lane B)


def _line_point(pos: int, line: dict, status: str, order: int) -> dict:
    """An item line of the AI run's file in the shape `group` reads."""
    from . import agent_review_crs as arc
    from . import crs_ai_workbook as wb

    rank = rp.rank_of_ai_line(dict(line))[0]
    return {
        "id": pos, "name": wb.field_name(line) or arc.against(line), "rule_book": _norm_keep(line.get("standard")),
        "clause": _norm_keep(line.get("clause")), "page": arc.line_page(line), "rank": rank, "tile": rp.TILE_OF_RANK[rank],
        "priority": words.priority_ai(status, line, order), "tags": [], "_line": line, "_status": (status, order),
    }  # fmt: skip


def _norm_keep(text) -> str | None:
    return " ".join(str(text or "").split()) or None


def group_lines(items: list) -> tuple[list, dict[int, str]]:
    """The AI run file's comment rows from its item lines `(line, status, order)`, with THE grouping of every CRS file (`group`): each
    row is its strongest line carrying `_comment` (its other lines, whether they disagree); and what every other line is called
    ("Part of comment n", or why it is not a comment), keyed by the line's id()."""
    points = [_line_point(pos, ln, st, o) for pos, (ln, st, o) in enumerate(items)]
    rows, kind_of = [], {}
    for c in group(points):
        by = {p["id"]: p for p in points if p["id"] in c["member_ids"]}
        lead = c["strongest"]
        others = [by[i]["_line"] for i in c["member_ids"] if i != lead["id"]]
        rows.append(({**lead["_line"], "_comment": {"others": others, "disagree": c["disagree"]}}, *lead["_status"]))
        kind_of.update({id(m): words.KIND_IN_COMMENT.format(n=len(rows)) for m in others})
    for c, kind in set_aside(points):
        kind_of.update({id(p["_line"]): kind for p in points if p["id"] in c["member_ids"]})
    return rows, kind_of


def _status_words(line: dict) -> str:
    """A line's own status in plain words (R91: a merged line says its status, never only "also checked")."""
    from . import crs_ai_workbook as wb

    got = wb.status_of(line)
    if got is None:
        return "not a comment"
    st, order = got
    met = order in (words.ORDER_PASS, words.ORDER_AI_MET, words.ORDER_AI_VERDICT_MET)
    return {
        words.STATUS_FAIL: "not met (proven by code)",
        words.STATUS_PASS: "met (proven by code)",
        words.STATUS_AI_VERDICT: f"{'met' if met else 'not met'} (two AI readers agree, engineer to confirm)",
        words.STATUS_AI: f"{'met' if met else 'not met'} in the AI reviewer's view, not proven by code",
    }.get(st, "a question for the engineer")


def also_words(line: dict) -> list[str]:
    """The comment's OTHER lines (order 14 lane B; R91): each with its own status, rule book, clause, page and what it asks, one part
    per line, so a second finding on the field is never folded away; and whether the lines disagree."""
    from . import crs_ai_workbook as wb
    from .agent_review_crs import against, line_page

    c = line.get("_comment") or {}
    out = []
    if c.get("disagree"):
        out.append(f"Note: the lines on this field disagree (met and not met, {len(c['others']) + 1} lines); the engineer decides.")
    for m in c.get("others") or []:
        got = wb.status_of(m)
        ask = wb._contractor_to(m, *got) if got else ""
        where = (against(m) or "the rule") + (f" (page {pg})" if (pg := line_page(m)) else "")
        out.append(f"Also on this field, {_status_words(m)} under {where}" + (f": {ask}" if ask else "."))
    return out
