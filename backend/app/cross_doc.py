"""THE CROSS-DOCUMENT CHECK, LANE 1: EXACT FACTS BY CODE (order 14, planner 25 Nov 2026 23:35 (b) item 1; builder H). Code only: no
model, no network, no write. OFF by default (CROSS_DOC_FACTS_ENABLED); OFF, a review keeps builder C's check by tag (`tag_cross`)
exactly as it is.

WHAT IT COMPARES, between the paper under review and the other papers of its package that the review's starter may read:
1. THE SAME EQUIPMENT TAG is the join: a value is compared only with a value another paper states for the same tag (C's tag
   index, `tag_cross.index`, and C's readings, `tag_cross.values`).
2. VALUE PLUS UNIT, after the app's unit conversion (`tag_cross.compare` -> `claims.normalise`, gauge against absolute never
   compared). Only NUMBERS: a value in words is a meaning, and a meaning is lane 2's (`cross_doc_meaning`), never a code finding.
3. THE STANDARD NAME PLUS EDITION: a standard both papers cite (one identifier, `standard_ids`, the literal key: NACE MR0175 and
   ISO 15156 are two names) with a stated edition of the same sort (two years, or two "Nth edition"s) that differ. A paper that
   cites one standard with two editions names no one edition: never compared. "Latest edition" states none.

THE PACKAGE (`package`): the papers tied to the paper by a RECORDED link, never a likeness of names: the same recorded project
(`references.project_of`), or naming on their own tag line a tag the paper names on its own tag line (the same plant item). Company
standards are never in it. Classification is not access control (rule 5): a tied paper the starter may not read is counted, never
named or quoted.

A MISMATCH IS A FINDING with BOTH quotes, each found by code on its own page (`verify.quote_in`); a pair whose quote code cannot
find on its page is not raised. It is a Question that asks the contractor to correct the papers (code proves the two papers differ,
not which one is right): never Pass or Fail. Each line names the other paper in `named_books`, so a viewer who may not open it sees
neither its name nor its words (`aim_review_view`, the `tag_cross.NOTE` prefix).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import tag_cross

ITEM_ID = "X2"
TOPIC = "cross-document check: exact facts"
SOURCE = "the papers of one package against each other (by code)"
#: Every lane's code note starts with C's note, so the view's rule-5 hiding covers it (`aim_review_view`).
NOTE_FACT = f"{tag_cross.NOTE}: fact"
NOTE_EDITION = f"{tag_cross.NOTE}: edition"
_STANDARD_ROLE = "COMPANY_STANDARD"


def lane_on() -> bool:
    from .config import settings

    return bool(getattr(settings, "cross_doc_facts_enabled", False))


# ------------------------------------------------------------------ the package


def _tag_papers(idx: tag_cross.Index, doc_id: str) -> set[str]:
    """The papers naming, on their own tag line, a tag `doc_id` names on its own tag line."""
    out: set[str] = set()
    for _tag, ms in idx.tags.items():
        if any(m.doc_id == doc_id and m.labelled for m in ms):
            out |= {m.doc_id for m in ms if m.labelled}
    return out - {doc_id}


def package(
    conn, paper_id: str, readable: frozenset[str], idx: tag_cross.Index | None = None
) -> tuple[list[str], int]:
    """(the tied papers the starter may read, how many tied papers the starter may not read). See the module note."""
    from .aim_review.references import project_of

    held = set(tag_cross._papers(conn))
    idx = idx if idx is not None else tag_cross.index(conn)
    tied = _tag_papers(idx, paper_id)
    mine = project_of(conn, paper_id)
    if mine is not None:
        tied |= {d for d in held if d != paper_id and project_of(conn, d) == mine}
    tied &= held
    tied.discard(paper_id)
    return sorted(d for d in tied if d in readable), sum(
        1 for d in tied if d not in readable
    )


# ------------------------------------------------------------------ the pairs (shared with lane 2)


@dataclass
class Pair:
    verdict: str  # "differ" | "agree" | "cannot" (`tag_cross.compare`)
    numeric: bool  # both values are numbers
    mine: tag_cross.Reading
    theirs: tag_cross.Reading


def _numeric(r: tag_cross.Reading) -> bool:
    from . import numparse

    return numparse.parse_value(r.value) is not None


def pairs(
    conn, paper_id: str, readable: frozenset[str]
) -> tuple[list[Pair], dict[str, int], dict]:
    """(every pair of one field for one tag between the paper and a readable paper naming the tag, {tag: papers not readable},
    the pages read). One pair per (other paper, field), however many tags the two papers share (as `tag_cross.check`)."""
    pages = tag_cross._pages(conn, tag_cross._papers(conn))
    idx = tag_cross.index(conn, pages)
    mine = tag_cross.values(conn, idx, paper_id, pages.get(paper_id, {}))
    out: list[Pair] = []
    hidden: dict[str, int] = {}
    done: set[tuple[str, str]] = set()
    cache: dict[str, list[tag_cross.Reading]] = {}
    for tag in dict.fromkeys(r.tag for r in mine):
        others = [d for d in idx.papers(tag) if d != paper_id]
        hidden[tag] = sum(1 for d in others if d not in readable)
        for other in (d for d in others if d in readable):
            if other not in cache:
                cache[other] = tag_cross.values(conn, idx, other, pages.get(other, {}))
            theirs = {r.field: r for r in cache[other] if r.tag == tag}
            for r in mine:
                if r.tag != tag or r.field not in theirs or (other, r.field) in done:
                    continue
                done.add((other, r.field))
                b = theirs[r.field]
                out.append(
                    Pair(tag_cross.compare(r, b), _numeric(r) and _numeric(b), r, b)
                )
    return out, hidden, pages


def proven(quote: str, page: int | None, pages: dict[int, str]) -> bool:
    """The quote stands on its page, found by code."""
    from .aim_review.verify import quote_in

    return (
        isinstance(page, int) and bool(quote) and quote_in(quote, pages.get(page, ""))
    )


# ------------------------------------------------------------------ the editions


@dataclass(frozen=True)
class Cited:
    doc_id: str
    key: str  # the standard's literal key ("API 610")
    name: str  # as printed
    sort: str  # "year" | "edition"
    edition: str  # "2010" | "11"
    page: int
    quote: str  # the page's line that prints it


#: An edition printed right after a cited identifier, on its line: "-2010", ":2009", ", 2010", "(2010)", "2019 edition",
#: "11th Edition", "11th Ed.", "Edition 11", "Ed. 11". A bare year after a space counts only when the line ends there or an edition
#: word or a closing mark follows (so "API 610 2010 kW" is not an edition); a year joined by "-" or ":" always counts.
_ED_ATTACHED = re.compile(r"^[-:\u2013/]\s?(?P<y>(?:19[5-9]|20[0-4])\d)(?!\d)")
_ED_YEAR = re.compile(
    r"^\s*(?:,\s*|\(\s*)?(?P<y>(?:19[5-9]|20[0-4])\d)(?![\d.,])"
    r"(?=\s*(?:$|[)\].,;]|\s*(?:edition|ed\b|ed\.|issue)))",
    re.IGNORECASE,
)
_ED_ORD = re.compile(
    r"^\s*,?\s*\(?\s*(?:(?P<o>\d{1,2})(?:st|nd|rd|th)\s+ed(?:ition|\.|\b)|ed(?:ition|\.)\s*(?P<o2>\d{1,2})\b)",
    re.IGNORECASE,
)
#: The identifier itself may end with its year ("ASME B31.3-2020", "ISO 13709:2009").
_SPELLED_YEAR = re.compile(r"[-:]\s*((?:19[5-9]|20[0-4])\d)$")


def _edition_after(spelling: str, tail: str) -> tuple[str, str] | None:
    if m := _SPELLED_YEAR.search(spelling.strip()):
        return "year", m.group(1)
    tail = tail.split("\n", 1)[0][:40]
    if m := _ED_ATTACHED.match(tail) or _ED_YEAR.match(tail):
        return "year", m.group("y")
    if m := _ED_ORD.match(tail):
        return "edition", str(int(m.group("o") or m.group("o2")))
    return None


def citations(doc_id: str, pages: dict[int, str]) -> list[Cited]:
    """Every standard the paper cites WITH a stated edition, by code (`standard_ids.find_citations`, `parse`)."""
    from . import standard_ids

    out: list[Cited] = []
    for page, text in sorted(pages.items()):
        for spelling, start, end in standard_ids.find_citations(text):
            sid = standard_ids.parse(spelling)
            ed = _edition_after(spelling, text[end:]) if sid else None
            if sid is None or ed is None:
                continue
            out.append(
                Cited(
                    doc_id,
                    sid.literal_key(),
                    " ".join(spelling.split()),
                    ed[0],
                    ed[1],
                    page,
                    tag_cross._line_at(text, start, end),
                )
            )
    return out


def _one_edition(cited: list[Cited]) -> dict[tuple[str, str], Cited]:
    """{(standard, sort): its citation} for each standard the paper cites with ONE edition of that sort."""
    seen: dict[tuple[str, str], set[str]] = {}
    first: dict[tuple[str, str], Cited] = {}
    for c in cited:
        seen.setdefault((c.key, c.sort), set()).add(c.edition)
        first.setdefault((c.key, c.sort), c)
    return {k: first[k] for k, eds in seen.items() if len(eds) == 1}


def _ed_words(c: Cited) -> str:
    return c.edition if c.sort == "year" else f"edition {c.edition}"


def edition_pairs(
    paper_id: str, tied: list[str], pages: dict[str, dict[int, str]]
) -> list[tuple[Cited, Cited]]:
    """(mine, theirs) for each standard the paper and a tied paper cite with different editions of the same sort."""
    mine = _one_edition(citations(paper_id, pages.get(paper_id, {})))
    out = []
    for other in tied:
        theirs = _one_edition(citations(other, pages.get(other, {})))
        for k, a in mine.items():
            b = theirs.get(k)
            if b is not None and a.edition != b.edition:
                out.append((a, b))
    return out


# ------------------------------------------------------------------ the lines


def _line(
    n: int,
    start: int,
    *,
    field: str,
    page: int,
    quote: str,
    comment: str,
    note: str,
    other: str,
    name: str,
    compare: dict,
) -> dict:
    return {
        "line_no": start + n,
        "item_id": ITEM_ID,
        "finding_no": n,
        "label": "Question",
        "field": field,
        "page": page,
        "quote": quote,
        "quote_unverified": "",
        "comment": " ".join(comment.split()),
        "standard": "",
        "book_document_id": "",
        "clause": "",
        "source": SOURCE,
        "topic": TOPIC,
        "code_note": note,
        "numbers_json": None,
        "named_books_json": json.dumps(
            [{"id": other, "name": name}], ensure_ascii=False
        ),
        "code_compare_json": json.dumps(compare, ensure_ascii=False),
        "deferred": False,
        "ask": "concern",
    }


def _more(hidden: int) -> str:
    return (
        f" {hidden} more paper{'s' if hidden != 1 else ''} of this package you may not open; not compared."
        if hidden
        else ""
    )


def lines(conn, paper_id: str, readable: frozenset[str], start: int = 0) -> list[dict]:
    """Lane 1's Question lines for the paper (`engine.to_line` columns), numbered from `start` + 1."""
    readable = frozenset(readable)
    found, hidden_by_tag, pages = pairs(conn, paper_id, readable)
    idx = tag_cross.index(conn, pages)
    tied, hidden = package(conn, paper_id, readable, idx)
    out: list[dict] = []
    for p in found:
        a, b = p.mine, p.theirs
        if p.verdict != "differ" or not p.numeric:
            continue
        if not (
            proven(a.quote, a.page, pages.get(a.doc_id, {}))
            and proven(b.quote, b.page, pages.get(b.doc_id, {}))
        ):
            continue  # both quotes stand on their pages, found by code, or nothing is raised
        name = tag_cross._title(conn, b.doc_id)
        comment = (
            f'For {a.tag}, this paper states {a.field} {a.value} {a.unit} (page {a.page}: "{a.quote}"), but {name} states '
            f'{b.value} {b.unit} (page {b.page}: "{b.quote}"). The two papers give different values for the same item: please '
            f"correct the one that is wrong, or state why they differ.{_more(hidden_by_tag.get(a.tag) or 0)}"
        )
        out.append(
            _line(
                len(out) + 1,
                start,
                field=a.field,
                page=a.page,
                quote=a.quote,
                comment=comment,
                note=f"{NOTE_FACT} {a.tag}",
                other=b.doc_id,
                name=name,
                compare={
                    "read_from": "verified quotes",
                    "result": "differs",
                    "other_page": b.page,
                    "other_quote": b.quote,
                    "unit_converted": bool(a.unit and b.unit and a.unit != b.unit),
                },
            )
        )
    for a, b in edition_pairs(paper_id, tied, pages):
        if not (
            proven(a.quote, a.page, pages.get(a.doc_id, {}))
            and proven(b.quote, b.page, pages.get(b.doc_id, {}))
        ):
            continue
        name = tag_cross._title(conn, b.doc_id)
        comment = (
            f'This paper cites {a.key} {_ed_words(a)} (page {a.page}: "{a.quote}"), but {name}, a paper of the same package, '
            f'cites {b.key} {_ed_words(b)} (page {b.page}: "{b.quote}"). Please state which edition applies and correct the '
            f"other paper.{_more(hidden)}"
        )
        out.append(
            _line(
                len(out) + 1,
                start,
                field=f"edition of {a.key}",
                page=a.page,
                quote=a.quote,
                comment=comment,
                note=f"{NOTE_EDITION} {a.key}",
                other=b.doc_id,
                name=name,
                compare={
                    "read_from": "verified quotes",
                    "result": "differs",
                    "other_page": b.page,
                    "other_quote": b.quote,
                },
            )
        )
    return out
