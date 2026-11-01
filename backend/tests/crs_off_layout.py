"""#1503: the switch-off workbook's full layout on a small invented fixture,
as `crs_export` of origin/main produced it. Used by test_1503 and by the
one-off dump that wrote `crs_off_layout.json` from main's code."""

from __future__ import annotations

import io

import openpyxl

from app import crs_export

STANDARDS = [
    {
        "standard": "SAES-A-1",
        "status": "Applied",
        "method": "m",
        "reason": "r",
        "evidence": "page 1",
    },
    {
        "standard": "SAES-B-1",
        "status": "Considered, not applied",
        "method": "m",
        "reason": "r",
        "evidence": "",
    },
    {
        "standard": "IEC 61511",
        "status": "Not in your library - upload required",
        "method": "",
        "reason": "",
        "evidence": "",
    },
]
NOTES = [
    {
        "note": "Standard not in your library - upload required",
        "standard": "IEC 61511",
        "count": None,
        "detail": "d",
    },
    {"note": "Not checked", "standard": "", "count": 2, "detail": "x"},
]
META = {
    "review_run_id": "run-1",
    "company_name": "Co",
    "project": "Proj",
    "recommended_code": "2",
    "recommended_code_reason": "reason",
    "incomplete_notice": "notice",
    "applicable_standards": STANDARDS,
    "review_notes": NOTES,
}


def rows():
    base = {
        "document_name": "DS-1.pdf",
        "comment_by": "AI Review",
        "row_kind": "datasheet_check",
        "engineer_confirmed": True,
        "priority": 3,
        "reasoning": "Read: Set pressure = 12 (p.2).",
        "rule_trust": "automatic rule not yet proven",
        "ai_review_comment": "AI wording",
    }
    return [
        {
            **base,
            "page_section": "p.2 - Set pressure",
            "comment": "Set pressure is above the limit.",
            "standard_reference": "SAES-J-600 4.1.2 (p.5)",
        },
        {
            **base,
            "page_section": "",
            "comment": "Second\nline of a comment " * 5,
            "priority": 1,
            "row_kind": "non_compliant",
            "standard_reference": "",
        },
        {
            **base,
            "page_section": "Not read from the datasheet (5 pages) - Cdtp",
            "comment": "Third.",
            "priority": None,
            "standard_reference": "API 520-I 4.2.3",
        },
    ]


def _cell(c):
    return [
        c.coordinate,
        c.value,
        c.alignment.horizontal,
        c.alignment.vertical,
        bool(c.alignment.wrap_text),
        bool(c.font.bold),
        c.font.size,
        c.font.name,
        c.fill.fgColor.rgb if c.fill.fill_type else None,
        c.border.left.style,
        c.data_type,
    ]


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
            "cells": [_cell(c) for r in ws.iter_rows(max_row=16) for c in r],
            "max": [ws.max_row, ws.max_column],
        }
    return out


def build_all(extra: dict | None = None) -> dict:
    return {
        copy: layout(
            crs_export.build_crs(rows(), {**META, **(extra or {}), "copy": copy})
        )
        for copy in ("internal", "issue")
    }
