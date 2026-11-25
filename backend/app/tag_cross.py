"""THE CROSS-DOCUMENT CHECK BY EQUIPMENT TAG (planner 25 Nov 2026 19:15, item 2; order 14 builder C). Code only: no model, no
network, no write.

THE TAG INDEX (`index`). A paper NAMES a tag when its own tag line says so ("Tag No.: 99-P-901 A/B", read by the app's one tag
reader, `classification._tag_hits`), when one of its field readings carries the tag (`submittal_facts.equipment_tag`), or when
a tag some held paper names that way stands in its page text as a whole token. Each
tag maps to the papers that name it, with the page and the line. Company standards are not read (they name no plant item).

THE VALUES (`values`). What a paper STATES for a tag is its stored field readings (`submittal_facts`, current rows: the
reading's own tag, else the paper's tag when its tag lines name exactly one), and, for a paper whose tag lines name ONE tag or
one group of identical items on one line (`_one_group`), each line of its text that is a label, a number and a unit the app's unit table knows (`text_readings`). A reading counts
only when its line is found by code on its page (a verified quote) and it is not left open (blank, TBA, By Vendor ...).

THE CHECK (`lines`). For the paper under review: each field it states for a tag that another readable held paper states for
the same tag. Numbers are compared by code after the app's unit conversion (`claims.normalise`; gauge against absolute is never
compared), within ROUND_OFF; words by their set of words. A difference is a QUESTION naming both papers and pages; never
Pass or Fail; an agreement is no line. Classification is not access control (rule 5): only papers the review's starter may read
are compared; a paper outside that set is counted ("N more papers you may not open"), never named or quoted. Each line names
the other paper in `named_books`, so a viewer who may not open it sees neither its name nor its value (`aim_review_view`).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

ITEM_ID = "X1"
TOPIC = "cross-document check by tag"
SOURCE = "the held papers against each other (by tag)"
#: The code note of a cross-document line (`aim_review_view` hides the comment from a viewer who may not open the other paper).
NOTE = "cross_document"
#: Two readings of one quantity agree within this share (printed rounding: "10 barg" and "145 psig").
ROUND_OFF = 0.005
HIDDEN_COMMENT = (
    "Compared with another held paper that names the same tag, which you may not open."
)
_STANDARD_ROLE = "COMPANY_STANDARD"


@dataclass
class Mention:
    doc_id: str
    page: int
    line: str
    labelled: bool  # its own tag line names the tag


@dataclass
class Reading:
    doc_id: str
    tag: str
    field: str
    value: str
    unit: str
    page: int
    quote: str


@dataclass
class Index:
    tags: dict[str, list[Mention]] = field(default_factory=dict)

    def papers(self, tag: str) -> list[str]:
        return list(dict.fromkeys(m.doc_id for m in self.tags.get(tag, [])))

    def shared(self, least: int = 2) -> dict[str, list[str]]:
        """{tag: paper ids} for every tag that `least` or more papers name."""
        return {t: p for t in self.tags if len(p := self.papers(t)) >= least}


def _pages(conn, doc_ids: list[str]) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    marks = ",".join("?" for _ in doc_ids)
    if not doc_ids:
        return out
    for r in conn.execute(
        f"SELECT document_id, page_no, text FROM pages WHERE document_id IN ({marks})",
        doc_ids,
    ):
        out.setdefault(str(r[0]), {})[int(r[1])] = str(r[2] or "")
    return out


def _papers(conn) -> list[str]:
    """Every held paper that may name a plant item: every document except a company standard."""
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT d.id FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id"
            " WHERE COALESCE(c.document_role, '') != ? ORDER BY d.id",
            (_STANDARD_ROLE,),
        )
    ]


def _line_at(text: str, start: int, end: int) -> str:
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    return " ".join(text[a : b if b >= 0 else len(text)].split())


def index(conn, pages: dict[str, dict[int, str]] | None = None) -> Index:
    """The tag index over the held papers (see the module note). `pages`: {doc id: {page: text}} (read from the database when
    None)."""
    from .classification import _tag_hits

    pages = pages if pages is not None else _pages(conn, _papers(conn))
    idx = Index()
    labelled: dict[str, set[tuple[str, int]]] = {}
    for doc_id, by_page in pages.items():
        for page, text in sorted(by_page.items()):
            for tags, quote in _tag_hits(page, text):
                for tag in tags:
                    if (doc_id, page) not in labelled.setdefault(tag, set()):
                        labelled[tag].add((doc_id, page))
                        idx.tags.setdefault(tag, []).append(
                            Mention(doc_id, page, quote, True)
                        )
    # a field reading's own tag is the paper naming it too (the reading's page and line)
    try:
        rows = conn.execute(
            "SELECT submittal_document_id, equipment_tag, page, source_text FROM submittal_facts"
            " WHERE superseded_at IS NULL AND COALESCE(equipment_tag, '') != ''"
        ).fetchall()
    except (
        sqlite3.OperationalError
    ):  # no readings table (a fresh library): only the tag lines
        rows = []
    for doc_id, tag, page, quote in rows:
        doc_id, tag = str(doc_id), " ".join(str(tag).split())
        if (
            doc_id in pages
            and isinstance(page, int)
            and (doc_id, page) not in labelled.setdefault(tag, set())
        ):
            labelled[tag].add((doc_id, page))
            idx.tags.setdefault(tag, []).append(
                Mention(doc_id, page, " ".join(str(quote or "").split()), True)
            )
    if not labelled:
        return idx
    rx = re.compile(
        r"(?<![A-Za-z0-9-])("
        + "|".join(re.escape(t) for t in sorted(labelled, key=len, reverse=True))
        + r")(?![A-Za-z0-9]|-[A-Za-z0-9])"
    )
    for doc_id, by_page in pages.items():
        for page, text in sorted(by_page.items()):
            for m in rx.finditer(text):
                tag = m.group(1)
                if (doc_id, page) in labelled[tag]:
                    continue
                labelled[tag].add((doc_id, page))
                idx.tags[tag].append(
                    Mention(doc_id, page, _line_at(text, m.start(), m.end()), False)
                )
    return idx


def _own_tags(idx: Index, doc_id: str) -> list[str]:
    return [
        t
        for t, ms in idx.tags.items()
        if any(m.doc_id == doc_id and m.labelled for m in ms)
    ]


def _one_group(idx: Index, pages: dict[int, str]) -> list[str]:
    """The paper's tags when its tag lines name ONE group ("Tag No.: 99-P-901 A/B, 99-P-902 A/B": one sheet for identical items,
    every value applies to each); [] when its tag lines name different groups (a list of items: no value is assigned)."""
    from .classification import _tag_hits

    groups = {
        frozenset(tags)
        for page, text in pages.items()
        for tags, _q in _tag_hits(page, text)
    }
    if len(groups) != 1:
        return []
    return [t for t in next(iter(groups)) if t in idx.tags]


def values(conn, idx: Index, doc_id: str, pages: dict[int, str]) -> list[Reading]:
    """What `doc_id` states for its tags: its current field readings with a verified source line and a stated value."""
    from . import blank_markers
    from .aim_review.verify import quote_in

    own = _own_tags(idx, doc_id)
    out: list[Reading] = []
    try:
        rows = conn.execute(
            "SELECT field_name, field_value, raw_value, raw_unit, unit, page, source_text, equipment_tag, is_blank"
            " FROM submittal_facts WHERE submittal_document_id = ? AND superseded_at IS NULL",
            (doc_id,),
        ).fetchall()
    except (
        sqlite3.OperationalError
    ):  # no readings table (a fresh library): nothing stated
        return out
    for r in rows:
        name, value, raw, raw_unit, unit, page, quote, tag, blank = (
            r[i] for i in range(9)
        )
        tag = str(tag or "").strip() or (own[0] if len(own) == 1 else "")
        value = str(raw if raw not in (None, "") else value or "").strip()
        if not tag or tag not in idx.tags or not name or not value or blank:
            continue
        if blank_markers.classify(value)[0] or blank_markers.value_left_open(value):
            continue  # a value left open (blank, TBA, By Vendor ...) is never compared
        page = int(page) if isinstance(page, int) else None
        if page is None or not quote or not quote_in(str(quote), pages.get(page, "")):
            continue  # a reading whose line code cannot find on its page proves nothing
        out.append(Reading(doc_id, tag, str(name).strip().lower(), value, str(raw_unit or unit or "").strip(), page,
                           " ".join(str(quote).split())))  # fmt: skip
    have = {(r.tag, r.field) for r in out}
    group = _one_group(idx, pages)
    if group:  # a paper about ONE item or one group of identical items: its own lines and printed pairs too
        extra = text_readings(doc_id, "", pages) + pdf_readings(conn, doc_id, pages)
        for tag in group:
            for r in extra:
                if (tag, r.field) not in have:
                    have.add((tag, r.field))
                    out.append(
                        Reading(doc_id, tag, r.field, r.value, r.unit, r.page, r.quote)
                    )
    return _unambiguous(out, extra if group else [])


def _unambiguous(readings: list[Reading], printed: list[Reading]) -> list[Reading]:
    """A label the paper states with two different values (a shell side and a tube side, two operating cases) names no ONE value:
    it is never compared (code cannot tell which of the other paper's values it pairs with)."""
    seen: dict[str, set[tuple[str, str]]] = {}
    for r in [*readings, *printed]:
        seen.setdefault(r.field, set()).add((r.value.casefold(), r.unit.casefold()))
    return [r for r in readings if len(seen.get(r.field, ())) == 1]


_VALUE = re.compile(
    r"^\s*(?P<value>-?\d+(?:[.,]\d+)?)\s*(?P<unit>[^\d\s][^\n]{0,14}?)?\s*$"
)


def _on_page(words: str, text: str) -> bool:
    """`words` stand on the page (case, spaces and typography folded): the quote check for a printed pair, whose two halves
    are two cells of the page, not one line."""
    from .aim_review.verify import norm

    w = re.sub(r"\s", "", norm(words))
    return len(w) >= 2 and w in re.sub(r"\s", "", norm(text))


def _label_line(label: str, text: str) -> str:
    """The page's own line that prints the label (the quote a person can find on the page; the value is a cell beside it)."""
    from .aim_review.verify import norm

    want = re.sub(r"\s", "", norm(label))
    for line in text.splitlines():
        if want and want in re.sub(r"\s", "", norm(line)):
            return " ".join(line.split())
    return ""


def pdf_readings(conn, doc_id: str, pages: dict[int, str]) -> list[Reading]:
    """The label-value pairs the app's datasheet reader prints from the paper's stored PDF (`datasheets._pairs_from_pdf_page`,
    by layout, under pdf_guard; no model). A pair counts when both its label and its value stand on the page's stored text and
    the value is a number with a unit the app's unit table knows. Nothing for a paper with no stored PDF."""
    from . import blank_markers, claims, stored_paths
    from .datasheets import _pairs_from_pdf_page

    row = conn.execute(
        "SELECT stored_path FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    path = stored_paths.local(str(row[0])) if row and row[0] else None
    if not path or not str(path).lower().endswith(".pdf"):
        return []
    out = []
    for page in sorted(pages):
        for label, value in _pairs_from_pdf_page(str(path), page):
            label = " ".join(str(label or "").lower().strip(" :=-").split())
            value = " ".join(str(value or "").split())
            if len(label) < 3 or not re.search(r"[a-z]{3}", label) or not value:
                continue
            if blank_markers.classify(value)[0] or blank_markers.value_left_open(value):
                continue
            if not (_on_page(label, pages[page]) and _on_page(value, pages[page])):
                continue
            m = _VALUE.match(value)
            # a printed pair is paired by LAYOUT, which a shifted cell can pair wrongly: only a number with a unit the app's
            # unit table knows counts ("2 coats", "Group IIB", a label read as a value: never one); words come from readings
            if (
                not m
                or not m.group("unit")
                or not claims.is_unit(m.group("unit").strip())
            ):
                continue
            out.append(Reading(doc_id, "", label, m.group("value").replace(",", "."), m.group("unit").strip(), page,
                               _label_line(label, pages[page])))  # fmt: skip
    return out


#: One line of a paper's text that states a value: its label, then a number and a unit the app's unit table knows ("Design
#: pressure 10 barg", "DESIGN TEMPERATURE: 120 °C"). The paper's own words; the unit decides, never a word list of labels.
_LINE_VALUE = re.compile(
    r"^[ \t]*(?P<label>[A-Za-z][A-Za-z .()/&-]{2,60}?)[ \t]*[:=]?[ \t]+(?P<value>-?\d+(?:[.,]\d+)?)[ \t]*"
    r"(?P<unit>[A-Za-z°%µ][A-Za-z0-9°%µ/.²³]{0,10}(?:[ \t][a-z]{1,2})?)[ \t]*$",
    re.M,
)


def text_readings(doc_id: str, tag: str, pages: dict[int, str]) -> list[Reading]:
    """What a paper's own text states for the ONE tag its tag lines name: each line that is a label, a number and a known unit
    (`_LINE_VALUE`, `claims.is_unit`). The line itself is the quote, on its page."""
    from . import claims

    out = []
    for page, text in sorted(pages.items()):
        for m in _LINE_VALUE.finditer(text):
            unit = m.group("unit").strip()
            if not claims.is_unit(unit):
                continue
            label = " ".join(m.group("label").lower().strip(" :=-").split())
            if len(label) < 3 or not re.search(r"[a-z]{3}", label):
                continue
            out.append(
                Reading(
                    doc_id,
                    tag,
                    label,
                    m.group("value").replace(",", "."),
                    unit,
                    page,
                    " ".join(m.group(0).split()),
                )
            )
    return out


def _words(value: str) -> frozenset[str]:
    return frozenset(w.casefold() for w in re.findall(r"[A-Za-z0-9.]+", value))


def compare(a: Reading, b: Reading) -> str:
    """'agree' | 'differ' | 'cannot', by code: numbers after the app's unit conversion (within ROUND_OFF), words by their set."""
    from . import claims, numparse

    va, vb = numparse.parse_value(a.value), numparse.parse_value(b.value)
    if va is not None and vb is not None:
        if bool(a.unit) != bool(b.unit):
            return "cannot"
        if not a.unit:
            ma, mb = va, vb
        else:
            na, nb = (
                claims.normalise(a.value, a.unit),
                claims.normalise(b.value, b.unit),
            )
            if (
                na.normalized_value is None
                or nb.normalized_value is None
                or na.normalized_unit != nb.normalized_unit
                or (na.reference or "") != (nb.reference or "")
            ):
                return "cannot"
            ma, mb = na.normalized_value, nb.normalized_value
        return (
            "agree"
            if abs(ma - mb) <= ROUND_OFF * max(abs(ma), abs(mb), 1e-12)
            else "differ"
        )
    if (va is None) != (vb is None):
        return "cannot"
    return "agree" if _words(a.value) == _words(b.value) else "differ"


def _title(conn, doc_id: str) -> str:
    row = conn.execute(
        "SELECT COALESCE(NULLIF(c.document_number, ''), NULLIF(c.title, ''), d.filename) FROM documents d"
        " LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?",
        (doc_id,),
    ).fetchone()
    return str(row[0] or doc_id) if row else doc_id


def check(conn, paper_id: str, readable: frozenset[str]) -> dict:
    """{"differ": [(mine, other)], "agree": [(mine, other)], "hidden": {tag: count of papers outside `readable`}} for the paper."""
    pages = _pages(conn, _papers(conn))
    idx = index(conn, pages)
    mine = values(conn, idx, paper_id, pages.get(paper_id, {}))
    out: dict = {"differ": [], "agree": [], "hidden": {}}
    done: set[tuple[str, str]] = (
        set()
    )  # (other paper, field): one comparison, however many tags the two papers share
    cache: dict[str, list[Reading]] = {}
    for tag in dict.fromkeys(r.tag for r in mine):
        others = [d for d in idx.papers(tag) if d != paper_id]
        out["hidden"][tag] = sum(1 for d in others if d not in readable)
        for other in (d for d in others if d in readable):
            if other not in cache:
                cache[other] = values(conn, idx, other, pages.get(other, {}))
            theirs = {r.field: r for r in cache[other] if r.tag == tag}
            for r in mine:
                if r.tag == tag and r.field in theirs and (other, r.field) not in done:
                    done.add((other, r.field))
                    verdict = compare(r, theirs[r.field])
                    if verdict in ("agree", "differ"):
                        out[verdict].append((r, theirs[r.field]))
    return out


def lines(conn, paper_id: str, readable: frozenset[str], start: int = 0) -> list[dict]:
    """The check's Question lines for the paper, as stored line rows (`engine.to_line` columns), numbered from `start` + 1."""
    found = check(conn, paper_id, frozenset(readable))
    out = []
    for n, (a, b) in enumerate(found["differ"], 1):
        name = _title(conn, b.doc_id)
        hidden = found["hidden"].get(a.tag) or 0
        more = (
            f" {hidden} more held paper{'s' if hidden != 1 else ''} name this tag that you may not open; not compared."
            if hidden
            else ""
        )
        comment = (
            f"For {a.tag}, this paper states {a.field} {a.value} {a.unit} (page {a.page}), but {name} states "
            f"{b.value} {b.unit} (page {b.page}); please confirm which value is right.{more}"
        )
        out.append(
            {
                "line_no": start + n,
                "item_id": ITEM_ID,
                "finding_no": n,
                "label": "Question",
                "field": a.field,
                "page": a.page,
                "quote": a.quote,
                "quote_unverified": "",
                "comment": " ".join(comment.split()),
                "standard": "",
                "book_document_id": "",
                "clause": "",
                "source": SOURCE,
                "topic": TOPIC,
                "code_note": f"{NOTE}: {a.tag}",
                "numbers_json": None,
                "named_books_json": json.dumps(
                    [{"id": b.doc_id, "name": name}], ensure_ascii=False
                ),
                "code_compare_json": json.dumps(
                    {
                        "read_from": "verified quotes",
                        "result": "differs",
                        "other_page": b.page,
                    },
                    ensure_ascii=False,
                ),
                "deferred": False,
                "ask": "concern",
            }
        )
    return out
