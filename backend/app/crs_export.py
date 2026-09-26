"""CRS (Comment Resolution Sheet) generator - client CRS format.

Built against the client's real template (CRS - Form of Agreement_2028 1.xlsx,
sheet 'FOA and SCH H'): seven columns from row 8, header block rows 1-7 with
the measured merges and widths. Values only, no formulas.

TWO RENDERINGS, ONE CONTENT. `build_crs_view` decides what the sheet SAYS -
the header block, the column headers, one entry per data row, the recommended
review code. `build_crs` draws that view into a workbook and returns its
bytes; the API's preview route serves the same view as JSON. The workbook is
rendered FROM the view rather than beside it, so there is no second path that
could decide something different: a preview that disagreed with the file the
client receives would be worse than no preview at all.

No database imports on purpose: the caller passes plain dicts, so this module
is testable without the app and reusable by any export path. Wiring findings
into `findings` rows is the integration task's job, not this module's.

Pre-built and pre-tested by Cowork (9 standalone tests) against the client
template; delivered on branch cowork/phase-7-crs-export for integration.
"""
import hashlib
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ARIAL = "Arial"
THIN = Side(style="thin")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

#: ISSUE #165, CRITERION 4. A row's `row_kind` (from `crs_mapping`, never
#: printed) picks its fill, so "already flagged as a defect", "needs a
#: human's judgement", "no value stated" and "checked in another document"
#: read differently at a glance - not just by the words in the comment cell.
#: Pastel, not saturated: the client's template is a working document an
#: engineer reads for hours, not a warning label. A `row_kind` with no entry
#: here (a row `crs_mapping` never tags, or a caller's raw dict from before
#: #165) gets no fill at all rather than a guessed one.
ROW_FILLS = {
    "non_compliant": PatternFill("solid", fgColor="FFF5D6D6"),
    "needs_engineer_review": PatternFill("solid", fgColor="FFFCF3CF"),
    "missing_information": PatternFill("solid", fgColor="FFEAEDED"),
    "requires_other_document": PatternFill("solid", fgColor="FFD6EAF8"),
    "missing_reference": PatternFill("solid", fgColor="FFEAEDED"),
    # B3: pages the system has not read into fields - engineer work, pale
    # amber like needs_engineer_review, never grey like "missing".
    "pages_not_readable": PatternFill("solid", fgColor="FFFDF2E9"),
}
HEADERS = ["Item No", "Document Name", "Page No./Section", "COMPANY Comments",
           "Comment By", "Contractor's Response", "Final Resolution"]
WIDTHS = {"A": 11.7, "B": 25.8, "C": 21.8, "D": 93.5, "E": 23.0, "F": 25.0,
          "G": 15.0}

def default_company() -> str:
    """Printed on row 1 when the caller names no company.

    Read from `settings.crs_company_name` (env CRS_COMPANY_NAME) at call time,
    so the client's company name lives in the operator's `.env` and never in
    git. Empty when unset, and empty prints nothing rather than a guess about
    who issued the sheet."""
    from .config import settings
    return settings.crs_company_name or ""

#: Row 2, and not a caller's to change: this IS what the document is.
SUBTITLE = "COMMENT RESOLUTION SHEET"
#: B5: the sheet listing the standards the review applied, and why.
STANDARDS_SHEET = "Applicable standards"
STANDARDS_COLUMNS = ("Standard", "Status", "Method", "Reason", "Evidence")
#: The status words that sheet prints.
STATUS_APPLIED = "Applied"
STATUS_CONSIDERED = "Considered, not applied"

#: Rows 3-7 of the header block: the label exactly as the template prints it,
#: and the meta key it takes its value from. Declared once and read by both
#: renderings, so a label cannot drift in the preview while the workbook keeps
#: the old one.
HEADER_FIELDS = (
    ("COMPANY Transmittal No.:", "company_transmittal"),
    ("CONTRACTOR  Transmittal No.:", "contractor_transmittal"),
    # The submittal's OWN number, from `documents.transmittal_number`. A
    # THIRD thing, beside the two transmittal numbers above and never a reuse
    # of either: those name the covering transmittals, this names the document
    # being reviewed. Blank when the upload carried none - see the rule below.
    ("Submittal No.:", "submittal_number"),
    ("Document Title:", "document_title"),
    ("Date Issued:", "date_issued"),
    ("Date Responded", "date_responded"),
)

#: Row 8 in the client's own template, and one row lower for every header
#: field added since. Derived, never hardcoded, so the table cannot land on
#: top of the header block when a field is added: both renderings and the
#: tests read the geometry from here.
COLUMN_HEADER_ROW = 3 + len(HEADER_FIELDS)
FIRST_DATA_ROW = COLUMN_HEADER_ROW + 1

#: Printed beside the code on the summary row. One definition, read by
#: both renderings, so the workbook and the preview name it identically.
RECOMMENDED_CODE_LABEL = "Recommended Review Code:"

#: The two columns that belong to the contractor. They are carried as empty
#: strings rather than left out, because the sheet has seven columns whether
#: or not anyone has answered yet - a reader must see the space they will fill.
CONTRACTOR_COLUMNS = ("contractor_response", "final_resolution")

