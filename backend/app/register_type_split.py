"""Split the documents with no register type: awaiting, or not in the register (#1087).

Kept out of `classification.py` (a listed long file that may only shrink).
"""

from __future__ import annotations

from . import access
from .db import connect


def untyped_split(scope: access.AccessScope) -> tuple[int, int]:
    """(awaiting a type, not in the register) among the documents in THIS
    CALLER'S SCOPE that have no register type (#1087).

    The register types only the deliverables it lists, so a document an
    administrator has given a ROLE (standard, contract document, submittal ...)
    will never get one: it is "not in the register", not "awaiting". A document
    with no role, or no classification row at all, is unknown and still
    awaiting. The two add up to the documents with no type."""
    allowed = list(scope.allowed_document_ids)
    if not allowed:
        return 0, 0
    marks = ",".join("?" * len(allowed))
    row = (
        connect()
        .execute(
            f"SELECT COALESCE(SUM(c.document_role IS NULL), 0),"
            f"       COALESCE(SUM(c.document_role IS NOT NULL), 0)"
            f" FROM documents d"
            f" LEFT JOIN document_classification c ON c.document_id = d.id"
            f" WHERE d.id IN ({marks})"
            f"   AND (c.document_id IS NULL OR c.doc_type IS NULL)",
            allowed,
        )
        .fetchone()
    )
    return int(row[0]), int(row[1])
