"""CRS (Comment Resolution Sheet) generator - KJO DORRA format.

Built against the client's real template (CRS - Form of Agreement_2028 1.xlsx,
sheet 'FOA and SCH H'): seven columns from row 8, header block rows 1-7 with
the measured merges and widths. Values only, no formulas.

No database imports on purpose: the caller passes plain dicts, so this module
is testable without the app and reusable by any export path. Wiring findings
into `findings` rows is the integration task's job, not this module's.

Pre-built and pre-tested by Cowork (9 standalone tests) against the client
template; delivered on branch cowork/phase-7-crs-export for integration.
"""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side

ARIAL = "Arial"
THIN = Side(style="thin")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
HEADERS = ["Item No", "Document Name", "Page No./Section", "COMPANY Comments",
           "Comment By", "Contractor's Response", "Final Resolution"]
WIDTHS = {"A": 11.7, "B": 25.8, "C": 21.8, "D": 93.5, "E": 23.0, "F": 25.0,
          "G": 15.0}


def build_crs(findings: list[dict], meta: dict) -> bytes:
    """Render a CRS workbook and return its bytes.

    findings: dicts with document_name, page_section, comment, comment_by.
    The response and resolution columns are ALWAYS left empty - they belong
    to the contractor, and pre-filling them would put words in their mouth.

    meta keys (all optional strings; a missing one renders as NOTHING, never
    as "None"): company_name, project, document_title, company_transmittal,
    contractor_transmittal, date_issued, date_responded.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "CRS"

    for col, width in WIDTHS.items():
        ws.column_dimensions[col].width = width

    def put(row, col, value, bold=False, size=10, center=False, wrap=False):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = Font(name=ARIAL, bold=bold, size=size)
        cell.alignment = Alignment(
            horizontal="center" if center else "left",
            vertical="top", wrap_text=wrap)
        return cell

    # Header block, rows 1-7, merges as measured from the template.
    ws.merge_cells("A1:G1")
    company = meta.get("company_name", "AL-KHAFJI JOINT OPERATIONS (KJO)")
    project = meta.get("project", "")
    put(1, 1, f"{company}\n {project}".rstrip(), bold=True, size=12,
        center=True, wrap=True)
    ws.row_dimensions[1].height = 30
    ws.merge_cells("A2:G2")
    put(2, 1, "COMMENT RESOLUTION SHEET", bold=True, size=12, center=True)
    for row, label, key in (
            (3, "COMPANY Transmittal No.:", "company_transmittal"),
            (4, "CONTRACTOR  Transmittal No.:", "contractor_transmittal"),
            (5, "Document Title:", "document_title"),
            (6, "Date Issued:", "date_issued"),
            (7, "Date Responded", "date_responded")):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
        put(row, 1, label, bold=True)
        put(row, 3, meta.get(key, "") or "")

    # Column headers, row 8.
    for i, header in enumerate(HEADERS, start=1):
        put(8, i, header, bold=True, center=True, wrap=True).border = BOX

    # Data rows from 9. Item numbers are assigned HERE, not taken from the
    # caller, so they are always 1..N with no gaps whatever the caller sends.
    for n, finding in enumerate(findings, start=1):
        row = 8 + n
        comment = str(finding.get("comment", ""))
        values = [n, finding.get("document_name", ""),
                  finding.get("page_section", ""), comment,
                  finding.get("comment_by", ""), "", ""]
        for i, value in enumerate(values, start=1):
            cell = put(row, i, value, wrap=(i == 4), center=(i == 1))
            cell.border = BOX
        ws.row_dimensions[row].height = max(
            15, 13 * (comment.count("\n") + len(comment) // 90 + 1))

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