#: Prefix of the per-row system-generated number the client asked for, and
#: the label it prints under. "Ref:" reads as what it is - a handle to quote
#: back - where a bare code in the comment would read as part of the comment.
ROW_REF_PREFIX = "RF-"
ROW_REF_LABEL = "Ref"

#: Hex digits of the digest kept. Six gives 16.7 million references, so two
#: DIFFERENT rows of one sheet colliding is remote; the loop below still
#: handles it rather than trusting the arithmetic.
ROW_REF_DIGITS = 6


def row_reference(review_run_id: str, finding: dict, salt: int = 0) -> str:
    """The stable, system-generated number for one CRS row.

    RE-EXPORTING A REVIEW MUST NOT RENUMBER IT. A contractor who answers item
    RF-4A2C1B has to find RF-4A2C1B on the next sheet, so this is a digest of
    WHAT THE ROW IS - the run it belongs to, the finding's own database id
    where it has one, and the text the row prints - and never of where the row
    happened to land. Row position, a uuid4 and a timestamp would all give the
    contractor a new number for the same comment every time.

    It DOES change when the finding itself changes, which is the other half of
    the bargain: a row whose requirement or evidence has been rewritten is a
    different comment, and quoting it back under the old number would attach
    the contractor's answer to text they never read. `comment_by` is left out
    of the key on purpose - an engineer confirming a finding changes who says
    it, not what it says, and must not renumber it.

    `salt` exists only for the collision loop in `build_crs_view`; callers
    leave it alone.
    """
    key = "\x1f".join((
        str(review_run_id or ""),
        str(finding.get("finding_id") or ""),
        str(finding.get("document_name") or ""),
        str(finding.get("page_section") or ""),
        str(finding.get("comment") or ""),
        str(salt) if salt else "",
    ))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return ROW_REF_PREFIX + digest[:ROW_REF_DIGITS].upper()



def build_crs_view(findings: list[dict], meta: dict) -> dict:
    """What a CRS says, with nothing in it about how it is drawn.

    THE SINGLE DEFINITION OF THE CONTENT. `build_crs` renders this into the
    client's template and the preview route serves it as JSON, so the file
    that leaves the building and the table on screen cannot disagree about a
    row, a label or the recommended code.

    findings: dicts with document_name, page_section, comment, comment_by,
    and `finding_id` where the row came from a stored finding - the reference
    minting reads it, and a row without one is still numbered from its text.
    meta: the keys `build_crs` documents, all optional.

    Returned shape:

      title                    row 1, company and project
      subtitle                 row 2, the document's own name
      header                   rows 3-7 as {label, value} pairs, in order
      columns                  the seven column headers, row 8
      rows                     one per finding, item_no assigned 1..N HERE,
                               each carrying the stable `row_ref` that its
                               comment's first line prints
      recommended_code         "" when the caller supplies none
      recommended_code_label   the label the summary row prints
      recommended_code_reason  "" when there is none

    The response and resolution columns are ALWAYS empty - they belong to the
    contractor, and pre-filling them would put words in their mouth.
    """
    company = meta.get("company_name", default_company())
    project = meta.get("project", "")

    # Item numbers are assigned HERE, not taken from the caller, so they are
    # always 1..N with no gaps whatever the caller sends - and the preview
    # numbers the rows the way the workbook does, not the way a browser
    # happens to iterate.
    # The per-row system-generated number. Minted HERE, in the one builder
    # both renderings read, so the .xlsx the client receives and the preview
    # on screen quote the same reference for the same comment - and so a
    # re-export of this run quotes it again rather than issuing a new one.
    run_id = meta.get("review_run_id", "")

    rows = []
    seen: set[str] = set()
    for n, finding in enumerate(findings, start=1):
        comment = str(finding.get("comment", ""))
        ref = row_reference(run_id, finding)
        # Two DIFFERENT rows landing on one reference would let a contractor
        # answer the wrong comment. Re-mint with a salt until the sheet's
        # references are distinct; the result is still decided by the rows'
        # own content, since the order they arrive in is itself content.
        salt = 0
        while ref in seen:
            salt += 1
            ref = row_reference(run_id, finding, salt)
        seen.add(ref)
        rows.append({
            "item_no": n,
            "row_ref": ref,
            "document_name": finding.get("document_name", ""),
            "page_section": finding.get("page_section", ""),
            # The reference is the comment's FIRST LINE rather than an eighth
            # column: the client's template has seven columns, and widening it
            # without their sign-off is what the project's own audits warned
            # against. Same shape as the Requirement/Submitted/Equipment lines
            # `crs_mapping._comment_text` already writes.
            "comment": f"{ROW_REF_LABEL}: {ref}" + (f"\n{comment}" if comment
                                                    else ""),
            "comment_by": finding.get("comment_by", ""),
            "contractor_response": "",
            "final_resolution": "",
            # NEVER PRINTED - read by `build_crs` alone to pick a row's fill.
            # Carried through the view (not read straight off `findings` by
            # the renderer) so the preview route and the workbook agree on
            # what kind a row is, same as every other field here.
            "row_kind": finding.get("row_kind", ""),
        })

    return {
        # Absent parts print nothing: an unset company must not leave the
        # title starting with a blank line.
        "title": "\n ".join(p for p in (company, project) if p).rstrip(),
        "subtitle": SUBTITLE,
        # A missing value renders as NOTHING, never as "None": a CRS carrying
        # a plausible-looking transmittal number lies about its own provenance.
        "header": [{"label": label, "value": meta.get(key, "") or ""}
                   for label, key in HEADER_FIELDS],
        "columns": list(HEADERS),
        "rows": rows,
        "recommended_code": meta.get("recommended_code") or "",
        "recommended_code_label": RECOMMENDED_CODE_LABEL,
        "recommended_code_reason": meta.get("recommended_code_reason") or "",
        # B5: WHICH STANDARDS THE REVIEW APPLIED, AND WHY - each with its
        # method, reason and evidence, plus the ones considered and not
        # included and the cited ones not held (MISSING_LOCALLY). Drawn on a
        # sheet of its own so the client's seven-column comment sheet is
        # unchanged.
        "applicable_standards": [
            {"standard": str(s.get("standard") or ""),
             "status": str(s.get("status") or ""),
             "method": str(s.get("method") or ""),
             "reason": str(s.get("reason") or ""),
             "evidence": str(s.get("evidence") or "")}
            for s in (meta.get("applicable_standards") or [])],
    }


