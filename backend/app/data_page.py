"""Is a page body text or data, so that a publisher's marker does not set it aside?

Two kinds of page are never book front matter, whatever their footer says:
body text (a numbered clause heading and real prose, the NORSOK page-11 guard
in `chunker.classify_page`) and, behind DATA_PAGE_NOT_FRONTMATTER_ENABLED, a
page of measured values. Kit proof 1 Nov: every page of a vendor's pump
datasheet carried a copyright line, pages 2-5 were set aside, and the fact
reader never saw them.
"""

from __future__ import annotations

import re
from collections import Counter

from .config import settings
from .quality import MIN_CLAUSE_WORDS, longest_clause

# A number and the token after it: "210.0 l/s", "82 %", "35 °C". The token
# counts only when it is a unit `claims` knows, so "1980 edition", "12 Jan"
# and "Rev 3" are not measurements (review of #1527).
_VALUE_TOKEN = re.compile(r"\d\s*(%|°\s*[CF]\b|[A-Za-zµ°][A-Za-z0-9µ°/()]{0,9})")
_MIN_MEASURED_LINES = 8
#: Enough measured values for any page: a datasheet's text often puts each label
#: and its value on separate lines, so the share alone undercounts it.
_MANY_MEASURED_LINES = 20


def _measured(line: str) -> bool:
    from .claims import is_unit  # claims is heavy; only a marker page asks

    for m in _VALUE_TOKEN.finditer(line):
        token = m.group(1)
        if token == "%" or token.startswith("°") or is_unit(token):
            return True
    return False


def is_data_page(lines: list[str]) -> bool:
    """A page of measured values: 20 lines that hold one, or 8 that are a third
    of the page. A book's copyright page holds a handful at most."""
    measured = sum(1 for line in lines if _measured(line))
    return measured >= _MANY_MEASURED_LINES or (
        measured >= _MIN_MEASURED_LINES and measured * 3 >= len(lines)
    )


#: A rights line on at least this many pages is the document's running footer.
RUNNING_RIGHTS_MIN_PAGES = 3


def running_rights_lines(pages: list[tuple[int, str]]) -> frozenset[str]:
    """Normalised lines carrying a front-matter marker that repeat on three or
    more pages (RUNNING_FOOTER_NOT_FRONTMATTER_ENABLED; off: empty).

    Kit proof 1 Nov (#1478): a vendor's 5-page pump sheet printed one
    "Copyright ... All rights reserved." footer on pages 2-5; that one line is
    two markers, so its two performance-curve pages were set aside as book
    front matter and the fact reader never saw them. A book's credits page is
    one page and keeps its own markers (ISBN, editors, its own rights
    sentence) when the repeated footer is left out; only the repeated line
    stops counting.
    """
    if not settings.running_footer_not_frontmatter_enabled:
        return frozenset()
    from .chunker import (
        _AMBIGUOUS_FRONTMATTER_MARKERS,
        _FRONTMATTER_MARKERS,
        normalise_line,
    )

    markers = (*_FRONTMATTER_MARKERS, *_AMBIGUOUS_FRONTMATTER_MARKERS)
    seen: Counter[str] = Counter()
    for _page_no, text in pages:
        norms = {normalise_line(line) for line in text.splitlines()}
        seen.update(
            n for n in norms if n and len(n) <= 120 and any(m in n for m in markers)
        )
    return frozenset(n for n, c in seen.items() if c >= RUNNING_RIGHTS_MIN_PAGES)


def marker_text(text: str, footer: frozenset[str]) -> str:
    """The page's text, lower case, that front-matter markers are looked for in:
    without the document's running rights footer (`running_rights_lines`)."""
    if not footer:
        return text.lower()
    from .chunker import normalise_line

    return "\n".join(
        ln for ln in text.lower().splitlines() if normalise_line(ln) not in footer
    )


def footer_signature() -> str:
    """Joins the chunk signature, so switching RUNNING_FOOTER_NOT_FRONTMATTER on
    marks every document stale; off it adds nothing (signatures unchanged)."""
    return "+running-footer" if settings.running_footer_not_frontmatter_enabled else ""


def page_kind(text: str, page_no: int, total: int, footer: frozenset[str]) -> str:
    """`chunker.classify_page` with the running footer left out. A page 1 that
    was front matter only because of that footer and is a short title block
    stays front matter, so `classify_document_pages` still labels it the title
    page (title detection does not depend on the footer)."""
    from . import unsupported_script as script
    from .chunker import _is_title_page, classify_page

    kind = script.kind(text) or classify_page(text, page_no, total, footer)
    if (
        footer
        and page_no == 1
        and kind == "prose"
        and classify_page(text, page_no, total) == "frontmatter"
        and _is_title_page(text, page_no)
    ):
        return "frontmatter"
    return kind


def body_or_data(text: str, lines: list[str]) -> bool:
    """True when the page is body text, or (switch on) a page of measured values."""
    from .chunker import count_clause_headings  # chunker imports this module

    if count_clause_headings(text) >= 1 and longest_clause(text) >= MIN_CLAUSE_WORDS:
        return True
    return settings.data_page_not_frontmatter_enabled and is_data_page(lines)
