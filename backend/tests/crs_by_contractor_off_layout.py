"""#1738: the switch-off workbook's full layout (values and styles, wrap and row heights included) on an
invented fixture, as `crs_export` of origin/main produced it: deferred-value rows from `crs_mapping`, numbered
rows, a contractor reply of two lines, a tall comment. `crs_by_contractor_off_layout.json` was written once from
main's code by `build_all`; the test compares the head's workbook with it. Uses only what main has."""

from __future__ import annotations

import io

import openpyxl

from app import crs_export
from app.crs_mapping import build_crs_rows
from tests.crs_off_layout import _cell


def _finding(n: int, **over) -> dict:
    base = {
        "id": f"fid-{n}",
        "origin": "datasheet_check",
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "hold_reason_code": "deferred_marker",
        "requirement_source_text": f"DATASHEET CHECK INV-{n}: invented item {n} is stated",
        "standard_clause": f"9.{n}",
        "crs_field_label": f"Invented quantity {n}",
        "contractor_section": f"Invented quantity {n}",
        "contractor_evidence_text": f"{n}0 zorbs",
        "contractor_page": n,
        "equipment_tag": "Q-7" if n % 2 else "Q-8",
        "document_id": "doc-inv",
        "approval_status": "accepted",
        "approved_by": "user-inv",
        "finding": f"Invented finding {n}",
    }
    return {**base, **over}


def rows() -> list[dict]:
    """Mapped rows (three deferred, one breach), numbered; one carries a reply of two lines; plus a tall row."""
    findings = [
        _finding(1),
        _finding(2),
        _finding(3),
        _finding(
            9,
            compliance_status="NON_COMPLIANT",
            hold_reason_code=None,
            crs_field_label="Invented limit",
            contractor_section="Invented limit",
        ),
    ]
    mapped = build_crs_rows(findings, [], "Invented sheet.pdf")
    out = [
        {
            **r,
            "engineer_confirmed": True,
            "crs_ref": f"CRS-INV-{i:03d}",
            "crs_status": "Open",
        }
        for i, r in enumerate(mapped, 1)
    ]
    out[1]["crs_response"] = (
        "Clarification needed - invented first line\ninvented second line"
    )
    tall = "\n".join(f"Invented line {n}" for n in range(60))
    out.append(
        {
            **out[0],
            "finding_id": "fid-tall",
            "finding_ids": ["fid-tall"],
            "comment": tall,
        }
    )
    return out


def layout(data: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    out = {"sheets": wb.sheetnames}
    for ws in wb.worksheets:
        out[ws.title] = {
            "widths": {k: v.width for k, v in sorted(ws.column_dimensions.items())},
            "merged": sorted(str(m) for m in ws.merged_cells.ranges),
            "heights": {
                str(k): v.height
                for k, v in sorted(ws.row_dimensions.items())
                if v.height
            },
            "cells": [_cell(c) for r in ws.iter_rows() for c in r],
            "max": [ws.max_row, ws.max_column],
        }
    return out


def build_all() -> dict:
    """{"<copy>-quality-<on|off>": layout} for both copies, export quality off and on."""
    return {
        f"{copy}-quality-{'on' if quality else 'off'}": layout(
            crs_export.build_crs(
                [dict(r) for r in rows()],
                {"review_run_id": "run-inv", "copy": copy, "export_quality": quality},
            )
        )
        for copy in ("internal", "issue")
        for quality in (False, True)
    }
