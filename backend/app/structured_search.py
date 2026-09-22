"""Small, scope-aware search over EPC workflow records.

B42. Every branch here now narrows through the SAME mask before a row is read.
Three things were wrong, and they were one mistake at three strengths:

* **The stakeholder branch never consulted the mask at all.** The route built a
  correct scope and passed it in; this branch discarded it and returned every
  user's email and display name through `deliverable_stakeholders`. It is
  reachable from the UI, which offers `stakeholder` in its own `kind` selector.
  A stakeholder is now visible only through a deliverable the caller may read -
  people are scoped by the documents they are attached to, because that is the
  only relationship this table records.
* **`allowed_document_ids` defaulted to `None`, meaning EVERYTHING.** It is now
  required. `access.unrestricted_scope()` deliberately materialises every id
  rather than passing `None`, so "the enforcement path is IDENTICAL in both
  modes"; a permissive default here reintroduced exactly the short-circuit that
  module went out of its way to remove. Every sibling - `applicability`,
  `comparison`, `answer`, `acronyms`, `claude_selection`, `corpus` - declares it
  required, and this module was the one outlier.
* **Rows belonging to no document were admitted to every scoped result.**
  `access.py:105-111` gives an unowned row to the admin capability and to nobody
  else. The two rules disagreed; `include_unowned` makes them agree, and it is
  required too, so the caller states the decision rather than inheriting it.

An empty scope means NOTHING, never everything - and it no longer returns early
from the whole function, which used to make the answer depend on which `kind`
was asked for.
"""
from __future__ import annotations

from .db import connect


def _scope_sql(column: str, allowed_document_ids: frozenset[str],
               include_unowned: bool) -> tuple[str, list[object]]:
    """The mask as a WHERE fragment, applied in SQL before any row is read.

    Never returns an empty fragment: a caller with no grants and no claim on
    the unowned rows gets `1=0`, which is "nothing" spelled so that a future
    edit cannot turn it into "everything" by dropping a clause.
    """
    parts: list[str] = []
    args: list[object] = []
    if allowed_document_ids:
        marks = ",".join("?" for _ in allowed_document_ids)
        parts.append(f"{column} IN ({marks})")
        args.extend(sorted(allowed_document_ids))
    if include_unowned:
        parts.append(f"{column} IS NULL")
    if not parts:
        return " AND 1=0", []
    return " AND (" + " OR ".join(parts) + ")", args


def search(query: str, *, allowed_document_ids: frozenset[str],
           include_unowned: bool, kind: str | None = None) -> list[dict]:
    """Records matching `query`, never more than the caller may read.

    `include_unowned` is the admin capability's entitlement to rows with no
    document, and comes from `AccessScope.is_admin` - which is already
    "unrestricted or holds admin", the same test `owns_conversation` applies.
    """
    term = f"%{query.strip()}%"
    if not query.strip():
        return []
    out: list[dict] = []
    if kind in (None, "deliverable"):
        where, scope_args = _scope_sql("document_id", allowed_document_ids,
                                       include_unowned)
        sql = ("SELECT id, 'deliverable' AS kind, title AS label, wbs_code,"
               " document_id FROM deliverables"
               " WHERE (title LIKE ? OR wbs_code LIKE ?)" + where)
        out.extend(dict(row) for row in
                   connect().execute(sql, [term, term, *scope_args]).fetchall())
    if kind in (None, "finding"):
        # Findings are never unowned: `review_findings.document_id` is NOT NULL
        # in the schema, so there is no unowned row for the admin rule to reach.
        # Passing False rather than `include_unowned` states that in code.
        where, scope_args = _scope_sql("document_id", allowed_document_ids, False)
        sql = ("SELECT id, 'finding' AS kind, finding AS label,"
               " NULL AS wbs_code, document_id FROM review_findings"
               " WHERE (finding LIKE ? OR requirement LIKE ?"
               " OR required_action LIKE ?)" + where)
        out.extend(dict(row) for row in
                   connect().execute(sql, [term, term, term, *scope_args]).fetchall())
    if kind in (None, "risk"):
        where, scope_args = _scope_sql("document_id", allowed_document_ids,
                                       include_unowned)
        sql = ("SELECT id, 'risk' AS kind, title AS label, NULL AS wbs_code,"
               " document_id FROM risks"
               " WHERE (title LIKE ? OR description LIKE ? OR risk_type LIKE ?)"
               + where)
        out.extend(dict(row) for row in
                   connect().execute(sql, [term, term, term, *scope_args]).fetchall())
    if kind in (None, "stakeholder"):
        # Scoped through the deliverable the person is attached to. The join is
        # the mask: a stakeholder reachable by no readable deliverable is not
        # reachable at all, so an unmatched person cannot fall through it.
        where, scope_args = _scope_sql("d.document_id", allowed_document_ids,
                                       include_unowned)
        sql = ("SELECT DISTINCT u.id, u.email, u.display_name FROM users u"
               " JOIN deliverable_stakeholders ds ON ds.user_id = u.id"
               " JOIN deliverables d ON d.id = ds.deliverable_id"
               " WHERE (u.email LIKE ? OR u.display_name LIKE ?)" + where)
        out.extend(
            dict(row) | {"kind": "stakeholder",
                         "label": row["display_name"] or row["email"],
                         "wbs_code": None, "document_id": None}
            for row in connect().execute(sql, [term, term, *scope_args]).fetchall())
    return out[:100]
