"""How a review names the standards it was run against: the library file name,
and the file name with the recorded document number and title (the label an
engineer reads in a held or excluded line). One place, so the review run does
not carry the lookups inline."""

from __future__ import annotations

from .db import connect


def filenames(standard_ids: list[str]) -> dict[str, str]:
    """{standard document id: library file name}; empty for no standards."""
    if not standard_ids:
        return {}
    marks = ",".join("?" for _ in standard_ids)
    rows = connect().execute(
        f"SELECT id, filename FROM documents WHERE id IN ({marks})", standard_ids
    )
    return {r["id"]: r["filename"] for r in rows}


def labels(standard_ids: list[str], names: dict[str, str]) -> dict[str, str]:
    """{standard document id: 'file name, document number, title'} (what exists)."""
    from . import classification

    out: dict[str, str] = {}
    for sid in standard_ids:
        record = classification.of_document(sid) or {}
        parts = (names.get(sid), record.get("document_number"), record.get("title"))
        out[sid] = " ".join(filter(None, parts))
    return out
