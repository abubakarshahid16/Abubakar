"""#1503, owner decision of 2 Nov 2026, behind CRS_ONE_ROW_PER_PROBLEM_ENABLED (off).

ONE ROW PER PROBLEM. Rows with the same clause, problem, value and verdict are one row
that lists every tag and page it covers. It happens where the sheet is composed, before
any number is looked up, so numbering, the issue gate and both copies see one row. Rows
are never joined on a guess, and these never merge: a different value or verdict, an
unknown value (not even with another unknown), an engineer's different words, a confirmed
row with an unconfirmed one, a carried-forward row, and two issued numbers.

ONE NUMBER. The merged row carries its first member's number, and `member_keys` keeps every
member's. A decision covers every member (`crs_issue.group_of`), each with its own event
on its finding. Confirming one member by another route takes it out of the identity, so it
stands alone and the rest stay unconfirmed. An issued number is never renumbered; a row
holds together under one only when that number's stored words are this row's own words.

"DID NOT REFERENCE X" rows go only when nothing in the review's scope requires X
(`requires`). They are counted and named in the internal Review notes. If it cannot be
established, the row stays. Dropping one never says the document complies with X.

Nothing here looks at a layout, a label or a standard's name (rule 13).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import crs_carry, crs_issue, crs_mapping, crs_numbers, standard_ids
from .config import settings
from .db import connect
from .submittal_review import list_applicable_standards

NOTE_MERGED = "One row per problem - rows merged"
NOTE_DROPPED = "Did not reference - row dropped, nothing in scope requires it"
_NEVER = (crs_mapping.ROW_KIND_CARRIED_FORWARD, crs_mapping.ROW_KIND_ENGINEER_COMMENT)
#: `applicability.REQUIRED_BY_TYPE`: the only reason a row may go. A service the
#: datasheet declares is the reviewed scope's own reason; it stays.
_BY_TYPE = "equipment type"


def enabled() -> bool:
    return bool(settings.crs_one_row_per_problem_enabled)


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def _ids(row: dict) -> list[str]:
    ids = row.get("finding_ids") or (
        [row["finding_id"]] if row.get("finding_id") else []
    )
    return list(dict.fromkeys(ids))


def _one(findings: list[dict], read) -> str:
    """The one folded value every finding holds; "" when they differ or it is unknown."""
    values = {_fold(read(f)) for f in findings}
    return next(iter(values)) if len(values) == 1 else ""


def _identity(row: dict, by_id: dict[str, dict]):
    """What must be identical for two rows to be one, or None when this row cannot join."""
    ids = _ids(row)
    members = [by_id[i] for i in ids if i in by_id]
    clause = str(row.get("standard_reference") or "").strip()
    if (
        not members
        or len(members) != len(ids)
        or not clause
        or row.get("row_kind") in _NEVER
    ):
        return None
    verdict = _one(members, lambda f: f.get("compliance_status"))
    value = _one(members, lambda f: f.get("contractor_evidence_text"))
    problem = _one(members, lambda f: f.get("requirement_source_text"))
    if not (verdict and value and problem):
        return None
    if len({_fold(f.get("engineer_comment")) for f in members}) != 1:
        return None
    if len({_fold(crs_mapping._field_label(f)) for f in members}) != 1:
        return None
    return (
        str(row.get("document_name") or ""),
        row.get("row_kind"),
        clause,
        verdict,
        value,
        problem,
        _fold(crs_mapping._field_label(members[0])),
        _fold(members[0].get("engineer_comment")),
        row.get("engineer_confirmed") is True,
    )


def _covers_line(members: list[dict]) -> str:
    tags = dict.fromkeys(str(f.get("equipment_tag") or "").strip() for f in members)
    pages = sorted({f["contractor_page"] for f in members if f.get("contractor_page")})
    parts = []
    if any(tags):
        parts.append("tags " + ", ".join(t for t in tags if t))
    if pages:
        parts.append("pages " + ", ".join(str(p) for p in pages))
    return "Applies to: " + "; ".join(parts) + "." if parts else ""


def _unique(values, joiner: str) -> str:
    return joiner.join(dict.fromkeys(str(v) for v in values if v))


def _joined(group: list[dict], by_id: dict[str, dict]) -> dict:
    """The one row of `group`: the first row, with every member's ids, keys, tags and pages."""
    lead = group[0]
    ids = list(dict.fromkeys(i for r in group for i in _ids(r)))
    line = _covers_line([by_id[i] for i in ids])
    return {
        **lead,
        "one_row": True,
        "finding_ids": ids,
        "member_keys": sorted(
            {
                k
                for r in group
                for k in [*(r.get("member_keys") or []), r.get("comment_key")]
                if k
            }
        ),
        "page_section": _unique((r.get("page_section") for r in group), "; "),
        "comment": "\n".join(p for p in (lead.get("comment"), line) if p),
        "reasoning": _unique((r.get("reasoning") for r in group), "\n\n"),
        "rule_trust": _unique((r.get("rule_trust") for r in group), "; "),
    }


