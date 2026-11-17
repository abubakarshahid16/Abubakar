"""Standards by ROLE and document KIND: a procedure is not checked against equipment design standards.

Owner order 3 Nov 2026: a HAZOP / SIL study procedure is checked against how studies must be run, never against the
design clauses of equipment standards (SAES-J-601 design sections, SAES-B-006 fireproofing). `reference/
standard_roles.json` (owner-editable data, no standard or kind named in code) gives each standard a ROLE and each document
kind the roles that apply to it. After the review's standards are chosen, a standard whose role does not apply to the
document's kind is LEFT OUT of the run (`excluded_by_scope`, the exclusion the review already persists with its reason) and COUNTED in the run note ("N standards left out: equipment
design standards do not apply to a procedure"): nothing vanishes unseen. Method standards that are held apply. When the
method standards for the kind are NOT held, the note says so ONCE ("standard needed: ...").

A kind only NARROWS (rule 5). Never left out: an engineer's manual choice, a standard with no role in the table, a kind with
no entry, an undecided, unknown or guessed kind. Off by default (`standard_roles_by_kind_enabled`); off, nothing here runs
and every answer is the one the review gave before. Pure reads of the table and the document-kind router's table.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import standard_ids
from .config import settings
from .db import connect

TABLE_PATH = Path(__file__).parent / "reference" / "standard_roles.json"
LEFT_OUT_MARK = " standards do not apply to a "


def enabled() -> bool:
    return bool(settings.standard_roles_by_kind_enabled)


def table(path: Path | None = None) -> dict:
    return json.loads((path or TABLE_PATH).read_text(encoding="utf-8"))


def kind_of(document_id: str | None) -> str | None:
    """The document's kind when it is decided: confirmed, or a suggestion the classifier did not mark a guess."""
    from . import kind_rules

    kind, state, guess = kind_rules._lookup(document_id)
    if (
        not kind
        or kind in ("unknown", "needs_engineer")
        or (guess and state != "confirmed")
    ):
        return None
    return kind


def role_of(labels: list[str], data: dict) -> str | None:
    """The role of the standard these names point at, or None: unmapped. A standard the table names keeps its role; one it
    does not name but that GOVERNS an equipment type (reference/governing_standards.json: an equipment type's books, its
    books in part, the materials books) takes `governing_books_role` when the table sets it (order 14 lane C: a procedure
    whose equipment type was misread is not given that equipment's design books)."""
    for identifier, role in (data.get("standards") or {}).items():
        if any(
            label and standard_ids.same_standard(identifier, label) for label in labels
        ):
            return role
    fallback = data.get("governing_books_role")
    if fallback and any(
        label and standard_ids.same_standard(book, label)
        for book in _governing_books()
        for label in labels
    ):
        return fallback
    return None


_GOVERNING_CACHE: dict[tuple, list[str]] = {}


def _governing_books() -> list[str]:
    """Every book reference/governing_standards.json names for an equipment type (whole, in part, materials). Read once per
    version of the file (a rule decision asks it once per rule)."""
    from . import applicability

    path = applicability.GOVERNING_PATH
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _GOVERNING_CACHE:
        _GOVERNING_CACHE.clear()
        _GOVERNING_CACHE[key] = _read_governing_books(
            applicability.governing_table(path)
        )
    return _GOVERNING_CACHE[key]


def _read_governing_books(gov: dict) -> list[str]:
    books = [b for ids in gov["equipment_types"].values() for b in ids]
    books += [
        e["standard"] for entries in gov["partial_standards"].values() for e in entries
    ]
    return sorted(set(books + list(gov["materials_standards"])))


def _labels(entry: dict | None, row: dict) -> list[str]:
    names = [row.get("identifier")]
    if entry:
        stem = str(entry.get("filename") or "").rsplit(".", 1)[0]
        names += [entry.get("identifier"), entry.get("document_number"), stem]
    return [n for n in names if n]


def apply(
    selected: dict[str, dict],
    document_id: str,
    library: list[dict],
    data: dict | None = None,
) -> dict | None:
    """Leave out of `selected` the standards whose role does not apply to the document's kind. Returns
    `{"kind", "count", "identifiers", "note", "needed"}` or None (off, kind undecided, nothing to say)."""
    if not enabled():
        return None
    kind = kind_of(document_id)
    data = data or table()
    allowed_roles = (data.get("kinds_apply") or {}).get(kind or "")
    if kind is None or allowed_roles is None:
        return None
    from . import applicability

    by_id = {entry["id"]: entry for entry in library}
    spared = set(data.get("never_left_out_methods") or ())
    left: dict[str, list[str]] = {}
    for standard_id, row in selected.items():
        # Only a standard the review's own matching picked, and only one it actually included: a person's or the project's
        # choice stays, and a row already held, excluded or candidate-only keeps its own reason and is not counted.
        if row.get("method") in spared or not applicability.is_included(row):
            continue
        labels = _labels(by_id.get(standard_id), row)
        role = role_of(labels, data)
        if role is not None and role not in allowed_roles:
            row["excluded_by_scope"] = (
                f"{role}{LEFT_OUT_MARK}{kind}"  # the existing exclusion: not included, reason persisted
            )
            left.setdefault(role, []).append(labels[0] if labels else standard_id)
    count = sum(len(v) for v in left.values())
    held = [lbl for entry in library for lbl in _labels(entry, {})]
    needed = [
        name
        for name in (data.get("method_standards") or {}).get(kind, [])
        if not any(standard_ids.same_standard(name, lbl) for lbl in held)
    ]
    note = "; ".join(
        f"{len(ids)} standard{'s' if len(ids) != 1 else ''} left out: {role}{LEFT_OUT_MARK}{kind}"
        for role, ids in left.items()
    )
    if not count and not needed:
        return None
    return {
        "kind": kind,
        "count": count,
        "identifiers": sorted({i for v in left.values() for i in v}),
        "note": note or None,
        "needed": needed,
    }


