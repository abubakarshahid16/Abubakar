"""The engineering review report as a PDF, built under the PyMuPDF lock (order 252).

`review.render_report` reads everything first (the document, the findings, the run header) with
the lock NOT held, then hands plain values to `write`, which builds the file with it held: no
database call and no model call inside (the lock must never wait on SQLite).
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from . import export_status, pdf_flow, pdf_guard


@pdf_guard.guarded
def write(path: Path, filename: str, findings: list, run: dict, header: list, *, generated: str) -> Path:
    """The PDF itself, under the lock: pure document building, no database and no model call (the
    data was read before the lock was taken)."""
    pdf = pymupdf.open()
    flow = pdf_flow.Flow(pdf)
    flow.text("ENGINEERING SUBMITTAL REVIEW", fontsize=18, fontname="hebo", color=(0.07, 0.23, 0.32))
    flow.gap(6)
    flow.text(f"Document: {filename}", fontsize=10)
    flow.text(f"Generated: {generated}  ·  Findings: {len(findings)}", fontsize=9, color=(0.3, 0.35, 0.4))
    for line in header:
        flow.text(line, fontsize=9, fontname="hebo" if line.startswith("Run ") else "helv",
                  color=(0.7, 0.1, 0.1) if line.startswith("Run ") else (0.3, 0.35, 0.4))
    flow.gap(9)
    flow.box("AI-assisted record. A qualified engineer must review and approve before use.",
             fontsize=9, color=(0.45, 0.2, 0.02), border=(0.7, 0.32, 0.04), fill=(1, 0.97, 0.91))
    flow.gap(12)
    for index, finding in enumerate(findings, 1):
        block = (
            f"{index}. [{finding['severity'].upper()}] {finding['category'].replace('_', ' ')}\n"
            f"Requirement: {finding['requirement']}\n"
            f"Finding: {finding['finding']}\n"
            f"Required action: {finding['required_action']}\n"
            f"Discipline: {finding.get('discipline') or 'not specified'}  |  Confidence: {finding.get('confidence') or 'not recorded'}\n"
            f"Governing sources: {', '.join(finding.get('governing_sources') or []) or 'not recorded'}\n"
            f"Evidence IDs: {', '.join(finding.get('citation_ids') or []) or 'none'}\n"
            f"Owner: {finding.get('owner_user_id') or 'unassigned'}  |  Due: {finding.get('due_date') or 'not set'}\n"
            f"Response: {finding.get('response_text') or 'not provided'}\n"
            f"Disposition: {finding.get('disposition') or 'not recorded'}  |  Approval: {finding.get('approval_status') or 'pending'}\n"
            f"Status: {finding['status']}  |  Escalation level: {finding['escalation_level']}"
        )
        # The box is as tall as its wrapped text and continues on the next page
        # when it must. It was a fixed box that cut a long finding off silently,
        # then one that printed "TEXT CONTINUES - NOT SHOWN HERE" (#633).
        flow.box(block, border=(0.65, 0.72, 0.75), fill=(0.96, 0.98, 0.98))
        flow.gap(12)
    if not findings and export_status.incomplete(run):
        # A run that did not complete has no "nothing recorded": it stopped.
        flow.text(export_status.status_line(run["status"], run["reason"]) + ". Findings were not "
                  "recorded because the review did not complete, not because none were found.",
                  fontsize=10, fontname="hebo", color=(0.7, 0.1, 0.1))
    elif not findings:
        flow.text("No review findings have been recorded for this document.", fontsize=10)
        flow.text("This is NOT a statement that the document was reviewed and found acceptable.",
                  fontsize=9, fontname="hebo", color=(0.7, 0.1, 0.1))
    pdf.save(str(path))
    pdf.close()
    return path
