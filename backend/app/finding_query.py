"""Order 117 item 5: the one WHERE of the review-findings list, and its count.

`review.list_findings` reads with it and `count_findings` counts with it, so a
page and its `total` can never disagree about which findings are in scope.
The scope filter is in the query, never after it (`metrics._where`): a filter
applied after a LIMIT silently returns the wrong page.
"""

from __future__ import annotations

from .db import connect


def where(
    document_id: str | None,
    status: str | None,
    review_run_id: str | None,
    allowed_document_ids: frozenset[str] | None,
) -> tuple[str, list] | None:
    """The WHERE fragment and its arguments; None when the caller holds no
    grants (nothing to read, never "everything")."""
    clauses: list[str] = []
    args: list = []
    if document_id:
        clauses.append("document_id = ?")
        args.append(document_id)
    if review_run_id:
        # ONE RUN'S FINDINGS. A comparison run produces one finding per
        # requirement - 1,580 on this corpus - so without this the only way to
        # see a run's output through the API is to fetch every finding ever
        # written and filter in the client.
        clauses.append("review_run_id = ?")
        args.append(review_run_id)
    if status:
        clauses.append("status = ?")
        args.append(status)
    if allowed_document_ids is not None:
        if not allowed_document_ids:
            return None
        marks = ",".join("?" for _ in allowed_document_ids)
        clauses.append(f"document_id IN ({marks})")
        args.extend(sorted(allowed_document_ids))
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), args


def count_findings(
    *,
    document_id: str | None = None,
    status: str | None = None,
    review_run_id: str | None = None,
    allowed_document_ids: frozenset[str] | None = None,
) -> int:
    """How many findings `review.list_findings` returns with no page applied."""
    found = where(document_id, status, review_run_id, allowed_document_ids)
    if found is None:
        return 0
    sql, args = found
    return (
        connect()
        .execute("SELECT COUNT(*) FROM review_findings" + sql, args)
        .fetchone()[0]
    )


def summary_counts(allowed_document_ids: frozenset[str] | None) -> dict:
    """The management summary's finding numbers, counted in SQL (V1b).

    The same numbers `review.list_findings` + a Python loop gave, without reading every finding row: one GROUP BY over the
    four columns the numbers depend on, then the severity word the screen shows (`severity_rule.effective_severity`) is
    applied to each group, so a group of old rows lands under the word it is displayed with. Scope is the one `where`.
    """
    from . import severity_rule

    found = where(None, None, None, allowed_document_ids)
    out = {"total": 0, "by_severity": {}, "by_status": {}, "escalated": 0}
    if found is None:
        return out
    sql, args = found
    rows = connect().execute(
        "SELECT severity, compliance_status, status, COALESCE(escalation_level, 0) > 0 AS esc, COUNT(*) AS n"
        " FROM review_findings" + sql + " GROUP BY severity, compliance_status, status, esc",
        args,
    ).fetchall()
    for row in rows:
        n = row["n"]
        word = severity_rule.effective_severity(
            {"severity": row["severity"], "compliance_status": row["compliance_status"]})
        out["total"] += n
        out["by_severity"][word] = out["by_severity"].get(word, 0) + n
        out["by_status"][row["status"]] = out["by_status"].get(row["status"], 0) + n
        if row["esc"]:
            out["escalated"] += n
    return out
