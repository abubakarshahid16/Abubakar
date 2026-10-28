"""Where in a standard a page sits, and whether a stored limit is whole (order 305.3). Pure, no database, no model.

A limit read from an appendix, a special-construction part or a worked example does not apply to every
equipment; a limit stored as a fragment or as the end of a range is not a plain ceiling. The converter and the
review need these facts per page and per stored sentence, from the standard's own headings and running
headers, never from one standard's layout.

`tag_pages(pages)` reads the pages of ONE standard in page order and gives each page a scope:

  main_body              nothing on or before the page marks it as anything else
  mandatory_appendix     under a heading "Mandatory Appendix N" / "Annex N (normative)"
  nonmandatory_appendix  "Nonmandatory Appendix" / "Annex N (informative)"
  appendix               an "Appendix" or "Annex" that does not say which
  special_part           under a "Part X" heading whose title restricts it to one kind of construction
  part_unknown           under a "Part X" heading whose title cannot be read (it is never main body)

and `example` (a worked example starts on the page and no heading has closed it). A region carries over to the
pages after its heading until the next heading of a region; a page that holds both a main-body stretch and a
heading is tagged with the stricter side and `boundary` True. The safe direction is always "not main body":
when in doubt a page is NOT main body, because main body is the only scope that may decide without an engineer.

It lives in app/ (moved from scripts/ by order 304.1, which is its first reader: the converter's scope gate).

`fragment_reasons(text)` and `range_boundary(text, limit)` look at one stored requirement sentence."""

from __future__ import annotations

import re

MAIN, MANDATORY, NONMANDATORY, APPENDIX = (
    "main_body",
    "mandatory_appendix",
    "nonmandatory_appendix",
    "appendix",
)
SPECIAL, PART_UNKNOWN = "special_part", "part_unknown"
#: Strictest first: the scope a mixed page gets.
_ORDER = (SPECIAL, PART_UNKNOWN, MANDATORY, NONMANDATORY, APPENDIX, MAIN)

#: A heading line is short and is not a sentence: it has no full stop at the end.
_MAX_HEADING_WORDS = 14
_APPENDIX = re.compile(
    r"^\s*(?:(?P<q>non-?\s?mandatory|mandatory|normative|informative)\s+)?"
    r"(?P<kind>appendix|annex)\s+(?P<id>(?-i:[A-Z]{1,2}\d{0,2}|\d{1,3}|[IVX]{1,5}))\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_ANNEX_TAIL = re.compile(
    r"\((?P<q>normative|informative)\)|\b(?P<q2>normative|informative)\b", re.IGNORECASE
)
_PART = re.compile(
    r"^\s*PART\s+(?P<id>[A-Z]{1,5}\d?)\b[\s:.\-\u2013\u2014]*(?P<title>.*)$"
)
_EXAMPLE = re.compile(
    r"^\s*(?:worked\s+|design\s+|calculation\s+)?example\b\s*[\dA-Z]*\s*[:.\-\u2013\u2014]?",
    re.IGNORECASE,
)
#: A numbered clause heading ("5.3 Relieving pressure", "6 Installation") closes an example.
_NUMBERED = re.compile(r"^\s*\d{1,2}(?:\.\d{1,3}){0,3}\s+[A-Z][A-Za-z]")
#: A part whose title says it applies to everything is main body; every other titled part is special.
_GENERAL_PART = re.compile(
    r"\b(?:general|introduction|scope|all\s+(?:methods|materials|vessels|equipment))\b",
    re.IGNORECASE,
)


#: A contents entry ends on dot leaders or a page number ("Annex D (informative) Sizing .... 41").
_CONTENTS_ENTRY = re.compile(r"\S.*(?:(?:\.|(?:\s\.)){3,}\s*\d*|\s\d{1,3})\s*$")
#: Lines of the page that count as its top: running headers and the heading of a page that opens a region.
_TOP_LINES = 8
#: A page with this many region headings is a contents page, not the start of a region.
_CONTENTS_PAGE_HEADINGS = 3


def _is_heading_line(line: str) -> bool:
    words = line.split()
    return 0 < len(words) <= _MAX_HEADING_WORDS and not line.rstrip().endswith(
        (".", ",", ";")
    )


