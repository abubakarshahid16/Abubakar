"""Mutations of the office / scanned datasheet inputs (DATASHEET_OFFICE_INPUT).

`backend/app/datasheet_inputs.py` and its seams in `upload.py`, `extract.py`
and `datasheets.py`. Every one must be DETECTED by
`backend/tests/test_datasheet_inputs.py`.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_datasheet_inputs.py"
_DI = APP / "datasheet_inputs.py"


def _m(num: int, description: str, path, anchor: str, replacement: str,
       keyword: str) -> Mutation:
    return Mutation(id=f"M{num}", phase=num, description=description, path=path,
                    anchor=anchor, replacement=replacement, target=_T,
                    keyword=keyword, tags=("datasheet", "inputs"))


MUTATIONS: tuple[Mutation, ...] = (
    _m(1700, "the rules reader never reads an office file's rows",
       APP / "datasheets.py",
       "        return datasheet_inputs.pairs_for_page(stored_path, page_no)",
       "        return []",
       "xlsx_rows_become_facts or docx_table_becomes_facts or whole_pipeline"),
    _m(1701, "a merged range spanning rows labels only its first row", _DI,
       '                            text = top_left.get(source, "")',
       '                            text = ""',
       "merged_cells_label_every_row"),
    _m(1702, "formulas are read as their text, not their cached value", _DI,
       "openpyxl.load_workbook(path, read_only=True, data_only=True,",
       "openpyxl.load_workbook(path, read_only=True, data_only=False,",
       "formula_cells_are_never_evaluated"),
    _m(1703, "hidden sheets are read like visible ones", _DI,
       '                if getattr(ws, "sheet_state", "visible") != "visible":',
       '                if getattr(ws, "sheet_state", "visible") == "never":',
       "hidden_sheet_is_skipped"),
    _m(1704, "Word tables are dropped", _DI,
       "            pages_rows[-1].extend(_table_rows(block, notes))",
       "            pages_rows[-1].extend([])",
       "docx_table_becomes_facts"),
    _m(1705, "a DOCTYPE outside word/document.xml is not refused", _DI,
       "                if _DOCTYPE.search(tail + block):",
       "                if False:",
       "doctype_in_any_xml_part"),
    _m(1706, "the document-part parser accepts a DOCTYPE", _DI,
       "    if _DOCTYPE.search(data):",
       "    if False:",
       "document_part_parser_refuses_a_doctype"),
    _m(1707, "a zip's declared unpacked size is not bounded", _DI,
       "    if declared > MAX_UNCOMPRESSED_BYTES:",
       "    if False:",
       "oversized_zip_is_refused"),
    _m(1708, "a .docx upload's declared unpacked size is not bounded",
       APP / "upload.py",
       "    if declared > MAX_XLSX_UNCOMPRESSED_BYTES:\n"
       '        raise UploadError("not_docx",',
       "    if False:\n"
       '        raise UploadError("not_docx",',
       "docx_upload_bomb_is_refused"),
    _m(1709, "table-shaped OCR lines are never read, even with the flag on",
       APP / "datasheets.py",
       "    table_lines = bool(settings.datasheet_office_input)",
       "    table_lines = False",
       "scanned_table_line_becomes_a_low_confidence"),
    _m(1710, "table-shaped OCR lines are read with the flag OFF",
       APP / "datasheets.py",
       "    table_lines = bool(settings.datasheet_office_input)",
       "    table_lines = True",
       "flag_off_ocr_table_lines"),
    _m(1711, "a .docx is accepted with the flag OFF", APP / "upload.py",
       "        if (kind == KIND_XLSX and settings.datasheet_office_input\n"
       "                and is_docx(temp_path)):",
       "        if (kind == KIND_XLSX\n"
       "                and is_docx(temp_path)):",
       "flag_off_docx_upload_is_refused"),
    _m(1712, "a workbook is indexed with the flag OFF", APP / "upload.py",
       "    indexed = kind == KIND_PDF or bool(settings.datasheet_office_input)",
       "    indexed = True",
       "flag_off_xlsx_is_stored_not_indexed"),
    _m(1713, "office facts are recorded as 'extracted', not by their source",
       APP / "datasheets.py",
       '    if extraction_method == "extracted" and _OFFICE_METHOD.get() is not None:',
       "    if False:",
       "xlsx_rows_become_facts or docx_table_becomes_facts"),
    _m(1714, "the extract stage reads an office file with PyMuPDF",
       APP / "extract.py",
       "    office_rows = _office_rows(pdf_path) if settings.datasheet_office_input else None",
       "    office_rows = None",
       "extract_stage_writes_office_pages or whole_pipeline"),
    _m(1715, "an office file's condition is left to PyMuPDF",
       APP / "datasheets.py",
       "        slug, why = datasheet_inputs.office_condition(stored_path)",
       '        slug, why = None, ""',
       "docx_with_a_doctype_is_refused"),
    _m(1716, "a scanned PDF page's stored OCR text is not used", _DI,
       "    if document_id is not None:\n        from .db import connect",
       "    if False:\n        from .db import connect",
       "scanned_pdf_page_reads_as_ocr_text"),
    _m(1717, "a sheet is read past the row limit", _DI,
       "                    if row_no > MAX_SHEET_ROWS:",
       "                    if False:",
       "past_the_row_limit"),
    _m(1718, "office rows are not stored as the page's table, so the chunker "
             "drops them", APP / "extract.py",
       "                     datasheet_inputs.tables_json(p, text)))",
       "                     None))",
       "whole_pipeline"),
    _m(1719, "a vertically merged Word cell is not carried down", _DI,
       '                text = above.get(grid_col, "")',
       '                text = ""',
       "keeps_document_order_and_vertical_merges"),
)
