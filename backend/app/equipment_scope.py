"""Rules by equipment scope: a rule written for ANOTHER equipment type or document
kind is left out of a review, counted, never silently dropped.

Behind `settings.rules_by_equipment_scope_enabled`, OFF by default. A rule has a
scope when (a) its stored `equipment_type` names equipment, or (b) its standard is
listed under `scope_only_standards` in `reference/governing_standards.json` (a
standard written for one equipment type only, e.g. a pump standard), or (c) it
carries a `document_kind` naming the kinds it is for. A rule with no known scope
stays in, and so does every rule when the submittal's own equipment type or kind
is unknown, unsure or a guess (rule 4: a guess stays a guess). This only NARROWS
the set the review already holds (rule 5); it adds nothing and reads no other
document. It recognises no layout (rule 13): types come from the equipment
vocabulary, kinds from the router.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import standard_ids, subject_scope
from .db import connect

TABLE_PATH = Path(__file__).parent / "reference" / "governing_standards.json"
CODE = "other_equipment_scope"


def enabled() -> bool:
    from .config import settings

    return bool(settings.rules_by_equipment_scope_enabled)


def scope_only_table(path: Path | None = None) -> dict[str, list[str]]:
    """{equipment type: [standards written for that type only]}."""
    data = json.loads((path or TABLE_PATH).read_text(encoding="utf-8"))
    table = data.get("scope_only_standards") or {}
    return {str(k).strip().lower(): list(v) for k, v in table.items()}


def submittal_kind(document_id: str | None) -> str | None:
    """The router's kind when decided: confirmed, or a suggestion that is not a
    guess. None for a guess, `needs_engineer`, `unknown` or no row."""
    if not document_id:
        return None
    row = (
        connect()
        .execute(
            "SELECT kind, state, evidence FROM document_kinds WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    if row is None or row["state"] == "needs_engineer":
        return None
    try:
        guess = bool(json.loads(row["evidence"] or "{}").get("guess"))
    except (TypeError, ValueError, AttributeError):
        guess = False
    kind = (row["kind"] or "").strip().lower()
    if not kind or kind == "unknown" or (guess and row["state"] != "confirmed"):
        return None
    return kind


def _kinds(value: object) -> set[str]:
    if not value:
        return set()
    items = [value] if isinstance(value, str) else list(value)
    return {str(k).strip().lower() for k in items if str(k).strip()}


def _own_types(
    requirement: dict, label: str, table: dict, vocab
) -> tuple[set[str], str]:
    """(equipment types the rule is for, where that was read) or (empty, "")."""
    stored = vocab.equipment_in(requirement.get("equipment_type"))
    if stored:
        return stored, "the rule's stored equipment type"
    if label:
        types = {
            kind
            for kind, codes in table.items()
            if any(standard_ids.same_standard(label, c) for c in codes)
        }
        if types:
            return types, "its standard is written for that equipment"
    return set(), ""


def gate(
    requirements: list[dict],
    *,
    equipment: set[str],
    kind: str | None,
    standard_labels: dict[str, str],
    table: dict[str, list[str]] | None = None,
    vocab=None,
) -> dict:
    """{"kept", "items", "summary"}. `equipment` is the submittal's equipment
    types as `subject_scope.read_equipment` reads them (empty = unknown or
    unsure); `kind` is `submittal_kind`. Every item carries code CODE and a
    reason; the summary counts with their boundary."""
    if not enabled():
        return {"kept": list(requirements), "items": [], "summary": None}
    vocab = vocab or subject_scope.vocabulary()
    table = scope_only_table() if table is None else table
    kept: list[dict] = []
    items: list[dict] = []
    by_other: dict[str, int] = {}
    unknown = unsure = 0
    for r in requirements:
        label = standard_labels.get(r.get("standard_document_id") or "", "")
        types, where = _own_types(r, label, table, vocab)
        kinds = _kinds(r.get("document_kind"))
        out_equipment = bool(types and equipment and not (types & equipment))
        out_kind = bool(kinds and kind and kind not in kinds)
        if out_equipment or out_kind:
            names = sorted(types) if out_equipment else sorted(kinds)
            by_other[" / ".join(names)] = by_other.get(" / ".join(names), 0) + 1
            this = ", ".join(sorted(equipment)) if out_equipment else kind
            items.append(
                {
                    "requirement": r,
                    "code": CODE,
                    "detail": f"for {' / '.join(names)} ({where or 'its stored document kind'}), "
                    f"this submittal is {this}",
                }
            )
            continue
        if (types and not equipment) or (kinds and not kind):
            unsure += 1  # has a scope, but the submittal's own is not decided
        elif not types and not kinds:
            unknown += 1
        kept.append(r)
    total = len(requirements)
    left_out = len(items)
    note = None
    if left_out:
        groups = "; ".join(f"{n} apply to {k}" for k, n in sorted(by_other.items()))
        note = (
            f"{left_out} rules left out: they apply to "
            f"{', '.join(sorted(by_other))} ({groups}); counted of the {total} rules "
            "of the standards in scope of this review"
        )
    summary = {
        "considered": total,
        "left_out": left_out,
        "by_other_scope": by_other,
        "kept_scope_unknown": unknown,
        "kept_submittal_scope_undecided": unsure,
        "submittal_equipment": sorted(equipment),
        "submittal_kind": kind,
        "note": note,
        "boundary": "the rules of the standards in scope of this review",
    }
    return {"kept": kept, "items": items, "summary": summary}


def split_part(result: dict | None) -> dict:
    """What the run stores in `requirement_split`; nothing when off."""
    summary = (result or {}).get("summary")
    return {"equipment_scope": summary} if summary else {}