def build_crs(findings: list[dict], meta: dict) -> bytes:
    """Render a CRS workbook and return its bytes.

    findings: dicts with document_name, page_section, comment, comment_by.
    The response and resolution columns are ALWAYS left empty - they belong
    to the contractor, and pre-filling them would put words in their mouth.

    meta keys (all optional strings; a missing one renders as NOTHING, never
    as "None"): company_name, project, document_title, company_transmittal,
    contractor_transmittal, submittal_number, date_issued, date_responded.
    `review_run_id` is meta too, and is not printed anywhere: it is half the
    key the per-row reference is minted from.

    EVERY VALUE COMES FROM `build_crs_view`. This function decides fonts,
    widths, merges and row heights - never what the sheet says.
    """
    view = build_crs_view(findings, meta)

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
    put(1, 1, view["title"], bold=True, size=12, center=True, wrap=True)
    ws.row_dimensions[1].height = 30
    ws.merge_cells("A2:G2")
    put(2, 1, view["subtitle"], bold=True, size=12, center=True)
    for offset, field in enumerate(view["header"]):
        row = 3 + offset
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
        put(row, 1, field["label"], bold=True)
        put(row, 3, field["value"])

    # Column headers, directly under the header block.
    for i, header in enumerate(view["columns"], start=1):
        put(COLUMN_HEADER_ROW, i, header,
            bold=True, center=True, wrap=True).border = BOX

    # Data rows, from the row after the column headers.
    for entry in view["rows"]:
        row = COLUMN_HEADER_ROW + entry["item_no"]
        comment = entry["comment"]
        values = [entry["item_no"], entry["document_name"],
                  entry["page_section"], comment, entry["comment_by"],
                  entry["contractor_response"], entry["final_resolution"]]
        fill = ROW_FILLS.get(entry.get("row_kind") or "")
        for i, value in enumerate(values, start=1):
            cell = put(row, i, value, wrap=(i == 4), center=(i == 1))
            cell.border = BOX
            if fill is not None:
                cell.fill = fill
        ws.row_dimensions[row].height = max(
            15, 13 * (comment.count("\n") + len(comment) // 90 + 1))

    # Recommended review code, when the caller supplies one: a bold merged
    # summary row two rows below the table, so the seven-column layout the
    # client's template defines is untouched. The reason renders beside it
    # verbatim - a code with no reason is an opinion, not a review.
    code = view["recommended_code"]
    if code:
        row = COLUMN_HEADER_ROW + len(view["rows"]) + 2
        ws.merge_cells(start_row=row, start_column=1, end_row=row,
                       end_column=2)
        ws.merge_cells(start_row=row, start_column=3, end_row=row,
                       end_column=7)
        put(row, 1, view["recommended_code_label"], bold=True)
        reason = view["recommended_code_reason"]
        put(row, 3, f"{code}" + (f" - {reason}" if reason else ""),
            bold=True, wrap=True)
        ws.row_dimensions[row].height = max(15, 13 * (len(reason) // 90 + 1))

    # B5: the applied standards and their reasons, on their own sheet.
    standards_sheet = wb.create_sheet(STANDARDS_SHEET)
    for col, header in enumerate(STANDARDS_COLUMNS, start=1):
        cell = standards_sheet.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
    for r, entry in enumerate(view["applicable_standards"], start=2):
        for col, key in enumerate(("standard", "status", "method", "reason", "evidence"),
                                  start=1):
            standards_sheet.cell(row=r, column=col, value=entry[key]).alignment = \
                Alignment(wrap_text=True, vertical="top")
    for col, width in zip("ABCDE", (38, 22, 16, 70, 60)):
        standards_sheet.column_dimensions[col].width = width

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
