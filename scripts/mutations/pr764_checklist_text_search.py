"""PR #764 (planner F-a): a checklist field not read is searched in the page
text before anyone is blamed; the review states its reader coverage."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_checklist_text_search.py"
_D = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M764-01", phase=764, description="the text search is dropped (every unread field is just 'not found')",
             path=_D, anchor="            searched = label_search(field, rules, page_texts or {})\n",
             replacement="            searched = None\n",
             target=_T, keyword="reader_gap_with_its_page", tags=("checklist", "honesty", "critical")),
    Mutation(id="M764-02", phase=764, description="a label on the sheet is reported as the contractor's missing value",
             path=_D, anchor="            if searched:\n                pages = ",
             replacement="            if False:\n                pages = ",
             target=_T, keyword="reader_gap_with_its_page", tags=("checklist", "honesty", "critical")),
    Mutation(id="M764-03", phase=764, description="a page with no text still lets the search blame the contractor",
             path=_D, anchor="    if not page_texts or any(not (t or \"\").strip() for t in page_texts.values()):\n",
             replacement="    if not page_texts:\n",
             target=_T, keyword="no_text_decides_nothing", tags=("checklist", "honesty")),
    Mutation(id="M764-04", phase=764, description="a wrapped label is not found (lines searched one by one)",
             path=_D, anchor="        if any(p.search(folded) for p in patterns) or _words_near(words, folded.split()):\n",
             replacement="        if any(p.search(normalise_field_name(line)) for line in (text or '').splitlines() for p in patterns):\n",
             target=_T, keyword="reader_gap_with_its_page", tags=("checklist",)),
    Mutation(id="M764-05", phase=764, description="a text-searched absence is excused again by the page-reader rule",
             path=_D, anchor="                  or (r.get(\"checklist\") and r.get(\"fact_id\") is None and not r.get(\"text_searched\")))\n",
             replacement="                  or (r.get(\"checklist\") and r.get(\"fact_id\") is None))\n",
             target=_T, keyword="not_re_excused", tags=("checklist", "honesty")),
    Mutation(id="M764-06", phase=764, description="the review states no reader coverage",
             path=APP / "comparison.py",
             anchor="    if checklist_coverage:\n",
             replacement="    if False:\n",
             target="tests/test_746_checklist_governs.py", keyword="states_its_reader_coverage", tags=("checklist",)),
)