def _numbers(row: dict) -> set[str]:
    return {k for k in [row.get("comment_key"), *(row.get("member_keys") or [])] if k}


def _issued(records: dict, keys) -> list[tuple[str, dict]]:
    return [
        (k, records[k])
        for k in sorted(keys)
        if k in records and records[k].get("issued", 1)
    ]


def _hold_together(group: list[dict], by_id: dict, records: dict) -> list[dict] | None:
    """The group in row order, its number's holder first; None when an issued number forbids it."""
    issued = _issued(records, {k for r in group for k in _numbers(r)})
    if not issued:
        return group
    if len(issued) > 1:
        return None
    key, record = issued[0]
    holder = next(r for r in group if key in _numbers(r))
    ordered = [holder, *(r for r in group if r is not holder)]
    joined = _joined(ordered, by_id)
    stored = _fold(record.get("comment"))
    if not stored or crs_carry.words_changed_since_issue(joined, record):
        return None
    return ordered


def _merge_note(group: list[dict], joined: dict, by_id: dict, records: dict) -> dict:
    refs = [
        records[k]["ref"] for r in group for k in sorted(_numbers(r)) if k in records
    ]
    numbers = f" Numbers: {', '.join(dict.fromkeys(refs))}." if refs else ""
    return {
        "note": NOTE_MERGED,
        "standard": str(joined.get("standard_reference") or ""),
        "count": len(joined["finding_ids"]),
        "detail": (
            f"{len(group)} rows with the same clause, problem, value and verdict are one row. "
            f"{_covers_line([by_id[i] for i in joined['finding_ids']])}{numbers}"
        ),
    }


def merge_rows(
    rows: list[dict], findings: list[dict], records: dict
) -> tuple[list[dict], list[dict]]:
    """(rows, notes). A row keeps the place of the first row of its group."""
    by_id = {f["id"]: f for f in findings if f.get("id")}
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = _identity(row, by_id)
        if key is not None:
            groups.setdefault(key, []).append(row)
    replace: dict[int, dict | None] = {}
    notes: list[dict] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = _hold_together(group, by_id, records)
        if ordered is None:
            continue
        joined = _joined(ordered, by_id)
        notes.append(_merge_note(ordered, joined, by_id, records))
        for member in group:
            replace[id(member)] = None
        replace[id(group[0])] = joined
    out = []
    for row in rows:
        kept = replace.get(id(row), row)
        if kept is not None:
            out.append(kept)
    return out, notes


# -------------------------------------------------- "did not reference X" rows


@dataclass
class ScopeData:
    """What this run's stored data says is in scope."""

    #: The names of the standards the run applied (`review_applicable_standards`, included).
    standards: list[str]
    #: How many active requirements each of them holds, in one list.
    requirement_counts: list[int]
    #: The words of those requirements and of this run's findings.
    texts: list[str]


