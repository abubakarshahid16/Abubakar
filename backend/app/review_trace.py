"""#791 part 0: the review step by step, for the engineer at the backend console.

WHY. A review is one button and a result. On 10 Oct "not a single compliant"
took hours to explain; one look at what each step produced would have shown
it. The owner asked to see every step in the `python run.py` window while a
review runs, and in a file to read later.

WHAT. `build(run, scope)` reads what the finished run STORED (facts, the page
ledger, the chosen standards, findings, the outcome, the CRS rows) and returns
ten step records - the SAME records part 1 will store per run and the app
view will show, so console, file and app can never disagree. It only reads:
a trace never changes the result. `emit(...)` writes the records, through the
named logger `review.debug`, to the console and to
`<data_dir>/debug/review-<run id>.log` (git-ignored, this machine only).

OFF BY DEFAULT. `REVIEW_DEBUG=true` turns it on; `REVIEW_DEBUG_DETAIL=true`
adds one line per checklist item and per CRS row (value, page, clause, result,
reason), so a row can be checked against the datasheet by eye. These lines
carry document values and comment text: they go to this machine's console and
file only, never to the server's normal log handlers (`propagate = False`),
GitHub or CI. A failure here never breaks a review.
"""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from .config import settings

LOGGER_NAME = "review.debug"
log = logging.getLogger(LOGGER_NAME)
log.propagate = False  # never into the server's normal log handlers

STEPS = ("READ", "CLEAN", "EQUIPMENT", "STANDARDS", "CHECKLIST",
         "RULES", "DECIDE", "COVERAGE", "CRS", "CODE")
#: Statuses as the decide step names them.
_DECISIONS = (("COMPLIANT", "meets"), ("NON_COMPLIANT", "fails"),
              ("MISSING_INFORMATION", "missing"), ("NEEDS_ENGINEER_REVIEW", "engineer"),
              ("NOT_APPLICABLE", "n/a"), ("NOT_IN_DOCUMENT_SCOPE", "other doc"))


def debug_dir() -> Path:
    return Path(settings.data_dir) / "debug"


def _step(name: str, summary: str, *, warning: str | None = None,
          counts: dict | None = None, items: list[str] | None = None) -> dict:
    return {"step": name, "summary": summary, "warning": warning,
            "counts": counts or {}, "items": items or []}


def _short(text: object, n: int = 70) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "..."


