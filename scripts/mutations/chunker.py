"""Mutations of `backend/app/chunker.py` - chunking quality (2026-09-27).

Brief P0 + audit F1, F2, F4, F5, F8, F10: tables read by geometry, data-sheet
rows, sentences across page breaks, running lines, numbering gaps, long
numbered requirements, hyphenation, duplicates, versioning. Each entry deletes
one of those features; `tests/test_chunking_quality.py` must notice. Older
chunker mutations stay in `misc.py`.
"""

from __future__ import annotations

from ._base import APP, Mutation

_CH = APP / "chunker.py"
_T = "tests/test_chunking_quality.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1222", phase=97,
        description="data-sheet rows are not recognised: 'Mixing Ratio' / ': 4:1' is a clause again",
        path=_CH,
        anchor='    if not any(":" in r for r in rows):\n        return [], 0',
        replacement="    return [], 0",
        target=_T, keyword="data_sheet_rows_become_one_table_block",
    ),
    Mutation(
        id="M1223", phase=97,
        description="ruled tables are not masked: cells reach the heading detector and the prose",
        path=_CH,
        anchor="    masked = mask_tables(pages, _decode_tables(raw_tables), running)",
        replacement="    masked = pages",
        target=_T, keyword="one_table_chunk_with_its_header or long_table_is_split",
        tags=("critical",),
    ),
    Mutation(
        id="M1224", phase=97,
        description="a ruled header box on every page is published as a table",
        path=_CH,
        anchor="            if body and all(_is_running(r, running, page_no) for r in body):\n"
               "                continue",
        replacement="            pass",
        target=_T, keyword="header_box_on_every_page",
    ),
    Mutation(
        id="M1225", phase=97,
        description="a table continued on the next page becomes a second table",
        path=_CH,
        anchor="            if (header and prev is not None and prev.rows is not None",
        replacement="            if (False and prev is not None and prev.rows is not None",
        target=_T, keyword="continued_on_the_next_page",
    ),
    Mutation(
        id="M1226", phase=97,
        description="split table pieces lose their caption and header row",
        path=_CH,
        anchor='        text = "\\n".join(lead + [rows[k] for k in idx])',
        replacement='        text = "\\n".join((lead if idx[0] == 0 else []) + [rows[k] for k in idx])',
        target=_T, keyword="long_table_is_split_on_rows",
    ),
    Mutation(
        id="M1228", phase=97,
        description="a sentence running over a page break is cut in two again",
        path=_CH,
        anchor="            pending = units.pop()",
        replacement="            pass",
        target=_T, keyword="across_a_page_break",
    ),
    Mutation(
        id="M1229", phase=97,
        description="line-break hyphens are left in ('galvan- ized')",
        path=_CH,
        anchor="    return _LINE_HYPHEN.sub(lambda m: _join_hyphenated(m.group(1), m.group(2), vocab), text)",
        replacement="    return text",
        target=_T, keyword="hyphens_are_repaired or own_spelling",
    ),
    Mutation(
        id="M1230", phase=97,
        description="';' and ':' end a unit again, so chunks start mid-sentence",
        path=_CH,
        anchor='_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\\"\'\\u201d\\u2019)\\]]*\\s+(?=[^a-z\\s])")',
        replacement='_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\\s+")',
        target=_T, keyword="colon_or_abbreviation",
    ),
    Mutation(
        id="M1231", phase=97,
        description="runt threshold back to 25 tokens",
        path=_CH,
        anchor="_MIN_CHUNK_TOKENS = 40",
        replacement="_MIN_CHUNK_TOKENS = 25",
        target=_T, keyword="runt_under_forty_tokens",
    ),
    Mutation(
        id="M1232", phase=97,
        description="any bare number at a page edge is stripped as a page number (table values lost)",
        path=_CH,
        anchor='                    and f"{_PAGENO_MARK}{int(m.group(1)) - page_no}" in running)',
        replacement="                    or True)",
        target=_T, keyword="foot_of_a_page_survive",
        tags=("critical",),
    ),
    Mutation(
        id="M1233", phase=97,
        description="a header block longer than the edge window leaks into the text",
        path=_CH,
        anchor="    while top < min(len(lines), limit) and (",
        replacement="    while False and (",
        target=_T, keyword="header_block_longer_than",
    ),
    Mutation(
        id="M1234", phase=97,
        description="one missing sibling number disables every later sibling again",
        path=_CH,
        anchor="            if not accepted or n <= accepted[-1] + 3 or name(n) in parents_with_children:",
        replacement="            if not accepted or n == accepted[-1] + 1:",
        target=_T, keyword="missing_sibling or after_a_gap or children_vouch",
        tags=("critical",),
    ),
    Mutation(
        id="M1235", phase=97,
        description="a table-like run swallows the heading after it",
        path=_CH,
        anchor="        if j > i and stop is not None and stop(lines, j):\n            break",
        replacement="        pass",
        target=_T, keyword="run_stops_at_the_heading",
    ),
    Mutation(
        id="M1236", phase=97,
        description="a long numbered requirement stays under its parent clause",
        path=_CH,
        anchor="    return m.group(1) if _OBLIGATION.search(sentence) else None",
        replacement="    return None",
        target=_T, keyword="long_numbered_requirement",
    ),
    Mutation(
        id="M1237", phase=97,
        description="a wrapped requirement's first line is consumed as a title",
        path=_CH,
        anchor="                    and _continues_as_sentence(lines, i + consumed))):",
        replacement="                    and False)):",
        target=_T, keyword="wrapped_requirement",
    ),
    Mutation(
        id="M1238", phase=97,
        description="identical chunks in one section all stay searchable",
        path=_CH,
        anchor="        if key in first:\n            dups[ordinal] = first[key]",
        replacement="        if False:\n            dups[ordinal] = first[key]",
        target=_T, keyword="kept_once or two_citations",
    ),
    Mutation(
        id="M1239", phase=97,
        description="extracted tables are left out of the chunk signature",
        path=_CH,
        anchor="        if tables.get(pno):",
        replacement="        if False:",
        target=_T, keyword="part_of_the_chunk_signature",
    ),
    Mutation(
        id="M1240", phase=97,
        description="CHUNKER_VERSION not bumped: old chunks are not detected stale",
        path=_CH,
        anchor='CHUNKER_VERSION = "5"',
        replacement='CHUNKER_VERSION = "4"',
        target=_T, keyword="previous_chunker_are_stale",
    ),
    Mutation(
        id="M1241", phase=97,
        description="a page-top heading sharing a digit-masked shape is stripped as furniture",
        path=_CH,
        anchor="            and (looks_like_heading(stripped) or _CLAUSE_NUMBER_LEAD.match(stripped))):",
        replacement="            and False):",
        target=_T, keyword="page_top_heading",
    ),
    Mutation(
        id="M1242", phase=97,
        description="a word hyphenated across a page break is not rejoined",
        path=_CH,
        anchor="    if m and n:",
        replacement="    if False:",
        target=_T, keyword="across_a_page_break",
    ),
)
