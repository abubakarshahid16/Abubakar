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


def latest_run_ids(allowed_document_ids: frozenset[str] | None) -> dict[str, str]:
    """submittal document id -> the id of its LATEST review run (newest created_at, id as the tiebreak, the order
    `submittal_review.list_review_runs` uses). None = no restriction; an empty set = nothing."""
    if allowed_document_ids is not None and not allowed_document_ids:
        return {}
    from . import aim_review_store

    sql, args = "SELECT r.id, r.submittal_document_id FROM review_runs r WHERE 1 = 1", []
    if allowed_document_ids is not None:
        sql += " AND r.submittal_document_id IN (" + ",".join("?" for _ in allowed_document_ids) + ")"
        args = sorted(allowed_document_ids)
    sql += aim_review_store.exclude(connect())  # a general review run (order 14) holds no findings
    sql += " ORDER BY r.created_at DESC, r.id DESC"
    latest: dict[str, str] = {}
    for row in connect().execute(sql, args).fetchall():
        latest.setdefault(row["submittal_document_id"], row["id"])
    return latest


def summary_counts(allowed_document_ids: frozenset[str] | None, *, latest_run_ids: frozenset[str] | None = None) -> dict:
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
    if latest_run_ids is not None:
        # Findings of the latest review of each paper, and findings that belong to no run (added by hand). V2: every run
        # of every paper was counted, so 87 runs over 5 papers read as 186,778 findings.
        marks = ",".join("?" for _ in latest_run_ids)
        extra = "(review_run_id IS NULL" + (f" OR review_run_id IN ({marks})" if latest_run_ids else "") + ")"
        sql = (sql + " AND " if sql else " WHERE ") + extra
        args = [*args, *sorted(latest_run_ids)]
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