def build(review_run_id: str, scope) -> dict:
    """The ten step records of a finished run, read from what it stored."""
    from . import comparison, datasheets, page_ledger, submittal_review
    from .db import connect

    run = submittal_review.get_review_run(review_run_id,
                                          allowed_document_ids=scope.allowed_document_ids)
    if run is None:
        return {"review_run_id": review_run_id, "document": None, "steps": []}
    sub = run["submittal_document_id"]
    allowed = scope.allowed_document_ids
    doc = connect().execute("SELECT filename FROM documents WHERE id = ?", (sub,)).fetchone()
    outcome = comparison.run_outcome(review_run_id, allowed_document_ids=allowed) or {}
    facts = datasheets.list_facts(sub, allowed_document_ids=allowed)
    findings = submittal_review.list_run_findings(review_run_id, allowed_document_ids=allowed)
    steps: list[dict] = []

    # 1 READ
    pages = page_ledger.coverage(sub)
    by_page_reader = pages.get("pages_read_only_by_page_reader") or []
    fields = {f.get("field_label") or f.get("field_name") for f in facts}
    blank = sum(1 for f in facts if f.get("is_blank"))
    steps.append(_step(
        "READ",
        f"pages {pages.get('pages_total')} | read into fields {len(pages.get('fact_pages') or [])}"
        + (f", backup reader only {len(by_page_reader)} (p{', p'.join(map(str, by_page_reader))})"
           if by_page_reader else "")
        + f" | values {len(facts)} from {len(fields)} fields | blank {blank}",
        warning=("no value read" if not facts else
                 "a page was read only by the backup page reader" if by_page_reader else None),
        counts={"pages": pages.get("pages_total"), "values": len(facts), "fields": len(fields),
                "blank": blank, "backup_reader_pages": len(by_page_reader)},
        items=[f"p{f.get('page')} {_short(f.get('field_label') or f.get('field_name'), 40)} = "
               f"{_short(f.get('raw_value') or f.get('field_value'), 40)}" for f in facts]))
    # 2 CLEAN
    converted = sum(1 for f in facts if f.get("normalized_value") is not None
                    and (f.get("normalized_unit") or "") != (f.get("raw_unit") or f.get("unit") or ""))
    notes = sum(1 for f in facts if f.get("value_note"))
    steps.append(_step("CLEAN", f"units converted {converted} | notes kept {notes} | blanks {blank}",
                       counts={"converted": converted, "notes": notes, "blanks": blank}))
    # 3 EQUIPMENT
    row = connect().execute("SELECT equipment_type FROM document_classification WHERE document_id = ?",
                            (sub,)).fetchone()
    tags = sorted({f.get("equipment_tag") for f in facts if f.get("equipment_tag")})
    kind = (row["equipment_type"] if row else None) or "not identified"
    steps.append(_step("EQUIPMENT", f"type: {kind} | tags: {', '.join(tags) or 'none'}",
                       warning="equipment type not identified" if kind == "not identified" else None,
                       counts={"tags": len(tags)}))
    # 4 STANDARDS
    chosen = [dict(r) for r in connect().execute(
        "SELECT d.filename, a.selection_method FROM review_applicable_standards a"
        " JOIN documents d ON d.id = a.standard_document_id"
        " WHERE a.review_run_id = ? AND a.included = 1 ORDER BY d.filename", (review_run_id,))]
    missing = [m if isinstance(m, str) else m.get("identifier")
               for m in outcome.get("missing_references") or []]
    steps.append(_step(
        "STANDARDS",
        f"chosen {len(chosen)}: " + ", ".join(f"{c['filename']} ({c['selection_method']})"
                                               for c in chosen[:6])
        + (" ..." if len(chosen) > 6 else "")
        + f" | cited not held {len(missing)}" + (f": {', '.join(missing[:6])}" if missing else ""),
        warning="no standard chosen" if not chosen else
                "cited standards not held" if missing else None,
        counts={"chosen": len(chosen), "cited_not_held": len(missing)}))
    # 5 CHECKLIST
    checklist = [f for f in findings if f.get("origin") == "datasheet_check"]
    c_status = Counter(f.get("compliance_status") for f in checklist)
    steps.append(_step(
        "CHECKLIST",
        (f"{len(checklist)} results | " + " | ".join(
            f"{label} {c_status.get(s, 0)}" for s, label in _DECISIONS[:4])) if checklist
        else "no checklist for this type",
        counts=dict(c_status),
        items=[f"{_short(f.get('matched_phrase') or f.get('requirement'), 30)} | "
               f"value {_short(f.get('contractor_evidence_text'), 25)} | p{f.get('contractor_page') or '-'}"
               f" | {f.get('compliance_status')} | {_short(f.get('ai_rationale') or f.get('finding'), 60)}"
               for f in checklist]))
    # 6 RULES
    rules = [f for f in findings if not f.get("origin")]
    paired = sum(1 for f in rules if f.get("fact_id"))
    split = outcome.get("requirement_split") or {}
    reasons = (split.get("applies_not_checked_reasons") or []) + (split.get("does_not_apply_reasons") or [])
    steps.append(_step(
        "RULES",
        f"findings {len(rules)} | paired with a value {paired} | not checked or not applying: "
        + ("; ".join(f"{r['reason']} {r['count']}" for r in reasons[:5]) or "none recorded"),
        counts={"findings": len(rules), "paired": paired}))
    # 7 DECIDE
    status = Counter(f.get("compliance_status") for f in findings)
    decided = status.get("COMPLIANT", 0) + status.get("NON_COMPLIANT", 0)
    steps.append(_step("DECIDE", " | ".join(f"{label} {status.get(s, 0)}" for s, label in _DECISIONS),
                       warning="0 decisions (no meets, no fails)" if findings and not decided else None,
                       counts={label: status.get(s, 0) for s, label in _DECISIONS}))
    # 8 COVERAGE
    cov = split.get("checklist_coverage") or {}
    steps.append(_step(
        "COVERAGE",
        (f"checklist values read {cov.get('read')} of {cov.get('fields')} | on the sheet, not read "
         f"{cov.get('on_sheet_not_read')}") if cov else "no checklist coverage recorded",
        counts=dict(cov) if cov else {}))
    # 9 CRS
    from .main import _crs_content
    try:
        rows, _meta, _name, _stamp = _crs_content(review_run_id, scope, "internal")
    except Exception:  # noqa: BLE001 - a trace never fails; say why the step is empty
        rows = None
    if rows is None:
        steps.append(_step("CRS", "could not compose the CRS", warning="CRS not composed"))
    else:
        missed = sum(1 for r in rows if r.get("row_kind") == "standard_not_cited")
        steps.append(_step(
            "CRS", f"rows {len(rows)} | missed-standard comments {missed} | numbered "
                   f"{sum(1 for r in rows if r.get('crs_ref'))}",
            counts={"rows": len(rows), "missed_standard": missed},
            items=[f"{r.get('crs_ref') or '-'} | {_short(r.get('standard_reference'), 30)} | "
                   f"{_short(r.get('page_section'), 20)} | {_short(r.get('comment'), 80)}" for r in rows]))
    # 10 CODE
    steps.append(_step("CODE", f"{outcome.get('recommended_code') or 'none'} | rule: "
                               f"{_short(outcome.get('reason'), 120) or 'none recorded'}"))
    return {"review_run_id": review_run_id, "document": doc["filename"] if doc else sub,
            "steps": steps}


def render(trace: dict, *, detail: bool = False) -> list[str]:
    """The console block, one line per step (and per item with `detail`)."""
    lines = [f"=== REVIEW {trace['review_run_id']} | {trace.get('document')} ==="]
    for i, s in enumerate(trace["steps"], 1):
        flag = f"  !! {s['warning']}" if s.get("warning") else ""
        lines.append(f"[{i}/{len(STEPS)} {s['step']}]".ljust(16) + f" {s['summary']}{flag}")
        if detail:
            lines.extend(f"      - {item}" for item in s.get("items") or [])
    lines.append(f"=== END {trace['review_run_id']} ===")
    return lines


def emit(review_run_id: str, scope) -> list[str] | None:
    """When `REVIEW_DEBUG` is on: write the run's steps to the console and to
    its per-run file. Returns the lines (None when off). Never raises."""
    if not settings.review_debug:
        return None
    try:
        lines = render(build(review_run_id, scope), detail=settings.review_debug_detail)
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            log.addHandler(handler)
        log.setLevel(logging.INFO)
        for line in lines:
            log.info(line)
        folder = debug_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"review-{review_run_id}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return lines
    except Exception:  # noqa: BLE001 - debug output never breaks a review
        logging.getLogger(__name__).warning("review debug output failed for run %s",
                                            review_run_id, exc_info=True)
        return None
