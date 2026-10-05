"""Mutations of `backend/app/quality.py` and `backend/app/extract.py`'s table
reader - chunking quality (2026-09-27, brief P0-1/P0-2). Kept together because
each module has fewer than three and they prove one change."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_chunking_quality.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1220", phase=97,
        description="the quality gate drops data rows and short requirements again",
        path=APP / "quality.py",
        anchor="    if words and (data_rows(text) or _REQUIREMENT_WORD.search(cleaned)",
        replacement="    if False and (data_rows(text) or _REQUIREMENT_WORD.search(cleaned)",
        target=_T, keyword="gate_keeps_data_rows or no_data_sheet_row_is_excluded",
        tags=("critical",),
    ),
    Mutation(
        id="M1221", phase=97,
        description="a recovered markdown table is not judged as a table",
        path=APP / "quality.py",
        anchor="    if rows >= 2 and rows >= 0.6 * len(lines):",
        replacement="    if False:",
        target=_T, keyword="recovered_table_is_judged_as_a_table",
    ),
    Mutation(
        id="M1243", phase=97,
        description="short requirement text is not rescued by its obligation word",
        path=APP / "quality.py",
        anchor="    if words and (data_rows(text) or _REQUIREMENT_WORD.search(cleaned)",
        replacement="    if words and (data_rows(text) or False",
        target=_T, keyword="gate_keeps_data_rows",
    ),
    Mutation(
        id="M1227", phase=97,
        description="extraction reads no tables: pages.tables_json is never written",
        path=APP / "extract.py",
        anchor="    found = page_tables(page, raw_text)",
        replacement="    found = []",
        target=_T, keyword="stores_ruled_tables or one_table_chunk_with_its_header",
        tags=("critical",),
    ),
    Mutation(
        id="M1244", phase=97,
        description="the batch commit drops the tables it was given",
        path=APP / "extract.py",
        anchor="        tables = rest[1] if len(rest) > 1 else None\n",
        replacement="        tables = None\n",
        target=_T, keyword="stores_ruled_tables",
    ),
)
