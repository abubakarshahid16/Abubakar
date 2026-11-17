"""A paper's own parts and its contract package (order 14 LPC, 17 Nov 2026): what a name the review calls a "missing book" really is.

A contract arrives as a PACKAGE: the agreement and its schedules, appendices, annexes, exhibits and attachments, each a held paper
of its own. Today's general review of a contract had no project paper to check against, so the paper's own article titles and its
references to the schedules of its package became "missing books". This module is the ONE home of three general decisions:

  * `cover_id(pages)`: the labelled number ("Contract No.", "Document No.", "Doc. No.", "Agreement No.", "Purchase Order No.",
    "Drawing No.") and the revision ("Rev 3", "Revision B") printed on the paper's COVER (the top lines of its first two pages);
    None when code does not find them there. Never guessed.
  * `package_papers(conn, paper, allowed)`: the other papers of the SAME package: held papers whose cover prints the SAME labelled
    number and whose role or decided kind is contract, inside the caller's scope (CLAUDE.md rule 5: a filter only narrows). A paper
    with no cover number has no package. `referred_package_papers` keeps those the paper names by their label (Schedule C, Annex 2):
    the project papers a contract's review is given automatically (`review_engine.plan_for`).
  * `resolve_name(name, paper, ...)`: what a cited name is: the paper's OWN part (a heading of the paper holds the name, or the paper
    places the name in one of its own articles), a part of the package that is HELD (resolved to that paper), a labelled part that
    is NOT held (the only "not held" line, named by its label), or a real book (left to the library check). `not_held_name` is the
    name the review lists as not held: "" for an own part or a held part.

General rules only (CLAUDE.md rule 13): label words, numbering and heading shape; nothing of one paper's layout or words. A name
that carries a standard identifier (`standard_ids.find_citations`) is always a book, never a part of the paper. Reads only.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from . import contract_checks as parts

Pages = list[tuple[int, str]]

COVER_PAGES = 2  # the cover and the title page
COVER_LINES = 12  # the top lines of each cover page that are read
#: A labelled number: the label words, then a token of letters, digits and joiners that holds at least one digit.
_NUMBER = re.compile(
    r"\b(?P<label>(?:contract|document|doc|agreement|purchase\s+order|drawing|dwg)\.?\s*(?:no\b\.?|number\b|nr\b\.?|#))\s*[:.]?\s*"
    r"(?P<number>(?=[A-Z0-9./_-]*\d)[A-Z0-9][A-Z0-9./_-]{2,40})(?![A-Za-z0-9])",
    re.I,
)
_REVISION = re.compile(
    r"\b(?:rev|revision)\b\.?\s*(?:no\b\.?)?\s*[:.]?\s*(?P<rev>[A-Z]?\d{1,3}[A-Z]?|[A-Z])(?![A-Za-z0-9])",
    re.I,
)
HEADING_WORDS = 12  # a heading is a short line
_LEAD_NUMBER = re.compile(
    r"^\s*(?:(?:sub-?)?(?:article|clause|section|part)\s+)?(?:\d+(?:\.\d+)*|[IVXL]{1,6})\s*[.):-]?\s*",
    re.I,
)
_NUMBER_ONLY = re.compile(
    r"^\s*(?:(?:sub-?)?(?:article|clause|section)\s+)?\d+(?:\.\d+)*\s*[.):-]?\s*$", re.I
)
#: The paper places a name in one of its OWN articles: "... listed in Sub-Article 1.1 of this Agreement", "... set out in Clause 4
#: hereof". "referred to in" is not a place: an article that mentions a book does not hold it.
_SELF_PLACE = re.compile(
    r"^\W{0,3}(?:as\s+)?(?:listed|set\s+out|set\s+forth|defined|described|stated|specified|contained|given)\s+(?:in|under)\s+"
    r"(?:sub-?)?(?:article|clause|section|paragraph)\s+\d+(?:\.\d+)*[a-z]?"
    r"\s*(?:of\s+this\b|hereof\b|herein\b|above\b|below\b)",
    re.I,
)
SELF_NEAR = 80  # characters after the name in which the paper's own article is read

OWN, HELD, NOT_HELD, BOOK = "own part", "held in the package", "not held", "book"


@dataclass(frozen=True)
class CoverId:
    number: str | None = None
    number_label: str | None = None
    number_page: int | None = None
    revision: str | None = None
    revision_page: int | None = None


@dataclass(frozen=True)
class Resolution:
    """What a cited name is. `name` is what a not-held line prints (the label of a part not held); `document_id` and `page`
    say where a held part or an own part is."""

    kind: str
    name: str
    document_id: str | None = None
    page: int | None = None


def _fold(text: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(text or "").lower()).split())


def cover_lines(pages: Pages) -> list[tuple[int, str]]:
    """The top `COVER_LINES` non-empty lines of the paper's first `COVER_PAGES` pages."""
    out: list[tuple[int, str]] = []
    for page, text in sorted(pages)[:COVER_PAGES]:
        lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
        out += [(page, ln) for ln in lines[:COVER_LINES]]
    return out


