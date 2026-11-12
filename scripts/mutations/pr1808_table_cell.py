"""ONE REVIEWER, the table cell (owner, 12 Nov 2026; redesign/TABLE-VALUE.md): per-tag groups, the settling of a held reading, the cell locator and the
slash-compound split. Each entry deletes one control; `tests/test_b1_table_cell.py` (or the step test) must notice. Ids M1808-07 onwards (CLAUDE.md rule 12;
the PR number is not known yet: renumber to the PR's own number when it is opened, as the rule says)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_b1_table_cell.py"
_C = APP / "agent_review_calculator_cells.py"
_K = APP / "table_cell.py"
_TAGS = ("honesty", "critical", "calculator")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1808-07", phase=1808,
             description="a sheet is not grouped by tag: every tag's facts are pooled again",
             path=_C, anchor="    return tag if tag else f\"page {fact.get('page')}\"\n", replacement='    return "all"\n',
             target=_T, keyword="grouped_by_tag", tags=_TAGS),
    Mutation(id="M1808-08", phase=1808,
             description="a hold that is only other tags' values is not lifted",
             path=_C, anchor="    if not in_group and (rivals or other_pages):\n", replacement="    if False:\n",
             target=_T, keyword="only_other_tags", tags=_TAGS),
    Mutation(id="M1808-09", phase=1808,
             description="two readings are settled by a cell even when the cell holds neither or both (any located reading is kept)",
             path=_C, anchor="    if len(located) != 1 or not rivals:\n", replacement="    if not located or not rivals:\n",
             target=_T, keyword="settled_by_the_cell", tags=_TAGS),
    Mutation(id="M1808-10", phase=1808,
             description="a cell is taken even when a non-empty cell stands between the label and the value",
             path=_K, anchor="    return all(not _fold(c) for c in row[i + 1 : j])\n", replacement="    return True\n",
             target=_T, keyword="non_empty_cell_between", tags=_TAGS),
    Mutation(id="M1808-11", phase=1808,
             description="a header that matches two columns, or a label on two rows, still gives a cell",
             path=_K, anchor="        if len(cols) == 1 and len(label_rows) == 1:\n", replacement="        if cols and label_rows:\n",
             target=_T, keyword="header_that_matches_two", tags=_TAGS),
    Mutation(id="M1808-12", phase=1808,
             description="a compound row splits although the counts of label parts and figures differ",
             path=_K, anchor="    if len(figures) != len(names):\n", replacement="    if False:\n",
             target=_T, keyword="does_not_split_cleanly", tags=_TAGS),
    Mutation(id="M1808-13", phase=1808,
             description="a compound row splits when the unit stands on one part only or the units differ",
             path=_K, anchor="    elif not (units[0] and len(set(units)) == 1):\n", replacement="    elif False:\n",
             target=_T, keyword="does_not_split_cleanly", tags=_TAGS),
)
