"""Test B / HAZOP (part of #805), behind SECTION_INDEX_ENABLED: a section index built at review time, in memory, from the
stored chunk and page text. It writes nothing and changes no stored chunk.

THE DEFECT. The stored headings of a Word-derived procedure are the numbered clauses; every attachment (printed as
"<token>-<ATT|APP|ANNEX><nn> - <TITLE>") and table title ("Table A10.1: ...") sits under ONE catch-all heading, so no
element could find its own section there and a row said "no section of its own" about a section that exists. Also a cue
word in the title of an unrelated numbered clause made that clause "the element's own section".

WHAT IT DOES.
  * `refine` re-splits the body passages at headings of any kind: attachment/appendix/annex lines with a code and a
    title, table and figure titles, and, inside an attachment, short numbered item titles ("6. Independent Protection
    Layers"). The heading classes are DATA (`reference/section_index.json`), not tied to a document. Each new passage
    carries its heading as its section and the page of THAT PRINT of the heading: the passage's lines are walked in order
    against the stored page text, so a heading printed twice, or a title repeated on every page (a running header), never
    gives a later passage an earlier page. A heading whose printed line cannot be found on a page is not indexed.
  * What is never a heading: a line with dot leaders or a trailing page number after leaders or tabs (a table of
    contents entry, with or without a "Contents" heading), a run of three or more heading-like lines each ending in a
    page number, and a line repeated on three or more pages, and a line ending in a page number (after plain spaces too).
  * A table or figure caption is never the element's section: at most the closest one.
  * `title_hit`: a title is "about" an element only through a cue that is not a generic title word, and an indexed
    heading is the element's section only when it is also `_about` the element (two content words in common); a coded
    attachment title with a cue alone is the CLOSEST section, never "found".
Nothing here knows a layout or a document (rule 13).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import settings
from .db import connect

DATA = Path(__file__).parent / "reference" / "section_index.json"
_CACHE: dict = {}
#: Lines this short are never counted as running headers (a page number, a bullet).
_MIN_RUNNING = 4
#: How many pages beyond the cursor a heading's printed line is looked for.
_LOOKAHEAD = 4
_LEADERS = re.compile(r"(?:\.{3,}|…|\t)\s*\d{1,4}\s*$|\.{2,}\s*\d{1,4}\s*$")
_ENDS_IN_NUMBER = re.compile(r"\s\d{1,3}$")


def enabled() -> bool:
    return bool(settings.section_index_enabled)


def data() -> dict:
    if "data" not in _CACHE:
        raw = json.loads(DATA.read_text(encoding="utf-8"))
        _CACHE["data"] = {
            "classes": {
                k: re.compile(v, re.IGNORECASE)
                for k, v in raw["heading_classes"].items()
            },
            "item": re.compile(raw["item_heading"]),
            "item_words": int(raw["item_heading_max_words"]),
            "generic": frozenset(w.lower() for w in raw["generic_title_words"]),
        }
    return _CACHE["data"]


def heading_of_line(line: str, *, in_attachment: bool) -> str | None:
    """The heading this line is (the line itself, trimmed), or None. Item titles only inside an attachment. A table of
    contents entry (dot leaders, or a page number after leaders or a tab) is never a heading."""
    if _LEADERS.search(str(line or "")):
        return None
    text = " ".join(str(line or "").split())
    # a page number after plain spaces: a contents entry, in a run or alone
    if _ENDS_IN_NUMBER.search(text):
        return None
    if not text or len(text) > 160:
        return None
    d = data()
    if any(pattern.match(text) for pattern in d["classes"].values()):
        return text
    if in_attachment and d["item"].match(text) and len(text.split()) <= d["item_words"]:
        return text
    return None


def _is_caption(heading: str) -> bool:
    """A table or figure caption: it names a table or a figure, not a section of the document."""
    text = " ".join(heading.split())
    return any(
        data()["classes"][k].match(text) for k in ("table_title", "figure_title")
    )


def _flat(line: str) -> str:
    """A line as compared across extractions: spaces collapsed, every dash a hyphen."""
    return " ".join(str(line).replace("\u2013", "-").replace("\u2014", "-").split())


def _is_code_heading(heading: str) -> bool:
    """A coded attachment, appendix or annex title: a section of the document, not a part of one."""
    text = " ".join(heading.split())
    return any(data()["classes"][k].match(text) for k in ("code_title", "word_title"))


def _pages(document_id: str) -> dict[int, list[str]]:
    rows = (
        connect()
        .execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
        )
        .fetchall()
    )
    return {
        r["page_no"]: [_flat(x) for x in (r["text"] or "").split("\n")] for r in rows
    }


def _running(pages: dict[int, list[str]]) -> frozenset[str]:
    """Lines printed on three or more pages: running headers and footers."""
    seen: dict[str, set[int]] = {}
    for number, lines in pages.items():
        for line in lines:
            if len(line) >= _MIN_RUNNING:
                seen.setdefault(line, set()).add(number)
    floor = 3
    return frozenset(line for line, where in seen.items() if len(where) >= floor)


def _list_entries(lines: list[str]) -> frozenset[int]:
    """Indexes of lines that sit in a run of three or more consecutive heading-like lines with no text between them: a
    list of the attachments or tables (a contents list printed without page numbers), not the headings themselves."""
    like = [
        bool(line) and heading_of_line(line, in_attachment=True) is not None
        for line in lines
    ]
    inside: set[int] = set()
    start = None
    for at, flag in enumerate([*like, False]):
        if flag and start is None:
            start = at
        elif not flag and start is not None:
            if at - start >= 3:
                inside.update(range(start, at))
            start = None
    return frozenset(inside)


def _locate(
    heading: str, pages: dict[int, list[str]], cursor: tuple[int, int]
) -> tuple[int, int] | None:
    """(page, line) of the first print of `heading` at or after the cursor, within a few pages of it, else None. A print
    inside a list of headings (a contents list without page numbers) is not the heading."""
    page, index = cursor
    for number in range(page, page + _LOOKAHEAD + 1):
        lines = pages.get(number)
        if lines is None:
            continue
        listed = _list_entries(lines)
        for at in range(index if number == page else 0, len(lines)):
            if lines[at] == heading and at not in listed:
                return number, at
    return None


def _drop_contents_runs(
    found: list[tuple[int, str]], lines: list[str]
) -> list[tuple[int, str]]:
    """Three or more consecutive heading-like lines with no text between them are a list of the sections (a list of
    attachments, a contents list), not the sections: none of them is a heading, whether or not page numbers follow."""
    order = [i for i, line in enumerate(lines) if line.strip()]
    place = {i: n for n, i in enumerate(order)}
    drop: set[int] = set()
    run: list[int] = []
    for i, _ in found:
        if run and place[i] == place[run[-1]] + 1:
            run.append(i)
        else:
            if len(run) >= 3:
                drop.update(run)
            run = [i]
    if len(run) >= 3:
        drop.update(run)
    return [(i, h) for i, h in found if i not in drop]


def refine(body: list[dict], document_id: str) -> list[dict]:
    """`body`, with each passage re-split at the headings found in its text. Off: as given. A passage with no heading
    line inside is kept as it is; the pieces keep the passage's kind, each carries the page its heading is printed on
    and a page range that runs to the next heading's page (so a quote taken from its text is found on a page it spans)."""
    if not enabled():
        return body
    pages = _pages(document_id)
    running = _running(pages)
    out: list[dict] = []
    in_attachment = False
    last_section = None
    for chunk in body:
        section = (chunk.get("section") or "").strip()
        if section != last_section:
            in_attachment = _is_code_heading(section)
            last_section = section
        lines = str(chunk.get("text") or "").split("\n")
        found = []
        for i, line in enumerate(lines):
            heading = heading_of_line(line, in_attachment=in_attachment)
            if heading and _flat(heading) not in running:
                found.append((i, heading))
                in_attachment = in_attachment or _is_code_heading(heading)
        cuts = []
        cursor = (chunk.get("page_start") or 0, 0)
        for i, heading in _drop_contents_runs(found, lines):
            at = _locate(_flat(heading), pages, cursor)
            if at:  # a heading is indexed only when its own printed line is on a page, in order
                cuts.append((i, heading, at[0]))
                cursor = (at[0], at[1] + 1)
        if not cuts:
            out.append(chunk)
            continue
        end_page = chunk.get("page_end") or chunk.get("page_start")
        if cuts[0][0] > 0 and "\n".join(lines[: cuts[0][0]]).strip():
            out.append(
                {
                    **chunk,
                    "text": "\n".join(lines[: cuts[0][0]]).strip(),
                    "page_end": max(chunk.get("page_start") or 0, cuts[0][2]),
                }
            )
        parent = chunk.get("context") or section
        for n, (start, heading, page) in enumerate(cuts):
            stop = cuts[n + 1][0] if n + 1 < len(cuts) else len(lines)
            last = cuts[n + 1][2] if n + 1 < len(cuts) else max(page, end_page or page)
            out.append(
                {
                    **chunk,
                    "section": heading,
                    "context": f"{parent} > {heading}"
                    if parent and parent != heading
                    else heading,
                    "text": "\n".join(lines[start:stop]).strip(),
                    "page_start": page,
                    "page_end": last,
                    "locator": f"page {page}",
                    "ordinal": (chunk.get("ordinal") or 0) + (n + 1) / 1000,
                    "indexed_heading": True,
                    "heading_code": _is_code_heading(heading),
                    "heading_caption": _is_caption(heading),
                }
            )
    return out


_STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "their",
        "its",
        "into",
        "than",
        "then",
        "also",
        "not",
        "are",
        "was",
        "were",
        "been",
        "have",
        "has",
    ]
)


def _stems(text: str) -> set[str]:
    """Content words of a title, each cut to a stem (the first six letters, a plural s dropped), so "documents" and
    "documentation", "node" and "nodes" meet."""
    words = [
        w for w in re.findall(r"[a-z]{4,}", str(text or "").lower()) if w not in _STOP
    ]
    return {w[:6] if len(w) > 6 else w.rstrip("s") for w in words}


def _about(element_title: str, title: str) -> bool:
    """An indexed title is about the element only when it shares two content stems with the element's own title, or all
    its own content stems are in it ("Independent Protection Layers" is the element "Independent protection layers and
    their credit"; "Initiating Cause Frequency" is not "Causes, consequences and safeguards": one word in common is a
    coincidence)."""
    mine, theirs = _stems(element_title), _stems(title)
    shared = mine & theirs
    return len(shared) >= 2 or (bool(shared) and theirs <= mine)


def title_hit(element, chunk: dict, title: str, hits, *, near: bool = False) -> bool:
    """Does this title hold a cue of the element? `hits(phrases, text)` is the playbook's own cue match. Switch on:
    a generic title word is no cue; a heading found by the index (not one of the stored clause headings) is the element's
    own section only when it is also `_about` the element. `near`: the weaker claim "the closest section", for which a
    coded attachment title with a cue alone is enough (a table, figure or item title still needs `_about`)."""
    if not enabled():
        return any(hits(phrases, title) for _, phrases in element.groups)
    generic = data()["generic"]
    cued = any(
        hits(tuple(p for p in phrases if p.lower() not in generic), title)
        for _, phrases in element.groups
    )
    if not cued or not chunk.get("indexed_heading"):
        return cued
    if near and chunk.get("heading_code"):
        return True
    # a caption is at most the closest section, never the element's own
    if chunk.get("heading_caption"):
        return near and _about(element.title, title)
    return _about(element.title, title)


def heading_quotes(chunk: dict) -> list[str]:
    """The heading line of an indexed passage, as written and with its dashes flattened (the page text may print a
    different dash), for a row that cites a section whose own text states nothing (a title alone): the title is on the
    page, so it can be quoted and verified like any passage."""
    if not chunk.get("indexed_heading"):
        return []
    heading = chunk.get("section") or ""
    return list(dict.fromkeys([heading, _flat(heading)]))


def own_words() -> str:
    """The words of a partial hit on a heading: a closest section, not a claim that it is the element's own."""
    return (
        "the closest section is at"
        if enabled()
        else "a section of its own was found at"
    )


def none_words() -> str:
    """What the code can truthfully say when no heading names the element: no section is TITLED for it."""
    return "no section titled for it" if enabled() else "no section of its own"