def cover_id(pages: Pages) -> CoverId:
    """The labelled number and the revision the cover prints (the first found of each), else None for each. Never guessed."""
    number = label = n_page = rev = r_page = None
    for page, line in cover_lines(pages):
        if number is None and (m := _NUMBER.search(line)):
            number, label, n_page = (
                m.group("number").rstrip("./-_"),
                " ".join(m.group("label").split()),
                page,
            )
        if rev is None and (r := _REVISION.search(line)):
            rev, r_page = r.group("rev"), page
    return CoverId(number, label, n_page, rev, r_page)


def package_key(number: str | None) -> str:
    """The number as the package is matched on: letters and digits only, upper case."""
    return re.sub(r"[^A-Z0-9]", "", str(number or "").upper())


def load_pages(
    conn: sqlite3.Connection, document_id: str, last_page: int | None = None
) -> Pages:
    sql = (
        "SELECT page_no, text FROM pages WHERE document_id = ?"
        + (" AND page_no <= ?" if last_page else "")
        + " ORDER BY page_no"
    )
    args = (document_id, last_page) if last_page else (document_id,)
    return [(int(p), t or "") for p, t in conn.execute(sql, args).fetchall()]


def _contract_ids(conn: sqlite3.Connection) -> set[str]:
    """Held papers whose role or decided kind is contract."""
    ids = {
        r[0]
        for r in conn.execute(
            "SELECT document_id FROM document_classification WHERE document_role = 'CONTRACT_DOCUMENT'"
        )
    }
    # an older database without the kind table: the role alone
    with contextlib.suppress(sqlite3.OperationalError):
        ids |= {
            r[0]
            for r in conn.execute(
                "SELECT document_id FROM document_kinds WHERE kind = 'contract'"
            )
        }
    return ids


def package_papers(
    conn: sqlite3.Connection, paper: str, allowed: Iterable[str]
) -> list[dict]:
    """[{document_id, name, parts}] of the OTHER papers of the paper's package that the caller may read, in file-name order: the
    same labelled cover number, role or kind contract. [] when the paper's cover prints no number. `parts` is what each paper is
    (`contract_checks.package_part`: its labels on its first heading lines)."""
    key = package_key(cover_id(load_pages(conn, paper, COVER_PAGES)).number)
    if not key:
        return []
    allowed = frozenset(allowed)
    out = []
    for d in sorted(_contract_ids(conn) & allowed - {paper}):
        pages = load_pages(conn, d, COVER_PAGES)
        if package_key(cover_id(pages).number) != key:
            continue
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (d,)
        ).fetchone()
        if row is None:
            continue
        out.append(
            {"document_id": d, "name": row[0] or d, "parts": parts.package_part(pages)}
        )
    return sorted(out, key=lambda p: (str(p["name"]).lower(), p["document_id"]))


def _held_part(key: tuple[str, str], package: list[dict]) -> dict | None:
    """The held paper that IS the labelled part `key` itself (not one of its attachments)."""
    return next(
        (
            p
            for p in package
            if any(k == key and parent is None for k, parent in p["parts"])
        ),
        None,
    )