def _is_region_heading(
    match: re.Match, line: str, position: int, previous: str = ""
) -> bool:
    """A line that matches a region pattern is a heading only when it is not a sentence that happens to start
    with the word (a wrapped "Appendix E applies to ..."), not a contents entry, and, below the top of the page,
    carries a strong mark (capitals, or the standard's own word normative / mandatory)."""
    rest = (
        match.groupdict().get("rest") or match.groupdict().get("title") or ""
    ).strip()
    if _CONTENTS_ENTRY.search(rest):
        return False
    first = rest.lstrip("-\u2013\u2014:. ")[:1]
    if first and first.isalpha() and first.islower():
        return False
    before = previous.rstrip()
    if len(before.split()) >= 5 and before[-1:] in ",abcdefghijklmnopqrstuvwxyz":
        return False
    if position < _TOP_LINES:
        return True
    qualifier = match.groupdict().get("q") or _ANNEX_TAIL.search(rest)
    return bool(qualifier) or line.strip().isupper()


def _appendix_scope(match: re.Match) -> str:
    qualifier = (match.group("q") or "").lower().replace(" ", "").replace("-", "")
    if not qualifier:
        tail = _ANNEX_TAIL.search(match.group("rest") or "")
        qualifier = ((tail.group("q") or tail.group("q2")) if tail else "").lower()
    if qualifier in ("mandatory", "normative"):
        return MANDATORY
    if qualifier in ("nonmandatory", "informative"):
        return NONMANDATORY
    return APPENDIX


def _part_scope(match: re.Match, following: list[str]) -> str:
    title = match.group("title").strip() or next(
        (f.strip() for f in following[:2] if f.strip()), ""
    )
    if not title:
        return PART_UNKNOWN
    return MAIN if _GENERAL_PART.search(title) else SPECIAL


def tag_pages(pages: dict[int, str]) -> dict[int, dict]:
    """`{page number: {"scope", "region", "example", "boundary"}}` for the pages of one standard, read in order.
    `region` is the heading's own label ("Appendix 9", "Part UHT"), never a sentence."""
    out: dict[int, dict] = {}
    scope, region, example = MAIN, None, False
    for number in sorted(pages):
        start_scope = scope
        seen = [(scope, region)]
        lines = [ln for ln in (pages[number] or "").splitlines() if ln.strip()]
        content_before_heading = False
        mixed = False
        found = [
            (_APPENDIX.match(ln), _PART.match(ln))
            if _is_heading_line(ln)
            else (None, None)
            for ln in lines
        ]
        contents_page = sum(1 for a, q in found if a or q) >= _CONTENTS_PAGE_HEADINGS
        for i, line in enumerate(lines):
            if not _is_heading_line(line):
                content_before_heading = True
                continue
            appendix, part = found[i]
            heading = appendix or part
            if heading and (
                contents_page
                or not _is_region_heading(heading, line, i, lines[i - 1] if i else "")
            ):
                appendix = part = None
            if appendix:
                if content_before_heading and scope == MAIN:
                    mixed = True
                scope = _appendix_scope(appendix)
                region, example = (
                    f"{appendix.group('kind').title()} {appendix.group('id')}",
                    False,
                )
            elif part:
                if content_before_heading and scope == MAIN:
                    mixed = True
                scope, region, example = (
                    _part_scope(part, lines[i + 1 :]),
                    f"Part {part.group('id')}",
                    False,
                )
            elif _EXAMPLE.match(line):
                example = True
            elif _NUMBERED.match(line) and example:
                example = False
            else:
                content_before_heading = True
                continue
            seen.append((scope, region))
        strictest, strict_region = min(seen, key=lambda pair: _ORDER.index(pair[0]))
        out[number] = {
            "scope": strictest,
            "region": strict_region,
            "example": example
            or any(_EXAMPLE.match(ln) and _is_heading_line(ln) for ln in lines),
            "boundary": mixed or (start_scope != scope),
        }
    return out


# ---- one stored sentence ---------------------------------------------------------------------------------------

#: Words that cannot open a sentence of their own. "For", "In", "Where", "If" can, so they are not here.
_CONNECTIVE = (
    "and",
    "or",
    "but",
    "except",
    "unless",
    "provided",
    "which",
    "whose",
    "than",
    "also",
    "then",
    "nor",
    "that",
)
_TRAILING_FUNCTION_WORD = re.compile(
    r"\b(?:and|or|of|the|a|an|to|for|with|in|on|at|by|than|that|which|from|as|is|are|be|shall|should|may|not)\s*[,;:\-\u2013]?$",
    re.IGNORECASE,
)
_FIRST_FIGURE = re.compile(r"(?<![A-Za-z0-9_.-])\d+(?:[.,]\d+)*")
_MIN_WORDS_BEFORE_LIMIT = 3
_MIN_CHARS = 25