def _book_labels(conn, standard_document_id: str) -> list[str]:
    """The names a held book is known by (its document number, the number its file name carries, its file name), or []
    when the database has no such book. Read only."""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
    ).fetchone():
        return []
    row = conn.execute(
        "SELECT d.filename, c.document_number FROM documents d"
        " LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?",
        (standard_document_id,),
    ).fetchone()
    if row is None:
        return []
    from . import applicability

    filename = str(row[0] or "")
    names = [
        row[1],
        applicability.library_identifier(filename),
        filename.rsplit(".", 1)[0],
    ]
    return [n for n in names if n]


def _rule_book(conn, requirement_id: str) -> str | None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'standard_requirements'"
    ).fetchone():
        return None
    row = conn.execute(
        "SELECT standard_document_id FROM standard_requirements WHERE id = ?",
        (str(requirement_id),),
    ).fetchone()
    return row[0] if row else None


def rule_book_left_out(
    conn, requirement_id: str, paper_kind: str | None, data: dict | None = None
) -> dict | None:
    """Order 14 lane C, the RULE-level door: a rule whose book has a role that does not apply to the paper's kind
    (`kinds_apply`) is not asked of that paper, however the rule itself was labelled and however its book reached the
    candidates (named by the paper, kept by a stored classic run's per-rule decisions). Returns {"role", "kind", "book",
    "needs_kind"}
    when the rule is left out, else None. Off, an unmapped book, a kind with no entry or a rule with no stored book: None
    (a kind only narrows, rule 5). Read only."""
    if not enabled() or not paper_kind:
        return None
    data = data or table()
    allowed_roles = (data.get("kinds_apply") or {}).get(str(paper_kind))
    if allowed_roles is None:
        return None
    book = _rule_book(conn, requirement_id)
    if not book:
        return None
    labels = _book_labels(conn, book)
    role = role_of(labels, data)
    if role is None or role in allowed_roles:
        return None
    every = set(data.get("roles") or ())
    kinds = [  # the kinds this role governs; a kind that takes every role (contract, specification) is not named
        k
        for k, roles in (data.get("kinds_apply") or {}).items()
        if role in roles and set(roles) != every
    ]
    return {
        "role": role,
        "kind": str(paper_kind),
        "book": labels[0] if labels else book,
        "needs_kind": " or ".join(kinds) or role,
    }


def needed_line(kind: str, needed: list[str]) -> str | None:
    if not needed:
        return None
    return (
        f"Standard needed: {', '.join(needed)} (how a {kind} must be run). None of them is held in the library, so this "
        f"{kind} is not checked against them."
    )


def note_for_run(document_id: str, allowed) -> dict | None:
    """The run note's extra lines for the review of `document_id`, from the run's stored selection (the latest run of this
    submittal): how many standards the kind left out, and the method standards still needed. None when off."""
    if not enabled():
        return None
    kind = kind_of(document_id)
    if kind is None:
        return None
    from . import aim_review_store

    conn = connect()
    run = conn.execute(  # a general review run (order 14) stores no applicable standards: not this reader's run
        "SELECT r.id FROM review_runs r WHERE r.submittal_document_id = ?"
        + aim_review_store.exclude(conn)
        + " ORDER BY r.created_at DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    if run is None:
        return None
    rows = conn.execute(
        "SELECT exclusion_reason FROM review_applicable_standards WHERE review_run_id = ? AND included = 0"
        " AND exclusion_reason LIKE ?",
        (run["id"], f"%{LEFT_OUT_MARK}{kind}"),
    ).fetchall()
    data = table()
    from . import applicability

    library = applicability._library(allowed)
    held = [lbl for entry in library for lbl in _labels(entry, {})]
    needed = [
        n
        for n in (data.get("method_standards") or {}).get(kind, [])
        if not any(standard_ids.same_standard(n, h) for h in held)
    ]
    roles: dict[str, int] = {}
    for r in rows:
        role = r["exclusion_reason"].split(LEFT_OUT_MARK)[0]
        roles[role] = roles.get(role, 0) + 1
    left = "; ".join(
        f"{n} standard{'s' if n != 1 else ''} left out: {role}{LEFT_OUT_MARK}{kind}"
        for role, n in roles.items()
    )
    if not left and not needed:
        return None
    return {
        "roles_left_out": left or None,
        "standard_needed": needed_line(kind, needed),
    }
