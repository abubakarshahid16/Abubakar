"""Mutations for the document-reading audit (2026-09-30, reading findings 1-6).

Each entry deletes one fix; `tests/test_audit_reading.py` must notice.
Ids M1540-M1559 are reserved for this file.
"""

from __future__ import annotations

from ._base import APP, Mutation

_EX = APP / "extract.py"
_CH = APP / "chunker.py"
_Q = APP / "quality.py"
_OCR = APP / "ocr.py"
_T = "tests/test_audit_reading.py"

MUTATIONS: tuple[Mutation, ...] = (
    # 1. rotated pages
    Mutation(
        id="M1540", phase=98,
        description="rotated page: table box left in display coordinates, table discarded",
        path=_EX,
        anchor="    derotate = page.derotation_matrix if page.rotation % 360 else None",
        replacement="    derotate = None",
        target=_T, keyword="rotated_page",
    ),
    Mutation(
        id="M1541", phase=98,
        description="rotated page: rows kept in display order (columns read as rows)",
        path=_EX,
        anchor="                cells = _unrotated_rows(table, cells, derotate)",
        replacement="                pass",
        target=_T, keyword="rotated_page",
    ),
    # 2. unruled data sheets
    Mutation(
        id="M1542", phase=98,
        description="unruled data sheet not read as rows: values become clause headings",
        path=_CH,
        anchor="    paired = _paired_run(lines, i)\n    if paired[0]:\n        return paired",
        replacement="    pass",
        target=_T, keyword="unruled_data_sheet",
        tags=("critical",),
    ),
    Mutation(
        id="M1543", phase=98,
        description="a stack of split-line headings is swallowed as data-sheet rows",
        path=_CH,
        anchor="        if all(a < b for a, b in zip(keys, keys[1:])):\n            return [], 0",
        replacement="        pass",
        target=_T, keyword="stack_of_split_line_headings",
    ),
    # 3. contents-page evidence
    Mutation(
        id="M1544", phase=98,
        description="'text number' shape alone makes a contents page (data sheet excluded)",
        path=_CH,
        anchor="            and _contents_evidence(toc, page_no, total_pages)):",
        replacement="            ):",
        target=_T, keyword="tab_aligned_data_sheet",
        tags=("critical",),
    ),
    Mutation(
        id="M1545", phase=98,
        description="dot leaders are not contents evidence",
        path=_CH,
        anchor="    if sum(1 for line in toc if _DOT_LEADER.search(line)) >= len(toc) * 0.5:",
        replacement="    if False:",
        target=_T, keyword="dot_leaders",
    ),
    # 4. short-document running lines
    Mutation(
        id="M1546", phase=98,
        description="a 2-4 page document has no running lines: its page header is read as text",
        path=_CH,
        anchor="        return _short_document_running_lines(pages)",
        replacement="        return set()",
        target=_T, keyword="two_page_standard_header",
    ),
    Mutation(
        id="M1547", phase=98,
        description="short document: any line repeated in shape at the edge is furniture",
        path=_CH,
        anchor="        if tracks_page:\n            found.add(norm)",
        replacement="        found.add(norm)",
        target=_T, keyword="without_a_page_number",
    ),
    # 5. quality gate
    Mutation(
        id="M1548", phase=98,
        description="rpm / kW / kV / m3/h / Hz are not measured-value units",
        path=_Q,
        anchor='rpm\\b|kW\\b|kV\\b|m3/h(?:r)?\\b|m³/h(?:r)?\\b|Hz\\b)"',
        replacement='NOUNIT)"',
        target=_T, keyword="rotating_equipment_units",
    ),
    Mutation(
        id="M1549", phase=98,
        description="a line of equipment tags is dropped as debris",
        path=_Q,
        anchor='    if tag_list(cleaned):\n        return {"ok": True',
        replacement='    if False:\n        return {"ok": True',
        target=_T, keyword="equipment_tags",
    ),
    # 6. OCR merge
    Mutation(
        id="M1550", phase=98,
        description="OCR merge sorts row then column: a two-column page is interleaved",
        path=_OCR,
        anchor='    return "\\n".join(_reading_order(items)), len(added)',
        replacement=('    return "\\n".join(t for _, _, t in sorted(items, key=lambda it: '
                     '(round(it[0] / 6.0), it[1]))), len(added)'),
        target=_T, keyword="two_column_page or bucket_edge",
        tags=("critical",),
    ),
    Mutation(
        id="M1551", phase=98,
        description="column split ignores line length: a label/value sheet is read column-wise",
        path=_OCR,
        anchor="_MIN_COLUMN_WORDS = 4",
        replacement="_MIN_COLUMN_WORDS = 0",
        target=_T, keyword="label_value_sheet",
    ),
    Mutation(
        id="M1552", phase=98,
        description="rows grouped by fixed 6-pixel buckets: one visual row split at an edge",
        path=_OCR,
        anchor="        if anchor is None or it[0] - anchor > _ROW_TOLERANCE:",
        replacement="        if anchor is None or round(it[0] / 6.0) != round(anchor / 6.0):",
        target=_T, keyword="bucket_edge",
    ),
    Mutation(
        id="M1553", phase=98,
        description="every recognised line compared with every text-layer line (quadratic)",
        path=_OCR,
        anchor="        candidates = [m for _, m in native[lo:hi]]",
        replacement="        candidates = [m for _, m in native]",
        target=_T, keyword="only_with_lines_near_it",
    ),
)
