"""Owner 3 Nov 11:40 (b), behind CRS_COMPLIANCE_LIST_ENABLED: a value the sheet gives, checked only by a DRAFT rule and
with nothing found, writes NO CRS row. It goes to the internal-only sheet "Compliance list" with the status
"No issue found (draft rule)". The finding itself is untouched; this only decides which sheet shows it.

A draft rule is one no person approved: its label is `UNPROVEN`, or it is a safety-field Pass nobody ticked whose
label is not an approved rule's. A rule an owner or engineer approved decides in the CRS as before. A value that was
not read is not here: it stays a row. Nothing here compares a number or names a layout (rule 13). The label words are
strings so the CRS mapping can ask without importing the trust module; a test holds them to `rule_trust`.
"""

from __future__ import annotations

from .config import settings

SHEET = "Compliance list"
COLUMNS = (
    "Page",
    "Field",
    "Value read",
    "Standard and clause",
    "Status",
    "What the draft rule said",
)
STATUS = "No issue found (draft rule)"
UNPROVEN = "UNPROVEN"
#: Labels of a rule a person approved or confirmed; a finding with one of these is never listed here.
PERSON_LABELS = (
    "OWNER_APPROVED",
    "ENGINEER_APPROVED",
    "OWNER_NOTE_CONTEXT",
    "ENGINEER_CONFIRMED",
)
_HELD, _PASS = "NEEDS_ENGINEER_REVIEW", "COMPLIANT"


def enabled() -> bool:
    return bool(settings.crs_compliance_list_enabled)


def _value_given(finding: dict) -> bool:
    return bool(str(finding.get("contractor_evidence_text") or "").strip())


def is_listed(finding: dict) -> bool:
    """Switch on, a value read, nothing found by a draft rule, no person's decision on it."""
    if (
        not enabled()
        or finding.get("confirmed_by")
        or finding.get("approval_status") == "rejected"
    ):
        return False
    if finding.get("trust_label") in PERSON_LABELS or not _value_given(finding):
        return False
    status = finding.get("compliance_status")
    held_pass = (
        status == _HELD
        and finding.get("rule_said") == _PASS
        and finding.get("trust_label") == UNPROVEN
    )
    unticked_pass = status == _PASS and bool(finding.get("show_for_engineer_tick"))
    return held_pass or unticked_pass


def sheet_rows(findings: list[dict]) -> list[tuple]:
    """One line per listed finding: page, field, value read, standard and clause, status, the rule's words."""
    out = []
    for f in findings:
        if not is_listed(f):
            continue
        where = " ".join(
            x for x in (f.get("standard_name"), f.get("standard_clause")) if x
        )
        out.append(
            (
                f.get("contractor_page"),
                f.get("contractor_section") or "",
                str(f.get("contractor_evidence_text") or ""),
                where,
                STATUS,
                str(f.get("finding") or ""),
            )
        )
    return out


_SQL = (
    "SELECT f.*, d.filename AS standard_name FROM review_findings f"
    " LEFT JOIN documents d ON d.id = f.standard_document_id WHERE f.review_run_id = ? ORDER BY f.rowid"
)


def for_run(run_id: str | None) -> list[tuple]:
    """The listed lines of one review run, read from its stored findings. Nothing when the switch is off."""
    if not enabled() or not run_id:
        return []
    from .db import connect

    cursor = connect().cursor()
    cursor.row_factory = lambda cur, row: {
        d[0]: v for d, v in zip(cur.description, row, strict=True)
    }
    found = cursor.execute(_SQL, (run_id,)).fetchall()
    return sheet_rows(found)


def write_sheet(wb, run_id: str | None, write) -> None:
    """The internal-only sheet; no sheet at all when nothing is listed or the switch is off."""
    lines = for_run(run_id)
    if not lines:
        return
    from openpyxl.styles import Alignment, Font

    sheet = wb.create_sheet(SHEET)
    for col, header in enumerate(COLUMNS, start=1):
        write(sheet, 1, col, header).font = Font(bold=True)
    for r, line in enumerate(lines, start=2):
        for col, value in enumerate(line, start=1):
            write(sheet, r, col, value).alignment = Alignment(
                wrap_text=True, vertical="top"
            )
    for col, width in zip("ABCDEF", (8, 30, 34, 30, 28, 70), strict=True):
        sheet.column_dimensions[col].width = width
