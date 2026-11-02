"""#805 plan change 6: what the CRS says about version 2 rules. Only with RULEBOOK_V2_REVIEW_ENABLED on.

A Pass makes no CRS row, so a rule that met on every valve would leave no trace of who stands behind it. This adds, to the
internal copy only, one row per tag for each Pass, and a Review note with the run's line and the labels. The issue copy's
rows do not change: these rows are never engineer-confirmed, and no CRS number is given to them. An unticked safety Pass
already has its own row, so it gets no second one.
"""

from __future__ import annotations

import sqlite3

from . import coverage_pair, material_reference, rule_trust
from .rulebook_v2_stated import ORIGIN

ROW_KIND = "rulebook_v2_pass"
NOTE = "Rulebook version 2"
COMMENT_BY = "Rulebook version 2, not confirmed by an engineer"


def labels_of(finding: dict) -> list[str]:
    """Every label this finding carries. A rule decided on the owner's note is an owner-approved rule too."""
    label = finding.get("trust_label")
    out = [rule_trust.TRUST_WORDS[label]] if label in rule_trust.TRUST_WORDS else []
    if material_reference.NOT_CONFIRMED in (finding.get("finding") or ""):
        out.append(material_reference.NOT_CONFIRMED)
    return out


def _findings(
    conn: sqlite3.Connection, run_id: str, allowed: frozenset[str]
) -> list[dict]:
    """Only the findings on a standard this reader may read (CLAUDE.md rule 5): a row with no standard named is not one."""
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return [
        dict(r)
        for r in cursor.execute(
            "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = ? ORDER BY equipment_tag, id",
            (run_id, ORIGIN),
        )
        if r["standard_document_id"] in allowed
    ]


def _row(finding: dict) -> dict:
    tag = finding.get("equipment_tag")
    page = finding.get("contractor_page")
    field = finding.get("contractor_section") or ""
    where = ", ".join(x for x in (f"Page {page}" if page else "", field) if x)
    text = finding.get("finding") or ""
    return {
        "document_name": "",
        "page_section": where,
        "comment": f"Meets, {tag}: {text}" if tag else f"Meets: {text}",
        "comment_by": COMMENT_BY,
        "row_kind": ROW_KIND,
        "standard_reference": finding.get("standard_clause") or "",
        "severity": "",
        "engineer_confirmed": False,
        "reasoning": finding.get("ai_rationale") or "",
        "rule_trust": "; ".join(labels_of(finding)),
    }


def part(
    meta: dict, conn: sqlite3.Connection, run_id: str, allowed: frozenset[str]
) -> dict:
    """The meta with the rows and the note added. A run with no version 2 findings: `meta` as it was."""
    findings = _findings(conn, run_id, allowed)
    pair = coverage_pair.for_run(conn, run_id)
    stated = (pair or {}).get("rulebook_v2")
    if not findings and not stated:
        return meta
    labels = sorted({w for f in findings for w in labels_of(f)})
    said = (stated or {}).get("line") or ""
    words = f"{said} Labels on these rules: {'; '.join(labels)}." if labels else said
    return {
        **meta,
        "rulebook_v2_rows": [
            _row(f)
            for f in findings
            if f.get("compliance_status") == "COMPLIANT"
            and not f.get("show_for_engineer_tick")
        ],
        "review_notes": [
            *(meta.get("review_notes") or []),
            {
                "note": NOTE,
                "standard": "",
                "count": (stated or {}).get("rules"),
                "detail": words,
            },
        ],
    }
