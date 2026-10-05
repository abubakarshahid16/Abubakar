"""Mutations of the round-3 chunker rules (CHUNKER_VERSION 10).

A numbered line that reads as a sentence is a clause, a change-type word never
builds a section label, a Summary of Changes table is excluded with its reason,
and page 1's title block is one searchable chunk. `tests/test_chunker_r3.py`
must notice each deletion.
"""

from __future__ import annotations

from ._base import APP, Mutation

_CH = APP / "chunker.py"
_T = "tests/test_chunker_r3.py"
_P = 2010

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M2010", phase=_P,
        description="a numbered line that reads as a sentence is a heading again",
        path=_CH,
        anchor="    if _reads_as_sentence(title):\n        return True\n",
        replacement="    if False:\n        return True\n",
        target=_T, keyword="keeps_its_sentence_in_the_body or capitals_on_the_next_line",
        tags=("citation", "critical"),
    ),
    Mutation(
        id="M2011", phase=_P,
        description="a modal verb no longer marks a title as a sentence",
        path=_CH,
        anchor="    if n >= _MODAL_MIN_WORDS and any(w in _MODALS for w in words):\n        return True\n",
        replacement="",
        target=_T, keyword="reads_as_a_sentence_is_a_clause or capitals_on_the_next_line",
    ),
    Mutation(
        id="M2012", phase=_P,
        description="a title of any length is accepted as a title",
        path=_CH,
        anchor="    if n > _TITLE_MAX_WORDS:\n        return True\n",
        replacement="",
        target=_T, keyword="reads_as_a_sentence_is_a_clause",
    ),
    Mutation(
        id="M2013", phase=_P,
        description="a sentence opener with a comma no longer marks a title as a sentence",
        path=_CH,
        anchor="    return (n >= _SUBORDINATE_MIN_WORDS and words[0] in _SUBORDINATORS\n            and \",\" in core)",
        replacement="    return False",
        target=_T, keyword="reads_as_a_sentence_is_a_clause",
    ),
    Mutation(
        id="M2014", phase=_P,
        description="sentence rule over-reaches: every title of 3+ words is a sentence",
        path=_CH,
        anchor="    n = len(words)\n    if n > _TITLE_MAX_WORDS:",
        replacement="    n = len(words)\n    if n >= 3:\n        return True\n    if n > _TITLE_MAX_WORDS:",
        target=_T, keyword="genuine_short_title or genuine_headings_keep",
    ),
    Mutation(
        id="M2015", phase=_P,
        description="a number plus a change-type word builds a section label again",
        path=_CH,
        anchor="    if _is_change_type_title(title):\n        return None\n",
        replacement="",
        target=_T, keyword="change_type_word_is_never_a_section_label or split_line_form",
        tags=("citation",),
    ),
    Mutation(
        id="M2016", phase=_P,
        description="the change-type label rule also bans a real title like 'Addition of ...'",
        path=_CH,
        anchor="    return len(words) == 1 or words[1].strip(\".,;:\").casefold() not in _TITLE_CONNECTIVES",
        replacement="    return True",
        target=_T, keyword="change_type_word_is_never_a_section_label",
    ),
    Mutation(
        id="M2017", phase=_P,
        description="a Summary of Changes page is never classified as revision history",
        path=_CH,
        anchor="        if kinds[pno] == \"prose\" and is_change_table_page(",
        replacement="        if False and is_change_table_page(",
        target=_T, keyword="classified_revision_history or excluded_with_a_recorded_reason",
        tags=("critical",),
    ),
    Mutation(
        id="M2018", phase=_P,
        description="change-table rows alone, with no title or columns, are enough",
        path=_CH,
        anchor="    return bool(_PARAGRAPH_COLUMN.search(text) and _CHANGE_TYPE_COLUMN.search(text))",
        replacement="    return True",
        target=_T, keyword="detected_by_its_columns or continuation_page or classified_revision_history",
    ),
    Mutation(
        id="M2019", phase=_P,
        description="a change table never continues onto the next page",
        path=_CH,
        anchor="    if continues_history:\n        return True\n",
        replacement="",
        target=_T, keyword="continuation_page_with_only_rows",
    ),
    Mutation(
        id="M2020", phase=_P,
        description="change-table detection does not need rows to dominate the page's numbered lines",
        path=_CH,
        anchor="    return (len(rows) >= _MIN_CHANGE_ROWS\n            and len(rows) >= len(starters) * _MIN_CHANGE_ROW_SHARE)",
        replacement="    return len(rows) >= 1",
        target=_T, keyword="too_few_rows or among_many_other_numbered_clauses or detected_by_its_columns",
    ),
    Mutation(
        id="M2021", phase=_P,
        description="the title block on page 1 is not kept searchable",
        path=_CH,
        anchor="        elif kinds[pno] == \"frontmatter\" and _is_title_page(text, pno):",
        replacement="        elif False:",
        target=_T, keyword="title_block_becomes_one_searchable_chunk or excluded_with_a_recorded_reason",
        tags=("critical",),
    ),
    Mutation(
        id="M2022", phase=_P,
        description="a title block is accepted on any page, not only the first",
        path=_CH,
        anchor="    if page_no != 1:\n        return False\n",
        replacement="",
        target=_T, keyword="title_page_is_page_one_only",
    ),
    Mutation(
        id="M2023", phase=_P,
        description="a page with a contents word or dot leaders can be a title page",
        path=_CH,
        anchor="    if any(_CONTENTS_WORD.match(ln) or _DOT_LEADER.search(ln) for ln in lines):\n        return False\n",
        replacement="",
        target=_T, keyword="contents_page_never_becomes",
        tags=("critical",),
    ),
    Mutation(
        id="M2024", phase=_P,
        description="a long first page can be a title page (no size bound)",
        path=_CH,
        anchor="    if not lines or len(lines) > _TITLE_PAGE_MAX_LINES or len(text.split()) > _TITLE_PAGE_MAX_WORDS:\n        return False\n",
        replacement="    if not lines:\n        return False\n",
        target=_T, keyword="long_first_page",
    ),
    Mutation(
        id="M2025", phase=_P,
        description="a book's credits page (publishing markers) can be a title page",
        path=_CH,
        anchor="    if any(m in low for m in markers):\n        return False\n",
        replacement="",
        target=_T, keyword="credits_page_never_becomes",
    ),
    Mutation(
        id="M2026", phase=_P,
        description="the change table's exclusion is recorded with the generic reason",
        path=_CH,
        anchor="HISTORY_REASON if kind == HISTORY_KIND else f\"page classified as {kind}\"",
        replacement="f\"page classified as {kind}\"",
        target=_T, keyword="excluded_with_a_recorded_reason",
    ),
    Mutation(
        id="M2027", phase=_P,
        description="the 'real content dropped' alarm fires on a change table's own rows",
        path=_CH,
        anchor="            text = \"\\n\".join(ln for ln in text.splitlines() if not _CHANGE_ROW.match(ln))\n",
        replacement="            pass\n",
        target=_T, keyword="excluded_with_a_recorded_reason",
    ),
    Mutation(
        id="M2028", phase=_P,
        description="a title page is recorded as excluded instead of published",
        path=_CH,
        anchor="SEARCHED_PAGE_KINDS = RETRIEVABLE_KINDS | {TITLE_KIND}",
        replacement="SEARCHED_PAGE_KINDS = RETRIEVABLE_KINDS",
        target=_T, keyword="excluded_with_a_recorded_reason",
    ),
    Mutation(
        id="M2029", phase=_P,
        description="the title page is segmented as ordinary page text with no label",
        path=_CH,
        anchor="                blocks.append(Block(\"prose\", body, page_no, page_no, TITLE_SECTION))",
        replacement="                blocks.append(Block(\"prose\", body, page_no, page_no, None))",
        target=_T, keyword="title_block_becomes_one_searchable_chunk or excluded_with_a_recorded_reason",
    ),
)
