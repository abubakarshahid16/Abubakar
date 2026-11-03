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
    carries its heading as its section, the page the heading is printed on, and its own text.
  * `title_hit`: a title is "about" an element only through a cue that is not a generic title word (`generic_title_words`:
    document, report, input, record ...): a clause titled "REFERENCE DATA AND DOCUMENTATION" is not about records.
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
    """The heading this line is (the line itself, trimmed), or None. Item titles only inside an attachment."""
    text = " ".join(str(line or "").split())
    if not text or len(text) > 160:
        return None
    d = data()
    if any(pattern.match(text) for pattern in d["classes"].values()):
        return text
    if (
        in_attachment
        and (m := d["item"].match(text))
        and len(text.split()) <= d["item_words"]
    ):
        return text if m else None
    return None


def _is_loose(heading: str) -> bool:
    """A numbered item title, a table title or a figure title: headings that name a part of a section, not a section
    of the document (an attachment or appendix with a code is the latter)."""
    text = " ".join(heading.split())
    return not any(
        data()["classes"][k].match(text) for k in ("code_title", "word_title")
    )


def _is_attachment_heading(heading: str) -> bool:
    d = data()
    return any(d["classes"][k].match(heading) for k in ("code_title", "word_title"))


def _flat(line: str) -> str:
    """A line as compared across extractions: spaces collapsed, every dash a hyphen."""
    return " ".join(str(line).replace("\u2013", "-").replace("\u2014", "-").split())


def _pages(document_id: str) -> dict[int, list[str]]:
    rows = (
        connect()
        .execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
        )
        .fetchall()
    )
    return {
        r["page_no"]: [" ".join(x.split()) for x in (r["text"] or "").split("\n")]
        for r in rows
    }


def refine(body: list[dict], document_id: str) -> list[dict]:
    """`body`, with each passage re-split at the headings found in its text. Off: as given. A passage with no heading
    line inside is kept as it is; the pieces keep the passage's kind and carry the page of their heading."""
    if not enabled():
        return body
    pages = _pages(document_id)
    out: list[dict] = []
    in_attachment = False
    last_section = None
    for chunk in body:
        section = (chunk.get("section") or "").strip()
        if section != last_section:
            in_attachment = _is_attachment_heading(section)
            last_section = section
        lines = str(chunk.get("text") or "").split("\n")
        cuts = []
        for i, line in enumerate(lines):
            heading = heading_of_line(line, in_attachment=in_attachment)
            if heading:
                cuts.append((i, heading))
                if _is_attachment_heading(heading):
                    in_attachment = True
        if not cuts:
            out.append(chunk)
            continue
        if cuts[0][0] > 0 and "\n".join(lines[: cuts[0][0]]).strip():
            out.append({**chunk, "text": "\n".join(lines[: cuts[0][0]]).strip()})
        parent = chunk.get("context") or section
        for n, (start, heading) in enumerate(cuts):
            end = cuts[n + 1][0] if n + 1 < len(cuts) else len(lines)
            page = _page_of(heading, chunk, pages)
            out.append(
                {
                    **chunk,
                    "section": heading,
                    "context": f"{parent} > {heading}"
                    if parent and parent != heading
                    else heading,
                    "text": "\n".join(lines[start:end]).strip(),
                    "page_start": page,
                    "page_end": page,
                    "locator": f"page {page}" if page else chunk.get("locator"),
                    "ordinal": (chunk.get("ordinal") or 0) + (n + 1) / 1000,
                    "indexed_heading": True,
                    "heading_loose": _is_loose(heading),
                }
            )
    return out


def _page_of(heading: str, chunk: dict, pages: dict[int, list[str]]) -> int | None:
    """The page the heading line is printed on, found in the stored page text: inside the passage's own page range
    first, then on any later page (a stored page range can be short), else the passage's first page."""
    first = chunk.get("page_start") or 0
    last = chunk.get("page_end") or first
    for number in range(first, last + 1):
        if _flat(heading) in pages.get(number, []):
            return number
    later = sorted(
        n for n, lines in pages.items() if n >= first and _flat(heading) in lines
    )
    return later[0] if later else chunk.get("page_start")


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
    """A numbered item, table or figure title is about the element only when it shares two content stems with the
    element's own title, or all its own content stems are in it ("Independent Protection Layers" is the element
    "Independent protection layers and their credit"; "Initiating Cause Frequency" is not "Causes, consequences and
    safeguards": one word in common is a coincidence)."""
    mine, theirs = _stems(element_title), _stems(title)
    shared = mine & theirs
    return len(shared) >= 2 or (bool(shared) and theirs <= mine)


def title_hit(element, chunk: dict, title: str, hits) -> bool:
    """Does this title hold a cue of the element? `hits(phrases, text)` is the playbook's own cue match. Switch on:
    a generic title word is no cue, so a title is about the element only through a word that names it; and an indexed
    numbered item, table or figure title (the new, unproven kinds of heading) is the element's own section only when
    it is also `_about` the element."""
    if not enabled():
        return any(hits(phrases, title) for _, phrases in element.groups)
    generic = data()["generic"]
    cued = any(
        hits(tuple(p for p in phrases if p.lower() not in generic), title)
        for _, phrases in element.groups
    )
    if cued and chunk.get("heading_loose"):
        return _about(element.title, title)
    return cued


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
