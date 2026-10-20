"""An equipment type is not one kind (orders 180.1 item 5).

A standard that governs "pumps" may govern only one pump type (centrifugal,
reciprocating, metering, rotary); the same holds for compressors and heat
exchangers. The table in `reference/governing_standards.json`
(`equipment_subtypes`) says, per equipment type, which words state each sub-type
and which sub-types each standard governs. This module reads what the SHEET
states (its own text), never the library's wording:

  * a standard whose sub-types include a stated one -> required, as before;
  * a standard whose sub-types are all others than the stated one(s) -> not
    required and not selected (a reciprocating-pump standard is not asked of a
    centrifugal pump);
  * the sheet states no sub-type (or none the table knows) -> the standard is
    NOT dropped and NOT a "contractor did not reference it" row: it is asked of
    the engineer ("unsure"), with the reason.

A standard the table does not mention, or an equipment type with no sub-types,
behaves as before. Pure functions; data in the table, no code names a pump type.
"""

from __future__ import annotations

import re


def _stated(words_by_subtype: dict, text: str) -> set[str]:
    return {
        sub
        for sub, words in words_by_subtype.items()
        if any(re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE) for w in words)
    }


def classify(
    kind: str, identifier: str, text: str, table: dict
) -> tuple[str, list[str]]:
    """("required" | "other" | "unsure", the sub-types the standard governs)."""
    spec = (table.get("equipment_subtypes") or {}).get(kind) or {}
    governed = next(
        (
            g
            for std, g in (spec.get("standards") or {}).items()
            if std.casefold() == identifier.casefold()
        ),
        None,
    )
    if not governed:
        return "required", []
    stated = _stated(spec.get("subtypes") or {}, text)
    if len(stated) != 1:
        # none stated, or two types named (a pump with a reciprocating driver,
        # a spare of another type): the sheet does not say which it is
        return "unsure", list(governed)
    return ("required" if stated & set(governed) else "other"), list(governed)


def required(equipment, source, text, table, by) -> list[dict]:
    """The standards the equipment type requires, with sub-types applied: a
    list of {"identifier", "by", "reason"[, "unsure", "governs"]}."""
    out: list[dict] = []
    for kind in sorted(equipment):
        for identifier in table["equipment_types"].get(kind, []):
            verdict, governed = classify(kind, identifier, text, table)
            if verdict == "other":
                continue
            entry = {
                "identifier": identifier,
                "by": by,
                "reason": f"it governs a {kind} (read from the submittal's {source})",
            }
            if verdict == "unsure":
                entry |= {"unsure": True, "governs": governed, "kind": kind}
            out.append(entry)
    return out


def identifiers(kind: str, text: str, table: dict) -> list[tuple[str, str]]:
    """[(standard, "required" | "unsure")] to select for the review: those whose
    sub-type the sheet states (or that have none) are compared; an unsure one is
    selected HELD for the engineer (never compared, never dropped silently)."""
    out = []
    for i in table["equipment_types"].get(kind, []):
        verdict = classify(kind, i, text, table)[0]
        if verdict != "other":
            out.append((i, verdict))
    return out


def row(identifier: str, verdict: str, where: str) -> dict:
    """The selection row of a governing standard; held when its sub-type is unsure."""
    from .applicability import METHOD_GOVERNING
    from .held_standards import HELD_SUBTYPE_UNSURE

    out = {
        "method": METHOD_GOVERNING,
        "identifier": identifier,
        "reason": f"{identifier} governs a {where}",
    }
    if verdict == "unsure":
        out["held_for_engineer"] = (
            "held for the engineer to check: the datasheet does not state which type it is "
            "(or names more than one), and this standard governs one type only"
        )
        out["held_code"] = HELD_SUBTYPE_UNSURE
    return out


def not_cited_words(r: dict) -> str:
    """The CRS comment of a required standard the contractor did not cite."""
    ident = r["identifier"]
    if r.get("unsure"):
        return (
            f"Engineer to check whether {ident} applies: it governs only "
            f"{' / '.join(r.get('governs') or [])} {r.get('kind') or 'equipment'}, "
            f"and the datasheet does not state the {r.get('kind') or 'equipment'} type."
        )
    return (
        f"Contractor did not reference {ident}; confirm compliance with "
        f"{ident} (required because {r['reason']})."
    )