def fragment_reasons(text: str | None) -> list[str]:
    """Why a stored requirement sentence is a fragment, [] when it reads as a whole sentence: it starts mid-sentence
    (lower case or a connective), it has fewer than three words before its first figure (no subject), it ends on a
    function word or a dangling punctuation mark, or it is shorter than a sentence can be."""
    body = " ".join((text or "").split())
    if not body:
        return ["empty"]
    reasons: list[str] = []
    first = body.lstrip("\"'“‘([").split(" ", 1)[0]  # noqa: RUF001
    if first[:1].islower() or first.lower().strip(",;:") in _CONNECTIVE:
        reasons.append("starts_mid_sentence")
    figure = _FIRST_FIGURE.search(body)
    if figure and len(body[: figure.start()].split()) < _MIN_WORDS_BEFORE_LIMIT:
        reasons.append("no_subject_before_limit")
    if _TRAILING_FUNCTION_WORD.search(body) or body.endswith((",", "-", "\u2013", "(")):
        reasons.append("cut_mid_clause")
    if len(body) < _MIN_CHARS:
        reasons.append("too_short")
    return reasons


_UNIT = r"(?:\s*(?:[A-Za-z%°/²³]+(?:\s?[A-Za-z%°/²³]+)?))?"
_NUM = r"\d+(?:[.,]\d+)*"


def range_boundary(text: str | None, limit: str) -> bool:
    """Is `limit` (the number the converter stored) one END of a range in the sentence ("from 1000 to 3000 kPa",
    "between 15 and 70 bar", "over 1000 and up to 3000", "10-50 bar") and not a plain ceiling or floor? Both ends
    count: either end alone does not state a limit the equipment can be held to."""
    body = " ".join((text or "").split())
    number = re.escape(str(limit).strip())
    if not body or not number:
        return False
    patterns = (
        rf"\b(?:from|between)\b[^.;]{{0,40}}?(?<![\w.]){number}(?![\w.]){_UNIT}\s+(?:to|and|through|up to)\s+{_NUM}",
        rf"\b(?:from|between)\b[^.;]{{0,40}}?{_NUM}{_UNIT}\s+(?:to|and|through|up to)\s+{number}(?![\w.])",
        rf"(?<![\w.]){number}(?![\w.]){_UNIT}\s*(?:to|through)\s*{_NUM}",
        rf"{_NUM}{_UNIT}\s*(?:to|through)\s*{number}(?![\w.])",
        rf"\b(?:over|above|exceeding|greater than|more than)\s+{number}(?![\w.]){_UNIT}[^.;]{{0,25}}?\b(?:up to|not exceeding|not more than|less than|and below)\b",
        rf"\b(?:up to|not exceeding|not more than|less than)\s+{number}(?![\w.]){_UNIT}[^.;]{{0,25}}?\b(?:over|above|exceeding|greater than|more than)\s+{_NUM}",
    )
    return any(re.search(p, body, re.IGNORECASE) for p in patterns) or _dashed_range(
        body, str(limit).strip()
    )


_DASHED = re.compile(
    rf"(?<![\w.\u2013-])({_NUM})\s*([A-Za-z%\u00b0/]*)\s*[-\u2013]\s*({_NUM})\s*([A-Za-z%\u00b0/]*)"
)


def _dashed_range(body: str, limit: str) -> bool:
    """ "10-50 bar", "10 bar - 50 bar": a dash is a range only when a unit sits on one of the two figures. Without a
    unit a dash joins a code ("ISO 15156-3", "SAES-J-600 8-3"), not two ends of a range."""
    from . import field_vocabulary

    wanted = limit.replace(",", ".")
    for m in _DASHED.finditer(body):
        first, u1, second, u2 = m.groups()
        if wanted not in (first.replace(",", "."), second.replace(",", ".")):
            continue
        if any(field_vocabulary._unit_families(u) for u in (u1, u2) if u):
            return True
    return False
