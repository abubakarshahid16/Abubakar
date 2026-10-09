"""#660: a requirement cites the page its sentence is on. Ids M4951-M4957."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w6_660_requirement_page.py"
_S = APP / "standards.py"
_TAG = ("w6", "citation")


def _m(i, desc, anchor, repl, kw):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=_S, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4951, "a requirement always cites the chunk's first page",
       "    if not page_texts or last <= first:\n        return first\n",
       "    return first\n", "second_page_of_a_spanning_chunk"),
    _m(4952, "only the first page of a spanning chunk is searched",
       "    for page_no in range(first, last + 1):",
       "    for page_no in range(first, first + 1):", "second_page_of_a_spanning_chunk"),
    _m(4953, "a sentence found nowhere is given the last page",
       "            return page_no\n    return first\n",
       "            return page_no\n    return last\n", "not_found_on_any_page"),
    _m(4954, "the page texts of a spanning chunk are never read",
       "    if chunk[\"page_end\"] <= chunk[\"page_start\"]:\n        return None\n    rows",
       "    return None\n    rows", "second_page_of_a_spanning_chunk"),
    _m(4955, "a new requirement is written with the chunk's first page",
       "                        page=sentence_page(chunk, sentence, pages_of_chunk),",
       "                        page=chunk[\"page_start\"],", "second_page_of_a_spanning_chunk"),
    _m(4956, "a requirement met again keeps the first page",
       "            (chunk[\"id\"], page if page is not None else chunk[\"page_start\"], run_id,",
       "            (chunk[\"id\"], chunk[\"page_start\"], run_id,", "moves_a_kept_requirement"),
    _m(4957, "punctuation and line breaks are not folded away before searching",
       "    return _ALNUM.sub(\"\", (text or \"\").lower())",
       "    return (text or \"\").lower()", "line_breaks_and_hyphens"),
)
