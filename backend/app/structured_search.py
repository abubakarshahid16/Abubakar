"""Small, scope-aware search over EPC workflow records."""
from __future__ import annotations

from .db import connect


def search(query: str, *, allowed_document_ids: frozenset[str] | None = None,
           kind: str | None = None) -> list[dict]:
    term = f"%{query.strip()}%"
    if not query.strip():
        return []
    out: list[dict] = []
    if kind in (None, "deliverable"):
        sql = "SELECT id, 'deliverable' AS kind, title AS label, wbs_code, document_id FROM deliverables WHERE (title LIKE ? OR wbs_code LIKE ?)"
        args: list[object] = [term, term]
        if allowed_document_ids is not None:
            if not allowed_document_ids: return []
            marks = ",".join("?" for _ in allowed_document_ids)
            sql += f" AND (document_id IS NULL OR document_id IN ({marks}))"; args.extend(sorted(allowed_document_ids))
        out.extend(dict(row) for row in connect().execute(sql, args).fetchall())
    if kind in (None, "finding"):
        sql = "SELECT id, 'finding' AS kind, finding AS label, NULL AS wbs_code, document_id FROM review_findings WHERE (finding LIKE ? OR requirement LIKE ? OR required_action LIKE ?)"
        args = [term, term, term]
        if allowed_document_ids is not None:
            if not allowed_document_ids: return []
            marks = ",".join("?" for _ in allowed_document_ids)
            sql += f" AND document_id IN ({marks})"; args.extend(sorted(allowed_document_ids))
        out.extend(dict(row) for row in connect().execute(sql, args).fetchall())
    if kind in (None, "risk"):
        sql = "SELECT id, 'risk' AS kind, title AS label, NULL AS wbs_code, document_id FROM risks WHERE (title LIKE ? OR description LIKE ?)"
        args = [term, term]
        if allowed_document_ids is not None:
            if not allowed_document_ids: return []
            marks = ",".join("?" for _ in allowed_document_ids); sql += f" AND (document_id IS NULL OR document_id IN ({marks}))"; args.extend(sorted(allowed_document_ids))
        out.extend(dict(row) for row in connect().execute(sql, args).fetchall())
    if kind in (None, "stakeholder"):
        out.extend(dict(row) | {"kind": "stakeholder", "label": row["display_name"] or row["email"], "wbs_code": None, "document_id": None}
                   for row in connect().execute("SELECT DISTINCT u.id, u.email, u.display_name FROM users u JOIN deliverable_stakeholders ds ON ds.user_id=u.id WHERE u.email LIKE ? OR u.display_name LIKE ?", (term, term)).fetchall())
    return out[:100]