def requires(identifier: str, scope: ScopeData) -> bool | None:
    """Does the review's scope require this standard? True when the run applied it or a
    requirement in scope names it. False when neither does and every applied standard
    has stored requirements to read. None (cannot be established) when the run has no
    applied list, an applied standard has no requirements stored, or `identifier` names
    no standard."""
    wanted = standard_ids.parse(identifier or "")
    if wanted is None:
        return None
    if any(standard_ids.same_standard(identifier, name) for name in scope.standards):
        return True
    named = standard_ids.parse_all("\n".join(scope.texts))
    if any(standard_ids.same_identifier(wanted, other) for other in named):
        return True
    if not scope.standards or not all(scope.requirement_counts):
        return None
    return False


def _droppable(
    row: dict, check: dict, records: dict, decided, scope: ScopeData
) -> bool:
    if row.get("row_kind") != crs_mapping.ROW_KIND_STANDARD_NOT_CITED:
        return False
    ident = str(row.get("standard_reference") or "")
    entry = next(
        (
            r
            for r in (check or {}).get("required_not_cited") or []
            if r.get("identifier") == ident
        ),
        None,
    )
    if entry is None or entry.get("unsure") or entry.get("by") != _BY_TYPE:
        return False
    key = row.get("comment_key") or ""
    if key in decided or _issued(records, {key}):
        return False
    return requires(ident, scope) is False


def _drop_note(ident: str, scope: ScopeData) -> dict:
    return {
        "note": NOTE_DROPPED,
        "standard": ident,
        "count": 1,
        "detail": (
            f"The {len(scope.standards)} standards this run applied and the "
            f"{sum(scope.requirement_counts)} requirements they hold do not name {ident}. "
            "This does not say the document complies with it."
        ),
    }


def drop_unrequired(
    rows: list[dict], check: dict, scope: ScopeData, records: dict, decided
) -> tuple[list[dict], list[dict]]:
    """(rows kept, a Review note naming each one dropped)."""
    kept, notes = [], []
    for row in rows:
        if _droppable(row, check, records, decided, scope):
            notes.append(_drop_note(str(row.get("standard_reference") or ""), scope))
        else:
            kept.append(row)
    return kept, notes


def _scope_of(run_id: str, findings: list[dict], allowed: frozenset[str]) -> ScopeData:
    applied = list_applicable_standards(
        run_id, allowed_document_ids=allowed, include_excluded=False
    )
    ids = [r["standard_document_id"] for r in applied]
    names, counts, texts = [], [], []
    conn = connect()
    for doc in ids:
        name = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (doc,)
        ).fetchone()
        names.append(name["filename"] if name else "")
        words = conn.execute(
            "SELECT requirement_text, source_text FROM standard_requirements"
            " WHERE standard_document_id = ? AND superseded_at IS NULL",
            (doc,),
        ).fetchall()
        counts.append(len(words))
        texts += [
            f"{w['requirement_text'] or ''} {w['source_text'] or ''}" for w in words
        ]
    texts += [str(f.get("requirement_source_text") or "") for f in findings]
    return ScopeData(names, counts, texts)


def apply(
    rows: list[dict],
    notes: list[dict],
    findings: list[dict],
    check: dict,
    run_id: str,
    crs_scope: str,
    allowed: frozenset[str],
) -> tuple[list[dict], list[dict]]:
    """`main._crs_content`'s one call: (rows, Review notes). Switch off: as they came."""
    if not enabled():
        return rows, notes
    keys = {k for r in rows for k in _numbers(r)}
    records = crs_numbers.lookup(crs_scope, sorted(keys))
    rows, merged = merge_rows(rows, findings, records)
    dropped: list[dict] = []
    if any(r.get("row_kind") == crs_mapping.ROW_KIND_STANDARD_NOT_CITED for r in rows):
        decided = {d["subject"] for d in crs_issue.decisions(run_id)}
        rows, dropped = drop_unrequired(
            rows, check, _scope_of(run_id, findings, allowed), records, decided
        )
    return rows, [*notes, *merged, *dropped]
