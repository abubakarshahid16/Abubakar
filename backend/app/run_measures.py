"""#1525: the headline counts of one review run, in one home.

The CRS bench (`tools/crs_bench.score`) and the audit report (`review_audit_detail`)
both read `headline`, so a run's audit and its bench row can never count differently:
the same pattern as `deferred_pass`. It reads and counts; it decides nothing. A figure
that needs the bench's truth file is None for a run that is not on it, never 0.
"""

from __future__ import annotations

import re
import sqlite3

from . import coverage_pair, deferred_pass, presence_check

DECIDED = ("COMPLIANT", "NON_COMPLIANT")
NOT_IN_SCOPE = "NOT_IN_DOCUMENT_SCOPE"


def fold(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _quotes(conn: sqlite3.Connection, document_id: str, findings: list[dict]) -> dict:
    page_text = {
        r["page_no"]: fold(r["text"])
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
        )
    }
    quoted = [
        f
        for f in findings
        if (f.get("contractor_evidence_text") or "").strip()
        and f.get("contractor_page")
    ]
    verified = [
        f
        for f in quoted
        if fold(f["contractor_evidence_text"])
        in page_text.get(f["contractor_page"], "")
    ]
    return {
        "quotes_verified": len(verified),
        "quotes_unverified": len(quoted) - len(verified),
        "quotes_total": len(quoted),
    }


def _truth(
    conn: sqlite3.Connection, findings: list[dict], case: dict | None, replayed: bool
) -> dict:
    if case is None:
        return dict.fromkeys(("wrong", "untrue", "irrelevant"))
    matchers = case.get("wrong", []) + (
        case.get("wrong_replay", []) if replayed else []
    )
    if any(m.get("deferred") for m in matchers):
        for f in findings:
            f["deferred"] = f.get(
                "compliance_status"
            ) == "COMPLIANT" and coverage_pair.value_is_deferred(conn, f)
    wrong = [
        f
        for f in coverage_pair.hits(findings, matchers)
        if f.get("compliance_status") in DECIDED
    ]
    return {
        "wrong": len(wrong),
        "untrue": len(coverage_pair.hits(findings, case.get("untrue", []))),
        "irrelevant": len(coverage_pair.hits(findings, case.get("irrelevant", []))),
    }


def _pages(coverage: dict) -> dict:
    total = coverage.get("pages_total")
    # #1473: with PAGE_READ_BY_READING_ENABLED the ledger names the pages no
    # reading came back for; without it, the pages no field was read from.
    unread = (
        coverage.get("pages_not_read", coverage.get("pages_not_read_into_fields")) or []
    )
    return {
        "pages_read": None if total is None else total - len(unread),
        "pages_total": total,
    }


def headline(
    conn: sqlite3.Connection,
    document_id: str,
    outcome: dict,
    findings: list[dict],
    case: dict | None,
    *,
    coverage: dict | None = None,
    replayed: bool = False,
) -> dict:
    """The bench's headline measures. `case`: the run's truth entry; None = not on the file."""
    checklist = [f for f in findings if f.get("origin") == "datasheet_check"]
    with_req = [f for f in findings if f.get("requirement_id")]
    in_scope = {
        f["requirement_id"]
        for f in with_req
        if f.get("compliance_status") != NOT_IN_SCOPE
    }
    decided_req = {
        f["requirement_id"] for f in with_req if f.get("compliance_status") in DECIDED
    }
    if coverage is None:
        coverage = outcome.get("page_coverage") or {}
    split = outcome.get("requirement_split") or {}
    if isinstance(split.get("applies_not_checked"), int):
        # the headline's own boundary: the rules that apply to this submittal
        applies = (split.get("checked") or 0) + split["applies_not_checked"]
    else:
        applies = len(in_scope)
    is_deferred = deferred_pass.is_deferred_pass
    return {
        **_truth(conn, findings, case, replayed),
        # D2 (owner): a value marked 'By Contractor'/TBA is a Query, so a Pass
        # on one is not a decision the bench credits; it is shown on its own row.
        "checklist_decided": sum(
            presence_check.status_of(f) in DECIDED and not is_deferred(f)
            for f in checklist
        ),
        "checklist_total": len(checklist),
        "fails": sum(f.get("compliance_status") == "NON_COMPLIANT" for f in findings),
        "rules_decided": len(decided_req),
        "rules_in_scope": applies,
        "sent_away": sum(f.get("compliance_status") == NOT_IN_SCOPE for f in findings),
        **_quotes(conn, document_id, findings),
        **_pages(coverage),
        "pass_on_deferred": sum(map(is_deferred, findings)),
    }
