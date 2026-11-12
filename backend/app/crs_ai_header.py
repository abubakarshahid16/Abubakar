"""The facts the AI reviewer's CRS header block prints, read from what the app already holds for the document (order 13).

Reads only. A value the app does not hold is '' (CLAUDE.md rule 4: null renders as nothing; never invented). No model name and no
run number here: those live on the Notes sheet of the internal copy only.
"""

from __future__ import annotations

from collections.abc import Mapping

FIELDS = ("project", "document_number", "title", "revision", "date", "discipline")


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def equipment_words(equipment_type: object) -> str:
    """An equipment type of the app's vocabulary in plain words ('pressure_relief_valve' -> 'pressure relief valve')."""
    return _text(str(equipment_type or "").replace("_", " "))


def document_header(
    conn, document_id: str, equipment_type: object = None
) -> dict[str, str]:
    """{project, document_number, title, revision, date, discipline} of one document from `document_classification`.
    The discipline is the stored one (the cover's own words, else its canonical spelling); when none is stored, the
    equipment type in plain words; else ''."""
    row = conn.execute(
        "SELECT project, document_number, title, revision, effective_date, discipline, discipline_canonical, equipment_type"
        " FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    got: Mapping = dict(row) if row is not None else {}
    discipline = _text(got.get("discipline_canonical")) or _text(got.get("discipline"))
    discipline = discipline or equipment_words(
        equipment_type or got.get("equipment_type")
    )
    return {
        "project": _text(got.get("project")),
        "document_number": _text(got.get("document_number")),
        "title": _text(got.get("title")),
        "revision": _text(got.get("revision")),
        "date": _text(got.get("effective_date")),
        "discipline": discipline,
    }


def header_of(submittal: str, equipment_type: str | None) -> dict:
    """`document_header` on the calling thread's own connection (the job's)."""
    from .db import connect

    with connect() as conn:
        return document_header(conn, submittal, equipment_type)