def referred_package_papers(
    conn: sqlite3.Connection, paper: str, allowed: Iterable[str], limit: int
) -> tuple[list[str], int]:
    """(the package papers the paper names by their label, at most `limit`, in the order the paper first names them; how many more
    were named and held but left out by the limit). These are the project papers a contract's review is given automatically."""
    package = package_papers(conn, paper, allowed)
    if not package:
        return [], 0
    named: list[str] = []
    for _page, line in parts.lines_of(load_pages(conn, paper)):
        for word, label, _at in parts.labels(line):
            hit = _held_part((word, label.upper()), package)
            if hit is not None and hit["document_id"] not in named:
                named.append(hit["document_id"])
    return named[:limit], max(0, len(named) - limit)


def _is_heading(line: str, before: str) -> bool:
    """A short line that is a heading: all its letters upper case, or it starts with an article number, or the line before it is
    an article number alone ("3." then the title)."""
    words = line.split()
    if not words or len(words) > HEADING_WORDS or re.search(r"[.;:]\s+\S", line):
        return False
    letters = re.sub(r"[^A-Za-z]", "", line)
    return bool(letters) and (
        letters.isupper()
        or bool(_NUMBER_ONLY.match(before))
        or bool(re.match(r"^\s*\d+(?:\.\d+)*\.?\s+[A-Z]", line))
    )


def own_heading_page(name: str, pages: Pages) -> int | None:
    """The page of the paper's own heading that holds the name as a whole phrase, else None."""
    want = _fold(name)
    if len(want) < 4:
        return None
    lines = parts.lines_of(pages)
    for i, (page, line) in enumerate(lines):
        before = lines[i - 1][1] if i else ""
        if (
            _is_heading(line, before)
            and f" {want} " in f" {_fold(_LEAD_NUMBER.sub('', line))} "
        ):
            return page
    return None


def self_placed_page(name: str, pages: Pages) -> int | None:
    """The page on which the paper places the name in one of its own articles ("... listed in Sub-Article 1.1 of this ..."), else None."""
    words = [re.escape(w) for w in _fold(name).split()]
    if not words or len("".join(words)) < 4:
        return None
    rx = re.compile(r"\b" + r"\W+".join(words) + r"\b", re.I)
    for page, text in pages:
        flat = " ".join(str(text or "").split())
        for m in rx.finditer(flat):
            if _SELF_PLACE.match(flat[m.end() : m.end() + SELF_NEAR]):
                return page
    return None


def _labelled_title(name: str, pages: Pages) -> tuple[str, str] | None:
    """The label of the part whose title the paper prints as the name: a line that holds a label and the name, or a label line just
    above the name's line ('SCHEDULE "K"' then its title)."""
    want = _fold(name)
    if len(want) < 4:
        return None
    lines = parts.lines_of(pages)
    for i, (page, line) in enumerate(lines):
        if _fold(_LEAD_NUMBER.sub("", re.sub(parts._LABEL, " ", line))) != want:
            continue
        here = parts.labels(line)
        if not here and i and lines[i - 1][0] == page:
            above = lines[i - 1][1]
            only = parts.labels(above)
            here = only if only and not _fold(re.sub(parts._LABEL, " ", above)) else []
        if here:
            return here[0][0], here[0][1].upper()
    return None


def resolve_name(
    name: str,
    pages: Pages,
    package: list[dict] | None = None,
    own_id: str | None = None,
) -> Resolution:
    """What a cited name is (`OWN`, `HELD`, `NOT_HELD` or `BOOK`), read on the paper's pages and its package (`package_papers`).
    Order: a standard identifier is a book; a labelled part the name carries or names by its title is held (that paper) or not
    held (named by its label); a heading of the paper or a place in its own article is the paper's own part; else a book."""
    from .standard_ids import find_citations

    clean = " ".join(str(name or "").split())
    if not clean or find_citations(clean):
        return Resolution(BOOK, clean)
    found = parts.labels(clean)
    key = (found[0][0], found[0][1].upper()) if found else _labelled_title(clean, pages)
    if key is not None:
        if key in [k for k, _p in parts.package_part(pages)]:
            return Resolution(OWN, clean, own_id)  # the paper is that part itself
        held = _held_part(key, package or [])
        if held is not None:
            return Resolution(HELD, clean, held["document_id"])
        return Resolution(NOT_HELD, f"{key[0].capitalize()} {key[1]}")
    page = own_heading_page(clean, pages) or self_placed_page(clean, pages)
    if page is not None:
        return Resolution(OWN, clean, own_id, page)
    return Resolution(BOOK, clean)


