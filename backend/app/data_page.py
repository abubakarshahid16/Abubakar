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

from .config import settings
from .quality import MIN_CLAUSE_WORDS, longest_clause

# A line holding a number with a unit or a percent sign: "Rated flow : 210.0 l/s".
_MEASURED_LINE = re.compile(
    r"\d\s*(?:%|°\s*[CF]\b|[A-Za-zµ°]{1,6}(?:/[A-Za-z]{1,4})?\b)"
)
_MIN_MEASURED_LINES = 8
#: Enough measured values for any page: a datasheet's text often puts each label
#: and its value on separate lines, so the share alone undercounts it.
_MANY_MEASURED_LINES = 20


def is_data_page(lines: list[str]) -> bool:
    """A page of measured values: 20 lines that hold one, or 8 that are a third
    of the page. A book's copyright page holds a handful at most."""
    measured = sum(1 for line in lines if _MEASURED_LINE.search(line))
    return measured >= _MANY_MEASURED_LINES or (
        measured >= _MIN_MEASURED_LINES and measured * 3 >= len(lines)
    )


def body_or_data(text: str, lines: list[str]) -> bool:
    """True when the page is body text, or (switch on) a page of measured values."""
    from .chunker import count_clause_headings  # chunker imports this module

    if count_clause_headings(text) >= 1 and longest_clause(text) >= MIN_CLAUSE_WORDS:
        return True
    return settings.data_page_not_frontmatter_enabled and is_data_page(lines)
