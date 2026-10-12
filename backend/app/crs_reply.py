"""Read a contractor's returned Comment Resolution Sheet.

The contractor fills "Contractor's Response" on the sheet we issued and sends
it back. This reads that workbook - pure, no database - and returns each row's
Item No and response text. Matching the Item No to a stored comment, and
storing the reply, is `crs_numbers`' job and the route's.

FORGIVING ABOUT LAYOUT, STRICT ABOUT MEANING. The header row is FOUND (the
first row, within the first 40, holding both "Item No" and a response column),
so a contractor who inserts a logo row or deletes our title still imports.
But a row is only ever matched by its permanent number: a row whose Item No is
not a "CRS-...-NNN" number is reported as unmatched, never paired by position.

UNTRUSTED INPUT. Only .xlsx, size-capped by the caller, opened read-only with
formulas NOT evaluated (`data_only=True` reads the cached value a formula
left, never runs it). Nothing here executes content from the file.
"""
from __future__ import annotations

import io
import re

#: Hard limits on what one import may read.
MAX_ROWS = 5000
_HEADER_SCAN_ROWS = 40


class ReplySheetError(ValueError):
    """The file is not a CRS we can read. The message is safe to show."""


def _fold(value) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").lower())


_ITEM_HEADERS = {"itemno", "itemnumber", "item", "sno", "no", "commentno", "commentid"}
_RESPONSE_HEADERS = {"contractorsresponse", "contractorresponse", "contractorsreply",
                     "contractorreply", "response", "vendorresponse", "vendorreply"}


def read_replies(data: bytes) -> list[dict]:
    """[{"row": sheet row number, "item": Item No as text, "response": text}]
    for every data row that has an Item No. Raises ReplySheetError when the
    file is not a workbook or has no recognisable header."""
    import openpyxl

    from .upload import UploadError, validate_xlsx

    # THE UPLOAD LIMITS, BEFORE openpyxl DECOMPRESSES ANYTHING. The 10 MB cap
    # on the request is a cap on COMPRESSED bytes; a zip that declares
    # gigabytes of XML fits in it. `validate_xlsx` reads only the central
    # directory and refuses too many parts, too large a declared expansion,
    # macros and non-workbooks (audit 2026-09-30).
    try:
        validate_xlsx(io.BytesIO(data))
    except UploadError as exc:
        # `not_pdf` is the upload route's word for "not a zip at all"; here
        # the only thing expected was a workbook.
        raise ReplySheetError(
            "the file is not a readable .xlsx workbook" if exc.code == "not_pdf"
            else exc.message) from exc

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parse failure is "not a workbook"
        raise ReplySheetError("the file is not a readable .xlsx workbook") from exc
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            header_at = item_col = response_col = None
            for index, row in enumerate(rows, start=1):
                folded = [_fold(v) for v in row]
                items = [i for i, v in enumerate(folded) if v in _ITEM_HEADERS]
                responses = [i for i, v in enumerate(folded) if v in _RESPONSE_HEADERS]
                if items and responses:
                    header_at, item_col, response_col = index, items[0], responses[0]
                    break
                if index >= _HEADER_SCAN_ROWS:
                    break
            if header_at is None:
                continue
            out = []
            for number, row in enumerate(rows, start=header_at + 1):
                if number - header_at > MAX_ROWS:
                    raise ReplySheetError(f"the sheet has more than {MAX_ROWS} rows")
                cells = list(row) + [None] * (max(item_col, response_col) + 1 - len(row))
                item = str(cells[item_col] if cells[item_col] is not None else "").strip()
                if not item:
                    continue
                response = cells[response_col]
                out.append({"row": number, "item": item,
                            "response": str(response).strip() if response is not None else ""})
            return out
    finally:
        workbook.close()
    raise ReplySheetError(
        "no header row with both \"Item No\" and \"Contractor's Response\" was found")