def not_held_name(name: str, pages: Pages, package: list[dict] | None = None) -> str:
    """THE name a review lists as not held for a cited name: "" when it is the paper's own part or a held part of its package; the
    label alone for a labelled part that is not held ("Schedule X"); else the name unchanged (a book, left to the library check)."""
    got = resolve_name(name, pages, package)
    return "" if got.kind in (OWN, HELD) else got.name


class PaperParts:
    """The paper's pages and its package, read once per listing (`review_points.book_missing` keeps one in its `ctx`)."""

    def __init__(
        self, conn: sqlite3.Connection, paper: str | None, allowed: Iterable[str] = ()
    ) -> None:
        self.paper = paper
        self.readable = frozenset(allowed)
        self.pages: Pages = []
        self.package: list[dict] = []
        if not paper:
            return
        try:
            self.pages = load_pages(conn, paper)
            # every package paper: whether a part is HELD does not depend on who reads (rule 5 decides only whether its NAME is shown)
            self.package = package_papers(conn, paper, _contract_ids(conn))
        except sqlite3.Error:
            # could not read: nothing is resolved, so every name stays as the library check left it (the older behaviour), never
            # "own part" by default
            self.pages, self.package = [], []

    def resolve(self, name: str) -> Resolution:
        return resolve_name(name, self.pages, self.package, self.paper)

    def not_held_name(self, name: str) -> str:
        got = self.resolve(name)
        return "" if got.kind in (OWN, HELD) else got.name

    def held_name(self, got: Resolution) -> str | None:
        """The held paper's file name, only when the caller may read it (rule 5); else None."""
        if got.kind != HELD or got.document_id not in self.readable:
            return None
        return next(
            (
                str(p["name"])
                for p in self.package
                if p["document_id"] == got.document_id
            ),
            None,
        )


def words_of(got: Resolution, held_name: str | None = None) -> str:
    """What a row says of a name that is not a missing book."""
    if got.kind == OWN:
        where = f", page {got.page}" if got.page else ""
        return f'Not a rule book: "{got.name}" is a part of this paper itself{where}.'
    if got.kind == HELD:
        named = f" ({held_name})" if held_name else ""
        return f'Not a missing book: "{got.name}" is a paper of this contract package that the library holds{named}.'
    return ""


def as_mapping(got: Resolution) -> Mapping:
    return {
        "kind": got.kind,
        "name": got.name,
        "document_id": got.document_id,
        "page": got.page,
    }


PACKAGE_BOUNDARY = "papers of the same contract package that you may read"


def project_ids_for(
    conn: sqlite3.Connection,
    paper: str,
    kind: str | None,
    allowed: Iterable[str],
    chosen: Iterable[str] = (),
) -> tuple[tuple[str, ...], dict]:
    """P1: the project papers of a review: the ones the person chose, then, for a contract under general review, the papers of its
    package that it names by their label (`referred_package_papers`), each passing the general review's own check of a project paper
    (`agent_general_review.check_project_papers`: readable by the caller, not a rule book, not blocked, has page text), up to the
    general review's limit. Returns (all ids, {"given": [ids added], "left_out": n, "boundary": ...}). Reads only."""
    from . import agent_general_review as general
    from . import agent_review_gate

    chosen = tuple(dict.fromkeys(str(c) for c in chosen))
    facts: dict = {"given": [], "left_out": 0, "boundary": PACKAGE_BOUNDARY}
    if str(
        kind or ""
    ).strip().lower() != "contract" or not agent_review_gate.general_kind_enabled(kind):
        return chosen, facts
    allowed = frozenset(allowed)
    named, more = referred_package_papers(
        conn, paper, allowed, general.MAX_PROJECT_PAPERS
    )
    fresh = [d for d in named if d not in chosen and d != paper]
    accepted, _problems = general.check_project_papers(conn, paper, fresh, allowed)
    ok = [a["document_id"] for a in accepted]
    room = max(0, general.MAX_PROJECT_PAPERS - len(chosen))
    facts.update(given=ok[:room], left_out=more + max(0, len(ok) - room))
    return chosen + tuple(facts["given"]), facts
