"""PR 1581: a Word file's page on the CRS is real, marked partial, or its section
heading; a reading part is never printed as a page, and what was not read is said."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_word_page_markers.py"
_P = APP / "crs_mapping.py"


def _m(number: int, description: str, anchor: str, replacement: str) -> Mutation:
    return Mutation(
        id=f"M1581-{number:02d}",
        phase=1581,
        description=description,
        path=_P,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        tags=("honesty", "critical"),
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the page cell prints a reading part as a page",
        '        word_pages.at_pages(pages, group) if pages else "",\n',
        '        f"p.{_page_list(pages)}" if pages else "",\n',
    ),
    _m(
        2,
        "the comment sentence prints a reading part as a page",
        '        f"{word_pages.at_pages(pages, group)}," if pages else "",\n',
        '        f"p.{_page_list(pages)}," if pages else "",\n',
    ),
    _m(
        3,
        "the reasoning line prints a reading part as a page",
        """(f" ({word_pages.at(f)})" if page else ""))\n""",
        """(f" (p.{page})" if page else ""))\n""",
    ),
    _m(
        4,
        "a per-tag value prints a reading part as a page",
        """(f" ({word_pages.at(g)})" if g.get("contractor_page") else "")\n""",
        """(f" (p.{g['contractor_page']})" if g.get("contractor_page") else "")\n""",
    ),
    _m(
        5,
        "the safety tick prints a reading part as a page",
        """(f"{word_pages.at(f)}," if page else "", field)""",
        """(f"p.{page}," if page else "", field)""",
    ),
    _m(
        6,
        "the Review notes drop what was not read and the missing pages",
        "    return notes + word_pages.review_notes(findings)\n",
        "    return notes\n",
    ),
    _m(
        7,
        "an AI or web draft row prints a reading part as a page",
        """            word_pages.at(f) if f.get("contractor_page") else "",\n""",
        """            f"p.{f['contractor_page']}" if f.get("contractor_page") else "",\n""",
    ),
)
