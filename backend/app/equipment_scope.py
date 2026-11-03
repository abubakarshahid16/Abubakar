"""Rules by equipment scope: a rule written for ANOTHER equipment type or document
kind is left out of a review, counted, never silently dropped.

Behind `settings.rules_by_equipment_scope_enabled`, OFF by default. A rule has a
scope when (a) its standard is listed under `scope_only_standards` in
`reference/governing_standards.json` (a standard written for one equipment type
only, e.g. a pump standard), or (b) it carries a `document_kind` naming the
kinds it is for. A rule's own stored equipment type never drops it (a component
is built to its parent's code). A rule with no known scope
stays in, and so does every rule when the submittal's own equipment type or kind
is unknown or a guess (rule 4: a guess stays a guess). On a sheet whose type is
UNSURE (`subject_scope.equipment_doubt`) nothing is left out by equipment: a rule
about none of its possible types is HELD for the engineer, counted on its own line
(`hold_unsure`), until a type is confirmed. This only NARROWS
the set the review already holds (rule 5); it adds nothing and reads no other
document. It recognises no layout (rule 13): types come from the equipment
vocabulary, kinds from the router.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import standard_ids, subject_scope, v1_part_scope
from .db import connect

TABLE_PATH = Path(__file__).parent / "reference" / "governing_standards.json"
CODE = "other_equipment_scope"
HELD_CODE = "equipment_unconfirmed"


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


def _own_types(label: str, table: dict) -> tuple[set[str], str]:
    """(equipment types the rule is for, where that was read) or (empty, "").
    ONLY a standard written for one equipment family gives a scope. A rule's own
    stored type never drops it: a heat exchanger is built to a pressure-vessel
    code, and hiding an applicable requirement is worse than noise."""
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
) -> dict:
    """{"kept", "items", "summary"}. `equipment` is the submittal's equipment
    types as `subject_scope.read_equipment` reads them (empty = unknown or
    unsure, so none is left out here; `hold_unsure` holds an unsure sheet's);
    `kind` is `submittal_kind`. Every item carries code CODE and a
    reason; the summary counts with their boundary."""
    if not enabled():
        return {"kept": list(requirements), "items": [], "summary": None}
    table = scope_only_table() if table is None else table
    kept: list[dict] = []
    items: list[dict] = []
    by_other: dict[str, int] = {}
    unknown = unsure = 0
    for r in requirements:
        label = standard_labels.get(r.get("standard_document_id") or "", "")
        types, where = _own_types(label, table)
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


def hold_unsure(requirements, doubt, standard_labels, vocab) -> dict:
    """An unsure sheet rules nothing out (order 142). {"kept", "held", "summary"}: a rule about
    none of the sheet's POSSIBLE types (the type it is named as, the types its stated codes govern)
    is held for the engineer, on its own count. A guess is never the submittal's type (rule 4), and
    the sheet may really be any type, so the rule still applies until a type is confirmed."""
    if not doubt or not enabled():
        return {"kept": list(requirements), "held": [], "summary": None}
    possible = set(doubt["named"]) | {
        t for code in doubt["declared"] for t in code["governs"]
    }
    table = scope_only_table()
    headings = subject_scope.heading_sections(
        sorted({r.get("standard_document_id") or "" for r in requirements})
    )
    kept: list[dict] = []
    held: list[dict] = []
    by_type: dict[str, int] = {}
    for r in requirements:
        sid = r.get("standard_document_id") or ""
        about = subject_scope.requirement_subject(r, headings.get(sid, {}), vocab)[0]
        about = about | _own_types(standard_labels.get(sid, ""), table)[0]
        if not about or about & possible:
            kept.append(r)
            continue
        name = " / ".join(sorted(about))
        by_type[name] = by_type.get(name, 0) + 1
        detail = f"applies only if this is a {name}: engineer to confirm"
        held.append({"requirement": r, "code": HELD_CODE, "detail": detail})
    if not held:
        return {"kept": kept, "held": [], "summary": None}
    guess = " / ".join(sorted(possible))
    groups = "; ".join(
        f"{n} apply only if this is a {k}" for k, n in sorted(by_type.items())
    )
    note = (
        f"{len(held)} rules held for the engineer: {groups}. The equipment type is unsure "
        f"(a guess: {guess}), engineer to confirm; not compared, not left out; counted of the "
        f"{len(requirements)} rules of the standards in scope of this review"
    )
    summary = {
        "count": len(held),
        "by_type": by_type,
        "possible_types": sorted(possible),
        "note": note,
    }
    return {"kept": kept, "held": held, "summary": summary}


def split_part(result: dict | None) -> dict:
    """What the run stores in `requirement_split`; nothing when off."""
    summary = (result or {}).get("summary")
    return {"equipment_scope": summary} if summary else {}


def lines(outcome: dict | None) -> list[dict]:
    """The counts with their boundary, for the run summary and the CRS notes: the
    rules left out, and on its own line the rules held on an unsure equipment type."""
    part = ((outcome or {}).get("requirement_split") or {}).get("equipment_scope") or {}
    notes = [
        part.get("note"),
        (part.get("held_equipment_unconfirmed") or {}).get("note"),
    ]
    return [
        {
            "part": "equipment_scope",
            "line": note,
            "detail": True,
            "note": "Rules by equipment",
        }
        for note in notes
        if note
    ]


def gate_for_run(
    requirements, stored, facts, submittal_id, standard_labels, not_applied
):
    """The review's one call: `subject_scope.partial_gate`, the scope gate, then
    `hold_unsure`. Adds both gates' left-out items to `not_applied`. Returns (kept,
    result); `split_part` stores its summary, `result["held"]` is the held rules."""
    from . import applicability

    vocab = subject_scope.vocabulary()
    equipment, _source, doubt = subject_scope.read_equipment(stored, facts, vocab)
    partial = subject_scope.partial_gate(
        requirements,
        equipment=equipment,
        standard_labels=standard_labels,
        partial_standards=applicability.governing_table()["partial_standards"],
    )
    not_applied.extend(partial["items"])
    result = gate(
        partial["kept"],
        equipment=equipment,
        kind=submittal_kind(submittal_id),
        standard_labels=standard_labels,
    )
    not_applied.extend(result["items"])
    hold = hold_unsure(result["kept"], doubt, standard_labels, vocab)
    if hold["summary"]:
        result["summary"] = {
            **result["summary"],
            "held_equipment_unconfirmed": hold["summary"],
        }
    kept = v1_part_scope.gate(hold["kept"], stored.get("equipment_type"), not_applied)
    return kept, {**result, "held": hold["held"]}
